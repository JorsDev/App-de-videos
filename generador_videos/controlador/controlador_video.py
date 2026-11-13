"""
Controlador principal: orquesta la Vista y el Modelo.

Responsabilidades:
    * Recibir los eventos de la Vista y actualizar el ``ProyectoVideo``.
    * Validar el proyecto y el sistema antes de generar.
    * Ejecutar alineación (Whisper) y renderizado (FFmpeg) en un
      ``threading.Thread`` secundario para no congelar la interfaz.
    * Comunicar el progreso a la Vista de forma segura: el hilo de trabajo
      NUNCA toca widgets; deposita tareas en una ``queue.Queue`` que se vacía
      desde el hilo de la interfaz mediante ``after()``.
    * Gestionar cancelación y cierre seguro de la aplicación.
"""

from __future__ import annotations

import copy
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from modelo import (
    AlineacionCancelada,
    AlineadorAudio,
    ErrorAlineacion,
    ErrorFFmpeg,
    ErrorValidacionProyecto,
    FormatoVideo,
    GeneradorSubtitulos,
    MotorFFmpeg,
    ProyectoVideo,
    RenderizadoCancelado,
)
from modelo.proyecto_video import clave_orden_natural
from utilidades import GestorTemporales, InformacionSistema, verificar_sistema

if TYPE_CHECKING:  # Solo para anotaciones: evita acoplar el Controlador a una Vista concreta.
    from vista.ventana_principal import VentanaPrincipal

registro = logging.getLogger(__name__)

# Intervalo (ms) con el que el hilo de la UI revisa la cola de tareas.
INTERVALO_REVISION_COLA_MS = 80
# Tiempo máximo (s) de espera al cerrar mientras se cancela un proceso.
ESPERA_MAXIMA_CIERRE_S = 10.0

# Reparto del progreso global entre etapas del pipeline.
RANGO_PREPARACION = (0.00, 0.03)
RANGO_ALINEACION = (0.03, 0.45)
RANGO_SUBTITULOS = (0.45, 0.48)
RANGO_RENDERIZADO = (0.48, 1.00)


class EstadoControlador(Enum):
    """Estados posibles de la aplicación."""

    INACTIVO = auto()
    PROCESANDO = auto()
    CANCELANDO = auto()


def formatear_duracion(segundos: float) -> str:
    """Convierte segundos a 'm:ss' o 'h:mm:ss'."""
    segundos_totales = int(round(segundos))
    horas, resto = divmod(segundos_totales, 3600)
    minutos, segundos_restantes = divmod(resto, 60)
    return f"{horas}:{minutos:02d}:{segundos_restantes:02d}" if horas else f"{minutos}:{segundos_restantes:02d}"


