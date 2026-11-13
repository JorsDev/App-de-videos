"""
Ventana principal de la aplicación (CustomTkinter).

Distribución en tres columnas:
    [ Voz + Guion ]  [ Imágenes + vista previa ]  [ Música + Exportación ]
    [ ---------------- Progreso y acciones (ancho completo) ---------------- ]

Comunicación con el Controlador:
    * Eventos: el Controlador registra funciones con ``registrar_accion(nombre, funcion)``.
      La Vista las invoca cuando el usuario interactúa (ver ``ACCIONES_DISPONIBLES``).
    * Actualización: el Controlador llama a los métodos públicos de esta clase
      (``mostrar_imagenes``, ``actualizar_progreso``, ``mostrar_error``...).

La Vista no importa el Modelo, FFmpeg ni Whisper.
"""

from __future__ import annotations

from tkinter import messagebox
from typing import Any, Callable

import customtkinter as ctk

from vista import estilos
from vista.estilos import COLORES, ESPACIADO, FUENTES
from vista.paneles import (
    PanelAudioVoz,
    PanelExportacion,
    PanelGuion,
    PanelImagenes,
    PanelMusica,
    PanelProgreso,
)

# Nombres de los eventos que la Vista puede emitir hacia el Controlador.
ACCIONES_DISPONIBLES = (
    "seleccionar_audio_voz",      # (ruta: str)
    "quitar_audio_voz",           # ()
    "cargar_guion_archivo",       # (ruta: str)
    "agregar_imagenes",           # (rutas: list[str])
    "agregar_carpeta_imagenes",   # (carpeta: str)
    "mover_imagen",               # (indice: int, desplazamiento: int)
    "quitar_imagen",              # (indice: int)
    "ordenar_imagenes",           # ()
    "limpiar_imagenes",           # ()
    "seleccionar_musica",         # (ruta: str)
    "quitar_musica",              # ()
    "seleccionar_carpeta_salida", # (carpeta: str)
    "generar_video",              # ()
    "cancelar_proceso",           # ()
    "abrir_resultado",            # ()
    "cerrar_aplicacion",          # ()
)