class ControladorVideo:
    """Coordina la interacción entre ``VentanaPrincipal`` y la capa Modelo."""

    def __init__(self, vista: "VentanaPrincipal", proyecto: ProyectoVideo | None = None) -> None:
        self.vista = vista
        self.proyecto = proyecto or ProyectoVideo()

        self.estado = EstadoControlador.INACTIVO
        self._cola_tareas_vista: queue.Queue[tuple[Callable[..., Any], tuple]] = queue.Queue()
        self._evento_cancelacion = threading.Event()
        self._hilo_trabajo: threading.Thread | None = None
        self._informacion_sistema: InformacionSistema | None = None
        self._alineador: AlineadorAudio | None = None
        self._ruta_ultimo_video: Path | None = None
        self._cerrando = False

        self._registrar_acciones_vista()
        self._establecer_carpeta_salida_por_defecto()
        self._sincronizar_vista_con_proyecto()
        self._iniciar_revision_cola()
        self._ejecutar_en_segundo_plano(self._tarea_verificar_sistema, nombre="HiloVerificacionSistema")

    # ================================================================== #
    # Configuración inicial
    # ================================================================== #
    def _registrar_acciones_vista(self) -> None:
        acciones: dict[str, Callable[..., Any]] = {
            "seleccionar_audio_voz": self.seleccionar_audio_voz,
            "quitar_audio_voz": self.quitar_audio_voz,
            "cargar_guion_archivo": self.cargar_guion_desde_archivo,
            "agregar_imagenes": self.agregar_imagenes,
            "agregar_carpeta_imagenes": self.agregar_carpeta_imagenes,
            "mover_imagen": self.mover_imagen,
            "quitar_imagen": self.quitar_imagen,
            "ordenar_imagenes": self.ordenar_imagenes_por_nombre,
            "limpiar_imagenes": self.limpiar_imagenes,
            "seleccionar_musica": self.seleccionar_musica_fondo,
            "quitar_musica": self.quitar_musica_fondo,
            "seleccionar_carpeta_salida": self.seleccionar_carpeta_salida,
            "generar_video": self.generar_video,
            "cancelar_proceso": self.cancelar_proceso,
            "abrir_resultado": self.abrir_video_generado,
            "cerrar_aplicacion": self.cerrar_aplicacion,
        }
        for nombre_accion, funcion in acciones.items():
            self.vista.registrar_accion(nombre_accion, funcion)

    def _establecer_carpeta_salida_por_defecto(self) -> None:
        if self.proyecto.carpeta_salida is None:
            carpeta_videos = Path.home() / "Videos"
            self.proyecto.carpeta_salida = carpeta_videos if carpeta_videos.is_dir() else Path.home()

    def _sincronizar_vista_con_proyecto(self) -> None:
        """Refleja en la Vista el estado actual del proyecto."""
        proyecto = self.proyecto
        self.vista.mostrar_audio_voz(proyecto.ruta_audio_voz.name if proyecto.ruta_audio_voz else None)
        if proyecto.texto_guion:
            self.vista.establecer_texto_guion(proyecto.texto_guion)
        self._refrescar_lista_imagenes()
        self.vista.mostrar_musica(proyecto.ruta_musica_fondo.name if proyecto.ruta_musica_fondo else None)
        self.vista.mostrar_carpeta_salida(str(proyecto.carpeta_salida) if proyecto.carpeta_salida else None)

    # ================================================================== #
    # Comunicación segura hilo de trabajo → hilo de la interfaz
    # ================================================================== #
    def _enviar_a_vista(self, funcion: Callable[..., Any], *argumentos: Any) -> None:
        """Encola una función para ejecutarla en el hilo de la interfaz (seguro desde cualquier hilo)."""
        self._cola_tareas_vista.put((funcion, argumentos))

    def _iniciar_revision_cola(self) -> None:
        self.vista.programar(INTERVALO_REVISION_COLA_MS, self._procesar_cola_vista)

    def _procesar_cola_vista(self) -> None:
        """Ejecuta (en el hilo de la UI) todas las tareas pendientes y se reprograma con ``after()``."""
        ultima_actualizacion_progreso: tuple | None = None
        try:
            while True:
                funcion, argumentos = self._cola_tareas_vista.get_nowait()
                if funcion == self._mostrar_progreso_en_vista:
                    # Solo interesa el último valor de progreso de cada lote.
                    ultima_actualizacion_progreso = argumentos
                    continue
                self._ejecutar_tarea_vista_protegida(funcion, argumentos)
        except queue.Empty:
            pass
        if ultima_actualizacion_progreso is not None:
            self._ejecutar_tarea_vista_protegida(self._mostrar_progreso_en_vista, ultima_actualizacion_progreso)
        if not self._cerrando:
            self.vista.programar(INTERVALO_REVISION_COLA_MS, self._procesar_cola_vista)

    @staticmethod
    def _ejecutar_tarea_vista_protegida(funcion: Callable[..., Any], argumentos: tuple) -> None:
        try:
            funcion(*argumentos)
        except Exception:  # noqa: BLE001 - un fallo de UI no debe detener la cola
            registro.exception("Error al actualizar la interfaz")

    def _ejecutar_en_segundo_plano(self, funcion: Callable[..., Any], *argumentos: Any, nombre: str) -> threading.Thread:
        hilo = threading.Thread(target=funcion, args=argumentos, name=nombre, daemon=True)
        hilo.start()
        return hilo

    def _informar_progreso(self, fraccion: float, mensaje: str) -> None:
        """Llamado desde el hilo de trabajo."""
        self._enviar_a_vista(self._mostrar_progreso_en_vista, fraccion, mensaje)

    def _mostrar_progreso_en_vista(self, fraccion: float, mensaje: str) -> None:
        if self.estado == EstadoControlador.CANCELANDO:
            mensaje = "Cancelando..."
        self.vista.actualizar_progreso(fraccion, mensaje)

    @staticmethod
    def _escalar_progreso(rango: tuple[float, float], callback: Callable[[float, str], None]) -> Callable[[float, str], None]:
        """Convierte un progreso local 0..1 en el tramo global indicado."""
        inicio, fin = rango
        return lambda fraccion, mensaje: callback(inicio + (fin - inicio) * fraccion, mensaje)

    # ================================================================== #
    # Verificación del sistema
    # ================================================================== #
    def _tarea_verificar_sistema(self) -> None:
        """Hilo secundario: la importación de ctranslate2 puede tardar algunos segundos."""
        informacion = verificar_sistema()
        eliminadas = GestorTemporales.limpiar_residuos_antiguos()
        if eliminadas:
            registro.info("Se eliminaron %d carpetas temporales antiguas", eliminadas)
        self._enviar_a_vista(self._al_terminar_verificacion_sistema, informacion)

    def _al_terminar_verificacion_sistema(self, informacion: InformacionSistema) -> None:
        self._informacion_sistema = informacion
        partes = [
            f"FFmpeg {informacion.version_ffmpeg}" if informacion.ffmpeg_disponible else "⚠ FFmpeg no encontrado",
            "GPU CUDA" if informacion.gpu_cuda_disponible else "CPU",
        ]
        if informacion.ffmpeg_disponible and not informacion.soporta_subtitulos_ass:
            partes.append("⚠ sin libass")
        self.vista.mostrar_estado_sistema("  ·  ".join(partes), informacion.sistema_listo)
        if not informacion.ffmpeg_disponible:
            self.vista.mostrar_advertencia(
                "FFmpeg no encontrado",
                "No se encontró FFmpeg en el sistema. Puedes preparar el proyecto, "
                "pero no podrás generar videos hasta instalarlo:\n\n"
                "    winget install Gyan.FFmpeg\n\n"
                "Después reinicia la aplicación.",
            )

    def _validar_sistema(self) -> list[str]:
        informacion = self._informacion_sistema
        if informacion is None:
            return ["El sistema aún se está verificando. Intenta de nuevo en unos segundos."]
        errores = []
        if not informacion.ffmpeg_disponible:
            errores.append("FFmpeg/FFprobe no están instalados o no están en el PATH.")
        if self.proyecto.subtitulos_activados and informacion.ffmpeg_disponible and not informacion.soporta_subtitulos_ass:
            errores.append("Tu FFmpeg no soporta subtítulos (libass). Desactiva los subtítulos o instala otra build.")
        return errores

    # ================================================================== #
    # Eventos de entradas
    # ================================================================== #
    def seleccionar_audio_voz(self, ruta: str) -> None:
        self.proyecto.ruta_audio_voz = Path(ruta)
        self.vista.mostrar_audio_voz(Path(ruta).name, "calculando duración...")
        self._ejecutar_en_segundo_plano(self._tarea_calcular_duracion_voz, Path(ruta), nombre="HiloDuracionVoz")

    def quitar_audio_voz(self) -> None:
        """Limpia la selección del audio principal de voz."""
        self.proyecto.quitar_audio_voz()
        self.vista.mostrar_audio_voz(None)

    def _tarea_calcular_duracion_voz(self, ruta: Path) -> None:
        detalle = ""
        informacion = self._informacion_sistema or verificar_sistema()
        if informacion.ruta_ffprobe:
            try:
                duracion = MotorFFmpeg(ruta_ffprobe=informacion.ruta_ffprobe).obtener_duracion_medio(ruta)
                detalle = f"duración {formatear_duracion(duracion)}"
            except ErrorFFmpeg:
                detalle = "no se pudo leer la duración"
        # Solo actualizar si el usuario no cambió de archivo mientras tanto.
        self._enviar_a_vista(
            lambda: self.vista.mostrar_audio_voz(ruta.name, detalle) if self.proyecto.ruta_audio_voz == ruta else None
        )

    def cargar_guion_desde_archivo(self, ruta: str) -> None:
        try:
            texto = ProyectoVideo.cargar_guion_desde_archivo(ruta)
        except (OSError, ValueError) as error:
            self.vista.mostrar_error("No se pudo cargar el guion", str(error))
            return
        self.proyecto.texto_guion = texto
        self.vista.establecer_texto_guion(texto)
        self.vista.mostrar_mensaje_estado(f"Guion cargado: {Path(ruta).name}")

    def agregar_imagenes(self, rutas: list[str]) -> None:
        cantidad_previa = len(self.proyecto.rutas_imagenes)
        agregadas = self.proyecto.agregar_imagenes(rutas)
        self._refrescar_lista_imagenes(cantidad_previa if agregadas else None)
        self._informar_imagenes_ignoradas(len(rutas) - agregadas)

    def agregar_carpeta_imagenes(self, carpeta: str) -> None:
        try:
            rutas = ProyectoVideo.listar_imagenes_de_carpeta(carpeta)
        except NotADirectoryError as error:
            self.vista.mostrar_error("Carpeta no válida", str(error))
            return
        if not rutas:
            self.vista.mostrar_advertencia("Sin imágenes", "La carpeta no contiene imágenes .jpg, .png o .webp.")
            return
        self.agregar_imagenes([str(ruta) for ruta in rutas])

    def _informar_imagenes_ignoradas(self, cantidad: int) -> None:
        if cantidad > 0:
            self.vista.mostrar_mensaje_estado(f"Se ignoraron {cantidad} archivo(s) duplicados o con formato no permitido.", "advertencia")

    def mover_imagen(self, indice: int, desplazamiento: int) -> None:
        try:
            nuevo_indice = self.proyecto.mover_imagen(indice, desplazamiento)
        except IndexError:
            return
        self._refrescar_lista_imagenes(nuevo_indice)

    def quitar_imagen(self, indice: int) -> None:
        if 0 <= indice < len(self.proyecto.rutas_imagenes):
            self.proyecto.quitar_imagen(indice)
            self._refrescar_lista_imagenes()

    def ordenar_imagenes_por_nombre(self) -> None:
        self.proyecto.rutas_imagenes.sort(key=clave_orden_natural)
        self._refrescar_lista_imagenes()

    def limpiar_imagenes(self) -> None:
        if self.proyecto.rutas_imagenes and self.vista.preguntar_confirmacion(
            "Quitar imágenes", "¿Quitar todas las imágenes de la lista?"
        ):
            self.proyecto.rutas_imagenes.clear()
            self._refrescar_lista_imagenes()

    def _refrescar_lista_imagenes(self, indice_seleccionado: int | None = None) -> None:
        self.vista.mostrar_imagenes([str(ruta) for ruta in self.proyecto.rutas_imagenes], indice_seleccionado)

    def seleccionar_musica_fondo(self, ruta: str) -> None:
        self.proyecto.ruta_musica_fondo = Path(ruta)
        self.vista.mostrar_musica(Path(ruta).name)

    def quitar_musica_fondo(self) -> None:
        self.proyecto.quitar_musica_fondo()
        self.vista.mostrar_musica(None)

    def seleccionar_carpeta_salida(self, carpeta: str) -> None:
        self.proyecto.carpeta_salida = Path(carpeta)
        self.vista.mostrar_carpeta_salida(carpeta)

    # ================================================================== #
    # Generación del video
    # ================================================================== #
    def _aplicar_configuracion_de_vista(self) -> dict:
        """Copia al proyecto los valores actuales del formulario."""
        configuracion = self.vista.obtener_configuracion()
        self.proyecto.texto_guion = self.vista.obtener_texto_guion()
        self.proyecto.volumen_musica = float(configuracion["volumen_musica"])
        self.proyecto.subtitulos_activados = bool(configuracion["subtitulos_activados"])
        self.proyecto.efecto_ken_burns_activado = bool(configuracion["efecto_ken_burns_activado"])
        self.proyecto.formato_video = FormatoVideo.desde_etiqueta(configuracion["etiqueta_formato"])
        self.proyecto.nombre_archivo_salida = configuracion["nombre_archivo_salida"]
        return configuracion

    def generar_video(self) -> None:
        """Valida y lanza el pipeline completo en un hilo secundario."""
        if self.estado != EstadoControlador.INACTIVO:
            return
        configuracion = self._aplicar_configuracion_de_vista()
        errores = self.proyecto.validar() + self._validar_sistema()
        if errores:
            self.vista.mostrar_errores_validacion(errores)
            return

        # Copia independiente: los cambios en la UI durante el proceso no afectan al render.
        proyecto_congelado = copy.deepcopy(self.proyecto)
        self._evento_cancelacion = threading.Event()
        self._ruta_ultimo_video = None
        self._cambiar_estado(EstadoControlador.PROCESANDO)
        self.vista.actualizar_progreso(0.0, "Iniciando...")

        self._hilo_trabajo = self._ejecutar_en_segundo_plano(
            self._tarea_generar_video,
            proyecto_congelado,
            configuracion["modelo_whisper"],
            configuracion["idioma"],
            nombre="HiloGeneracionVideo",
        )

    def _obtener_alineador(self, nombre_modelo: str, idioma: str | None) -> AlineadorAudio:
        """Reutiliza el modelo ya cargado si no cambió (evita recargarlo en cada video)."""
        if self._alineador is None or self._alineador.nombre_modelo != nombre_modelo:
            if self._alineador is not None:
                self._alineador.liberar_modelo()
            self._alineador = AlineadorAudio(nombre_modelo=nombre_modelo, idioma=idioma)
        self._alineador.idioma = idioma
        return self._alineador

    def _tarea_generar_video(self, proyecto: ProyectoVideo, nombre_modelo: str, idioma: str | None) -> None:
        """Pipeline completo. Se ejecuta en el hilo secundario: NO toca widgets."""
        instante_inicio = time.perf_counter()
        informacion = self._informacion_sistema
        assert informacion is not None and informacion.ruta_ffmpeg and informacion.ruta_ffprobe
        evento = self._evento_cancelacion

        try:
            with GestorTemporales() as temporales:
                motor = MotorFFmpeg(informacion.ruta_ffmpeg, informacion.ruta_ffprobe)

                # 1) Preparación
                self._informar_progreso(RANGO_PREPARACION[0], "Analizando audio de voz...")
                duracion_voz = motor.obtener_duracion_medio(proyecto.ruta_audio_voz)
                bloques_guion = proyecto.dividir_guion_en_bloques()
                self._informar_progreso(
                    RANGO_PREPARACION[1], f"Audio de {formatear_duracion(duracion_voz)} · {len(bloques_guion)} bloques de guion"
                )

                # 2) Alineación audio ↔ guion
                alineador = self._obtener_alineador(nombre_modelo, idioma)
                if alineador._modelo is None:  # noqa: SLF001 - solo para informar al usuario
                    self._informar_progreso(
                        RANGO_ALINEACION[0], f"Cargando modelo Whisper '{nombre_modelo}' (la primera vez se descarga)..."
                    )
                resultado_alineacion = alineador.alinear_guion_con_audio(
                    proyecto.ruta_audio_voz,
                    bloques_guion,
                    self._escalar_progreso(RANGO_ALINEACION, self._informar_progreso),
                    evento,
                )

                # 3) Subtítulos (opcional)
                ruta_subtitulos = None
                if proyecto.subtitulos_activados:
                    self._informar_progreso(RANGO_SUBTITULOS[0], "Generando subtítulos dinámicos...")
                    ruta_subtitulos = GeneradorSubtitulos(proyecto.ancho, proyecto.alto).generar_archivo_ass(
                        resultado_alineacion.bloques, temporales.crear_ruta_temporal("subtitulos.ass"), duracion_voz
                    )

                # 4) Línea de tiempo y renderizado
                segmentos = MotorFFmpeg.calcular_linea_tiempo_imagenes(
                    proyecto.rutas_imagenes, resultado_alineacion.bloques, duracion_voz
                )
                self._informar_progreso(RANGO_SUBTITULOS[1], f"Preparando {len(segmentos)} imágenes...")
                ruta_video = motor.renderizar_video_final(
                    proyecto,
                    segmentos,
                    duracion_voz,
                    temporales.directorio_trabajo,
                    ruta_subtitulos,
                    self._escalar_progreso(RANGO_RENDERIZADO, self._informar_progreso),
                    evento,
                )

            tiempo_total = time.perf_counter() - instante_inicio
            self._enviar_a_vista(self._al_finalizar_con_exito, ruta_video, tiempo_total, resultado_alineacion.porcentaje_coincidencia)

        except (AlineacionCancelada, RenderizadoCancelado):
            self._enviar_a_vista(self._al_cancelar_completado)
        except (ErrorValidacionProyecto, ErrorAlineacion, ErrorFFmpeg, ValueError) as error:
            registro.warning("Error controlado en la generación: %s", error)
            self._enviar_a_vista(self._al_fallar, str(error))
        except Exception as error:  # noqa: BLE001
            registro.exception("Error inesperado en la generación")
            self._enviar_a_vista(self._al_fallar, f"Error inesperado: {error!r}")

    # ----------------------- Resultados (hilo UI) ---------------------- #
    def _al_finalizar_con_exito(self, ruta_video: Path, segundos: float, porcentaje_coincidencia: float) -> None:
        self._ruta_ultimo_video = ruta_video
        self._cambiar_estado(EstadoControlador.INACTIVO)
        self.vista.actualizar_progreso(1.0)
        self.vista.mostrar_mensaje_estado(
            f"✔ Video generado en {formatear_duracion(segundos)}: {ruta_video.name} "
            f"(coincidencia guion-audio {porcentaje_coincidencia}%)",
            "exito",
        )
        self.vista.habilitar_abrir_resultado(True)
        if self._cerrando:
            return
        if porcentaje_coincidencia < 60:
            self.vista.mostrar_advertencia(
                "Sincronización aproximada",
                f"Solo el {porcentaje_coincidencia}% del guion coincidió con el audio. "
                "Revisa que el guion corresponda a la locución o elige un modelo de IA más preciso.",
            )

    def _al_cancelar_completado(self) -> None:
        self._cambiar_estado(EstadoControlador.INACTIVO)
        self.vista.actualizar_progreso(0.0)
        self.vista.mostrar_mensaje_estado("Proceso cancelado. No se generó ningún video.", "advertencia")

    def _al_fallar(self, mensaje: str) -> None:
        self._cambiar_estado(EstadoControlador.INACTIVO)
        self.vista.mostrar_mensaje_estado("✖ Ocurrió un error durante la generación.", "error")
        if not self._cerrando:
            self.vista.mostrar_error("Error al generar el video", mensaje)

    def _cambiar_estado(self, nuevo_estado: EstadoControlador) -> None:
        self.estado = nuevo_estado
        self.vista.establecer_procesando(nuevo_estado != EstadoControlador.INACTIVO)

    # ================================================================== #
    # Cancelación, resultado y cierre
    # ================================================================== #
    def cancelar_proceso(self) -> None:
        if self.estado == EstadoControlador.PROCESANDO:
            self.estado = EstadoControlador.CANCELANDO
            self._evento_cancelacion.set()
            self.vista.mostrar_mensaje_estado("Cancelando... (esperando a que termine la etapa actual)", "advertencia")

    def abrir_video_generado(self) -> None:
        """Abre el explorador de archivos con el video generado seleccionado."""
        ruta = self._ruta_ultimo_video
        if ruta is None or not ruta.exists():
            self.vista.mostrar_advertencia("Video no disponible", "No se encontró el último video generado.")
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", f"/select,{ruta}"])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(ruta)])
            else:
                subprocess.Popen(["xdg-open", str(ruta.parent)])
        except OSError as error:
            self.vista.mostrar_error("No se pudo abrir la carpeta", str(error))

    def cerrar_aplicacion(self) -> None:
        """Cierre seguro: si hay un proceso activo, lo cancela y espera a que FFmpeg termine."""
        if self.estado == EstadoControlador.INACTIVO:
            self._finalizar_cierre()
            return
        if not self.vista.preguntar_confirmacion(
            "Proceso en curso", "Se está generando un video. ¿Cancelar el proceso y salir?"
        ):
            return
        self._cerrando = True
        self.cancelar_proceso()
        self._esperar_hilo_y_cerrar(time.monotonic())

    def _esperar_hilo_y_cerrar(self, instante_inicio: float) -> None:
        hilo_activo = self._hilo_trabajo is not None and self._hilo_trabajo.is_alive()
        if hilo_activo and time.monotonic() - instante_inicio < ESPERA_MAXIMA_CIERRE_S:
            self.vista.programar(200, lambda: self._esperar_hilo_y_cerrar(instante_inicio))
            return
        self._finalizar_cierre()

    def _finalizar_cierre(self) -> None:
        self._cerrando = True
        if self._alineador is not None:
            self._alineador.liberar_modelo()
        self.vista.cerrar()