class VentanaPrincipal(ctk.CTk):
    """Ventana raíz de la aplicación."""

    def __init__(self) -> None:
        ctk.set_appearance_mode(estilos.MODO_APARIENCIA)
        ctk.set_default_color_theme(estilos.TEMA_COLOR)
        super().__init__(fg_color=COLORES["fondo"])

        self.title(estilos.TITULO_APLICACION)
        self.geometry(estilos.TAMANO_VENTANA_INICIAL)
        self.minsize(*estilos.TAMANO_VENTANA_MINIMO)

        self._acciones: dict[str, Callable[..., Any]] = {}

        self._construir_cabecera()
        self._construir_cuerpo()
        self._construir_pie()

        self.protocol("WM_DELETE_WINDOW", lambda: self._emitir("cerrar_aplicacion", respaldo=self.destroy))

    # ------------------------------------------------------------------ #
    # Construcción de la interfaz
    # ------------------------------------------------------------------ #
    def _construir_cabecera(self) -> None:
        cabecera = ctk.CTkFrame(self, fg_color="transparent")
        cabecera.grid(row=0, column=0, sticky="ew", padx=ESPACIADO * 2, pady=(int(ESPACIADO * 1.5), ESPACIADO))
        cabecera.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(cabecera, text="🎬  " + estilos.TITULO_APLICACION, font=FUENTES["titulo"]).grid(
            row=0, column=0, sticky="w"
        )
        self.etiqueta_estado_sistema = ctk.CTkLabel(
            cabecera, text="⏳ Verificando sistema...", font=FUENTES["pequena"],
            text_color=COLORES["texto_secundario"], anchor="e", justify="right",
        )
        self.etiqueta_estado_sistema.grid(row=0, column=1, sticky="e")

    def _construir_cuerpo(self) -> None:
        cuerpo = ctk.CTkFrame(self, fg_color="transparent")
        cuerpo.grid(row=1, column=0, sticky="nsew", padx=ESPACIADO * 2)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        cuerpo.grid_rowconfigure(0, weight=1)
        cuerpo.grid_columnconfigure(0, weight=5, uniform="columnas")
        cuerpo.grid_columnconfigure(1, weight=4, uniform="columnas")
        cuerpo.grid_columnconfigure(2, weight=3, uniform="columnas")

        # Columna 1: voz + guion
        columna_entradas = ctk.CTkFrame(cuerpo, fg_color="transparent")
        columna_entradas.grid(row=0, column=0, sticky="nsew", padx=(0, ESPACIADO))
        columna_entradas.grid_columnconfigure(0, weight=1)
        columna_entradas.grid_rowconfigure(1, weight=1)

        self.panel_audio_voz = PanelAudioVoz(
            columna_entradas,
            al_seleccionar_audio=lambda ruta: self._emitir("seleccionar_audio_voz", ruta),
            al_quitar_audio=lambda: self._emitir("quitar_audio_voz"),
        )
        self.panel_audio_voz.grid(row=0, column=0, sticky="ew", pady=(0, ESPACIADO))
        self.panel_guion = PanelGuion(
            columna_entradas, al_cargar_archivo=lambda ruta: self._emitir("cargar_guion_archivo", ruta)
        )
        self.panel_guion.grid(row=1, column=0, sticky="nsew")

        # Columna 2: imágenes
        self.panel_imagenes = PanelImagenes(
            cuerpo,
            al_agregar_archivos=lambda rutas: self._emitir("agregar_imagenes", rutas),
            al_agregar_carpeta=lambda carpeta: self._emitir("agregar_carpeta_imagenes", carpeta),
            al_mover_imagen=lambda indice, desplazamiento: self._emitir("mover_imagen", indice, desplazamiento),
            al_quitar_imagen=lambda indice: self._emitir("quitar_imagen", indice),
            al_ordenar_por_nombre=lambda: self._emitir("ordenar_imagenes"),
            al_limpiar_imagenes=lambda: self._emitir("limpiar_imagenes"),
        )
        self.panel_imagenes.grid(row=0, column=1, sticky="nsew", padx=(0, ESPACIADO))

        # Columna 3: música + exportación (desplazable en pantallas pequeñas)
        columna_ajustes = ctk.CTkScrollableFrame(cuerpo, fg_color="transparent")
        columna_ajustes.grid(row=0, column=2, sticky="nsew")
        columna_ajustes.grid_columnconfigure(0, weight=1)

        self.panel_musica = PanelMusica(
            columna_ajustes,
            al_seleccionar_musica=lambda ruta: self._emitir("seleccionar_musica", ruta),
            al_quitar_musica=lambda: self._emitir("quitar_musica"),
        )
        self.panel_musica.grid(row=0, column=0, sticky="ew", pady=(0, ESPACIADO))
        self.panel_exportacion = PanelExportacion(
            columna_ajustes,
            al_seleccionar_carpeta=lambda carpeta: self._emitir("seleccionar_carpeta_salida", carpeta),
            al_cambiar_formato=self.panel_imagenes.establecer_formato_previsualizacion,
        )
        self.panel_exportacion.grid(row=1, column=0, sticky="ew")

    def _construir_pie(self) -> None:
        self.panel_progreso = PanelProgreso(
            self,
            al_generar=lambda: self._emitir("generar_video"),
            al_cancelar=lambda: self._emitir("cancelar_proceso"),
            al_abrir_resultado=lambda: self._emitir("abrir_resultado"),
        )
        self.panel_progreso.grid(row=2, column=0, sticky="ew", padx=ESPACIADO * 2, pady=int(ESPACIADO * 1.5))

    # ------------------------------------------------------------------ #
    # Registro y emisión de acciones
    # ------------------------------------------------------------------ #
    def registrar_accion(self, nombre_accion: str, funcion: Callable[..., Any]) -> None:
        """Asocia un evento de la interfaz con una función del Controlador."""
        if nombre_accion not in ACCIONES_DISPONIBLES:
            raise ValueError(f"Acción desconocida: {nombre_accion!r}")
        self._acciones[nombre_accion] = funcion

    def _emitir(self, nombre_accion: str, *argumentos, respaldo: Callable[[], Any] | None = None) -> None:
        funcion = self._acciones.get(nombre_accion)
        if funcion is not None:
            funcion(*argumentos)
        elif respaldo is not None:
            respaldo()

    # ------------------------------------------------------------------ #
    # API pública para el Controlador: lectura de datos
    # ------------------------------------------------------------------ #
    def obtener_texto_guion(self) -> str:
        return self.panel_guion.obtener_texto()

    def obtener_configuracion(self) -> dict:
        """Opciones del formulario (exportación + volumen de música) como dict simple."""
        configuracion = self.panel_exportacion.obtener_configuracion()
        configuracion["volumen_musica"] = self.panel_musica.obtener_volumen()
        return configuracion

    # ------------------------------------------------------------------ #
    # API pública para el Controlador: actualización de la interfaz
    # ------------------------------------------------------------------ #
    def mostrar_audio_voz(self, nombre_archivo: str | None, detalle: str = "") -> None:
        self.panel_audio_voz.mostrar_archivo(nombre_archivo, detalle)

    def establecer_texto_guion(self, texto: str) -> None:
        self.panel_guion.establecer_texto(texto)

    def mostrar_imagenes(self, rutas: list[str], indice_seleccionado: int | None = None) -> None:
        self.panel_imagenes.mostrar_imagenes(rutas, indice_seleccionado)

    def mostrar_musica(self, nombre_archivo: str | None) -> None:
        self.panel_musica.mostrar_archivo(nombre_archivo)

    def mostrar_carpeta_salida(self, ruta: str | None) -> None:
        self.panel_exportacion.mostrar_carpeta_salida(ruta)

    def mostrar_estado_sistema(self, texto: str, sistema_listo: bool) -> None:
        self.etiqueta_estado_sistema.configure(
            text=texto, text_color=COLORES["exito"] if sistema_listo else COLORES["advertencia"]
        )

    def actualizar_progreso(self, fraccion: float, mensaje: str | None = None) -> None:
        self.panel_progreso.actualizar_progreso(fraccion, mensaje)

    def mostrar_mensaje_estado(self, mensaje: str, tipo: str = "normal") -> None:
        self.panel_progreso.mostrar_mensaje(mensaje, tipo)

    def establecer_procesando(self, procesando: bool) -> None:
        self.panel_progreso.establecer_procesando(procesando)
        self.configure(cursor="watch" if procesando else "")

    def habilitar_abrir_resultado(self, habilitado: bool) -> None:
        self.panel_progreso.habilitar_abrir_resultado(habilitado)

    # ------------------------------------------------------------------ #
    # Diálogos
    # ------------------------------------------------------------------ #
    def mostrar_error(self, titulo: str, mensaje: str) -> None:
        messagebox.showerror(titulo, mensaje, parent=self)

    def mostrar_advertencia(self, titulo: str, mensaje: str) -> None:
        messagebox.showwarning(titulo, mensaje, parent=self)

    def mostrar_informacion(self, titulo: str, mensaje: str) -> None:
        messagebox.showinfo(titulo, mensaje, parent=self)

    def mostrar_errores_validacion(self, errores: list[str]) -> None:
        self.mostrar_advertencia("Revisa el proyecto", "Corrige lo siguiente antes de generar:\n\n• " + "\n• ".join(errores))

    def preguntar_confirmacion(self, titulo: str, mensaje: str) -> bool:
        return bool(messagebox.askyesno(titulo, mensaje, parent=self))

    # ------------------------------------------------------------------ #
    # Planificación en el hilo de la interfaz
    # ------------------------------------------------------------------ #
    def programar(self, milisegundos: int, funcion: Callable[[], Any]) -> str:
        """Envoltorio de ``after()`` para que el Controlador planifique tareas en el hilo de la UI."""
        return self.after(milisegundos, funcion)

    def cerrar(self) -> None:
        self.destroy()
