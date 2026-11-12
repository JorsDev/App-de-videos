"""
Motor de renderizado basado en FFmpeg CLI.

Pipeline de dos fases (estándar en flujos de postproducción automatizados):

    FASE 1 - Clips de imagen (0 % → 80 %)
        Cada imagen se convierte en un clip .mp4 independiente con la
        duración exacta (en frames) que le corresponde en la línea de tiempo:
            scale (cover) → crop → [zoompan Ken Burns] → yuv420p → libx264

    FASE 2 - Ensamblado final (80 % → 100 %)
        concat demuxer de los clips
        + [subtitles .ass quemados con libass]  (opcional)
        + voz principal
        + [música en loop, volumen ajustado, fundidos, amix + limitador] (opcional)
        → MP4 H.264/AAC con +faststart

Todos los comandos se ejecutan con ``subprocess`` y la carpeta temporal como
directorio de trabajo, lo que evita problemas de escapado de rutas de Windows
en los filtros (``subtitles=filename=subtitulos.ass``).
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from modelo.alineador_audio import BloqueAlineado
from modelo.proyecto_video import ProyectoVideo
from utilidades.verificador_sistema import BANDERAS_CREACION_PROCESO

CallbackProgreso = Optional[Callable[[float, str], None]]

# Reparto del progreso total entre las dos fases del renderizado.
PESO_FASE_CLIPS = 0.80
PESO_FASE_FINAL = 0.20

# Movimientos Ken Burns disponibles (se alternan imagen por imagen).
MOVIMIENTOS_KEN_BURNS = (
    "acercamiento_centro",
    "alejamiento_centro",
    "paneo_izquierda_derecha",
    "paneo_derecha_izquierda",
    "acercamiento_superior",
)
ZOOM_MAXIMO_KEN_BURNS = 0.15  # 15 % de acercamiento


class ErrorFFmpeg(Exception):
    """Fallo al ejecutar FFmpeg/FFprobe."""

    def __init__(self, mensaje: str, salida_error: str = "") -> None:
        self.salida_error = salida_error
        detalle = f"\n\nDetalle de FFmpeg:\n{salida_error.strip()[-1500:]}" if salida_error.strip() else ""
        super().__init__(mensaje + detalle)


class RenderizadoCancelado(Exception):
    """El usuario canceló el renderizado."""


@dataclass
class SegmentoImagen:
    """Tramo de la línea de tiempo cubierto por una imagen."""

    indice: int
    ruta_imagen: Path
    inicio: float
    fin: float

    @property
    def duracion(self) -> float:
        return max(0.0, self.fin - self.inicio)


class MotorFFmpeg:
    """Construye y ejecuta el pipeline de FFmpeg para generar el video final."""

    def __init__(
        self,
        ruta_ffmpeg: str = "ffmpeg",
        ruta_ffprobe: str = "ffprobe",
        preset_codificacion: str = "veryfast",
        calidad_crf_final: int = 20,
        calidad_crf_intermedia: int = 16,
        factor_sobremuestreo_ken_burns: int = 2,
        bitrate_audio: str = "192k",
    ) -> None:
        """
        Args:
            preset_codificacion: Preset de libx264 (ultrafast … veryslow).
            calidad_crf_final: CRF del video final (menor = más calidad).
            calidad_crf_intermedia: CRF de los clips temporales (alta calidad).
            factor_sobremuestreo_ken_burns: Escalado previo a zoompan para
                evitar el "temblor" típico del filtro (2 = doble resolución).
        """
        self.ruta_ffmpeg = ruta_ffmpeg
        self.ruta_ffprobe = ruta_ffprobe
        self.preset_codificacion = preset_codificacion
        self.calidad_crf_final = calidad_crf_final
        self.calidad_crf_intermedia = calidad_crf_intermedia
        self.factor_sobremuestreo_ken_burns = max(1, int(factor_sobremuestreo_ken_burns))
        self.bitrate_audio = bitrate_audio

    # ------------------------------------------------------------------ #
    # Información de medios
    # ------------------------------------------------------------------ #
    def obtener_duracion_medio(self, ruta_medio: str | Path) -> float:
        """Devuelve la duración en segundos de un archivo de audio/video (ffprobe)."""
        comando = [
            self.ruta_ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(ruta_medio),
        ]
        try:
            resultado = subprocess.run(
                comando, capture_output=True, text=True, timeout=60, creationflags=BANDERAS_CREACION_PROCESO
            )
        except FileNotFoundError as error:
            raise ErrorFFmpeg("No se encontró ffprobe. Instala FFmpeg y agrégalo al PATH.") from error
        except subprocess.SubprocessError as error:
            raise ErrorFFmpeg(f"ffprobe no respondió al analizar {ruta_medio}") from error
        if resultado.returncode != 0:
            raise ErrorFFmpeg(f"No se pudo leer la duración de {ruta_medio}", resultado.stderr)
        try:
            return float(resultado.stdout.strip())
        except ValueError as error:
            raise ErrorFFmpeg(f"Duración inválida para {ruta_medio}: {resultado.stdout!r}") from error

    # ------------------------------------------------------------------ #
    # Línea de tiempo de imágenes
    # ------------------------------------------------------------------ #
    @classmethod
    def calcular_linea_tiempo_imagenes(
        cls,
        rutas_imagenes: Sequence[str | Path],
        bloques_alineados: Sequence[BloqueAlineado],
        duracion_total: float,
    ) -> list[SegmentoImagen]:
        """
        Distribuye las imágenes cubriendo [0, duracion_total] sin huecos.

        Reglas:
            * Igual cantidad de imágenes y bloques → una imagen por bloque.
            * Menos imágenes que bloques → se agrupan bloques consecutivos
              buscando duraciones equilibradas.
            * Más imágenes que bloques → los bloques largos reciben varias
              imágenes (reparto proporcional) y se subdividen en partes iguales.
            * Sin bloques → reparto uniforme.
        La imagen cambia justo cuando empieza a pronunciarse el bloque siguiente.
        """
        if not rutas_imagenes:
            raise ValueError("Se necesita al menos una imagen para la línea de tiempo.")
        if duracion_total <= 0:
            raise ValueError("La duración total debe ser mayor que cero.")

        intervalos = cls._calcular_intervalos_de_bloques(bloques_alineados, duracion_total)
        cantidad_imagenes = len(rutas_imagenes)

        if not intervalos:
            paso = duracion_total / cantidad_imagenes
            tramos = [(i * paso, (i + 1) * paso) for i in range(cantidad_imagenes)]
        elif cantidad_imagenes == len(intervalos):
            tramos = intervalos
        elif cantidad_imagenes < len(intervalos):
            tramos = cls._agrupar_intervalos(intervalos, cantidad_imagenes, duracion_total)
        else:
            tramos = cls._subdividir_intervalos(intervalos, cantidad_imagenes)

        # Cierre exacto de la línea de tiempo (sin huecos por redondeo).
        tramos = list(tramos)
        tramos[0] = (0.0, tramos[0][1])
        tramos[-1] = (tramos[-1][0], duracion_total)

        return [
            SegmentoImagen(indice, Path(ruta), inicio, fin)
            for indice, (ruta, (inicio, fin)) in enumerate(zip(rutas_imagenes, tramos))
        ]

    @staticmethod
    def _calcular_intervalos_de_bloques(
        bloques_alineados: Sequence[BloqueAlineado], duracion_total: float
    ) -> list[tuple[float, float]]:
        """Convierte los bloques en intervalos contiguos que cubren todo el audio."""
        bloques = sorted((b for b in bloques_alineados if b.palabras or b.fin > b.inicio), key=lambda b: b.inicio)
        if not bloques:
            return []
        fronteras = [0.0]
        for bloque in bloques[1:]:
            frontera = min(max(bloque.inicio, fronteras[-1]), duracion_total)
            fronteras.append(frontera)
        fronteras.append(duracion_total)

        intervalos: list[tuple[float, float]] = []
        for inicio, fin in zip(fronteras[:-1], fronteras[1:]):
            if fin - inicio <= 1e-3 and intervalos:
                # Bloque degenerado (duración ~0): se fusiona con el anterior.
                intervalos[-1] = (intervalos[-1][0], fin)
            elif fin - inicio > 1e-3:
                intervalos.append((inicio, fin))
        return intervalos

    @staticmethod
    def _agrupar_intervalos(
        intervalos: list[tuple[float, float]], cantidad_grupos: int, duracion_total: float
    ) -> list[tuple[float, float]]:
        """Elige ``cantidad_grupos - 1`` cortes entre bloques lo más equilibrados posible."""
        fronteras_candidatas = [fin for _, fin in intervalos[:-1]]
        cortes: list[float] = []
        indice_minimo = 0
        for numero_corte in range(1, cantidad_grupos):
            objetivo = numero_corte * duracion_total / cantidad_grupos
            indice_maximo = len(fronteras_candidatas) - (cantidad_grupos - 1 - numero_corte) - 1
            mejor_indice = min(
                range(indice_minimo, indice_maximo + 1),
                key=lambda i: abs(fronteras_candidatas[i] - objetivo),
            )
            cortes.append(fronteras_candidatas[mejor_indice])
            indice_minimo = mejor_indice + 1
        limites = [0.0, *cortes, duracion_total]
        return list(zip(limites[:-1], limites[1:]))

    @staticmethod
    def _subdividir_intervalos(
        intervalos: list[tuple[float, float]], cantidad_imagenes: int
    ) -> list[tuple[float, float]]:
        """Asigna varias imágenes a los bloques más largos (método D'Hondt)."""
        imagenes_por_intervalo = [1] * len(intervalos)
        for _ in range(cantidad_imagenes - len(intervalos)):
            indice_mayor = max(
                range(len(intervalos)),
                key=lambda i: (intervalos[i][1] - intervalos[i][0]) / imagenes_por_intervalo[i],
            )
            imagenes_por_intervalo[indice_mayor] += 1

        tramos: list[tuple[float, float]] = []
        for (inicio, fin), cantidad in zip(intervalos, imagenes_por_intervalo):
            paso = (fin - inicio) / cantidad
            tramos.extend((inicio + i * paso, inicio + (i + 1) * paso) for i in range(cantidad))
        return tramos

    # ------------------------------------------------------------------ #
    # Filtros de video
    # ------------------------------------------------------------------ #
    @staticmethod
    def construir_filtro_estatico(ancho: int, alto: int) -> str:
        """Escala la imagen para cubrir el lienzo y recorta el sobrante (sin bandas negras)."""
        return (
            f"scale={ancho}:{alto}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={ancho}:{alto},setsar=1,format=yuv420p"
        )

    @staticmethod
    def construir_filtro_ken_burns(
        ancho: int, alto: int, cantidad_frames: int, fps: int, indice_imagen: int, factor_sobremuestreo: int = 2
    ) -> str:
        """
        Construye el filtro zoompan para el efecto Ken Burns.

        La imagen se sobremuestrea (factor x resolución final) antes de
        zoompan para que el movimiento sea suave y sin vibraciones.
        """
        ancho_grande = ancho * factor_sobremuestreo
        alto_grande = alto * factor_sobremuestreo
        denominador = max(cantidad_frames - 1, 1)
        progreso = f"(on/{denominador})"
        zoom = ZOOM_MAXIMO_KEN_BURNS
        centro_x = "iw/2-(iw/zoom/2)"
        centro_y = "ih/2-(ih/zoom/2)"

        movimiento = MOVIMIENTOS_KEN_BURNS[indice_imagen % len(MOVIMIENTOS_KEN_BURNS)]
        zoom_inicial_alejamiento = f"{1 + zoom:.4f}"
        zoom_fijo_paneo = f"{1 + zoom * 0.8:.4f}"
        if movimiento == "acercamiento_centro":
            expr_z, expr_x, expr_y = f"1+{zoom}*{progreso}", centro_x, centro_y
        elif movimiento == "alejamiento_centro":
            expr_z, expr_x, expr_y = f"{zoom_inicial_alejamiento}-{zoom}*{progreso}", centro_x, centro_y
        elif movimiento == "paneo_izquierda_derecha":
            expr_z, expr_x, expr_y = zoom_fijo_paneo, f"(iw-iw/zoom)*{progreso}", centro_y
        elif movimiento == "paneo_derecha_izquierda":
            expr_z, expr_x, expr_y = zoom_fijo_paneo, f"(iw-iw/zoom)*(1-{progreso})", centro_y
        else:  # acercamiento_superior
            expr_z, expr_x, expr_y = f"1+{zoom}*{progreso}", centro_x, f"(ih/2-(ih/zoom/2))*(1-{progreso})"

        return (
            f"scale={ancho_grande}:{alto_grande}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={ancho_grande}:{alto_grande},setsar=1,"
            f"zoompan=z='{expr_z}':x='{expr_x}':y='{expr_y}':d={cantidad_frames}:s={ancho}x{alto}:fps={fps},"
            f"format=yuv420p"
        )

    # ------------------------------------------------------------------ #
    # Renderizado
    # ------------------------------------------------------------------ #
    def renderizar_video_final(
        self,
        proyecto: ProyectoVideo,
        segmentos_imagen: list[SegmentoImagen],
        duracion_total: float,
        directorio_trabajo: str | Path,
        ruta_subtitulos_ass: str | Path | None = None,
        callback_progreso: CallbackProgreso = None,
        evento_cancelacion: threading.Event | None = None,
    ) -> Path:
        """
        Genera el .mp4 final.

        Args:
            proyecto: Proyecto validado (formato, fps, música, carpeta de salida...).
            segmentos_imagen: Resultado de ``calcular_linea_tiempo_imagenes``.
            duracion_total: Duración del audio de voz (segundos).
            directorio_trabajo: Carpeta temporal (``GestorTemporales``).
            ruta_subtitulos_ass: Archivo .ass a quemar o ``None`` para video limpio.
            callback_progreso: ``(fraccion 0..1, mensaje)``.
            evento_cancelacion: Al activarse, se detiene FFmpeg.

        Returns:
            Ruta del video generado.
        """
        if not segmentos_imagen:
            raise ValueError("No hay segmentos de imagen para renderizar.")
        directorio = Path(directorio_trabajo)
        directorio_clips = directorio / "clips"
        directorio_clips.mkdir(parents=True, exist_ok=True)

        # --- FASE 1: un clip por imagen --------------------------------
        frames_por_segmento = self._calcular_frames_por_segmento(segmentos_imagen, proyecto.fps)
        total_frames = sum(frames_por_segmento)
        frames_completados = 0
        nombres_clips: list[str] = []

        for segmento, cantidad_frames in zip(segmentos_imagen, frames_por_segmento):
            self._verificar_cancelacion(evento_cancelacion)
            nombre_clip = f"clip_{segmento.indice:04d}.mp4"
            mensaje = f"Renderizando imagen {segmento.indice + 1} de {len(segmentos_imagen)}..."
            base_progreso = frames_completados

            def progreso_clip(segundos: float, base=base_progreso, mensaje=mensaje) -> None:
                frames_hechos = min(base + segundos * proyecto.fps, total_frames)
                self._notificar(callback_progreso, PESO_FASE_CLIPS * frames_hechos / total_frames, mensaje)

            self._notificar(callback_progreso, PESO_FASE_CLIPS * frames_completados / total_frames, mensaje)
            comando_clip = self._construir_comando_clip(segmento, cantidad_frames, proyecto, directorio_clips / nombre_clip)
            self._ejecutar_ffmpeg(
                comando_clip, directorio, directorio / f"log_{nombre_clip}.txt", progreso_clip, evento_cancelacion
            )
            nombres_clips.append(nombre_clip)
            frames_completados += cantidad_frames

        # Lista para el concat demuxer (rutas relativas a la carpeta de la lista).
        ruta_lista = directorio_clips / "lista_clips.txt"
        ruta_lista.write_text("".join(f"file '{nombre}'\n" for nombre in nombres_clips), encoding="utf-8")

        # --- FASE 2: ensamblado final ----------------------------------
        nombre_ass: str | None = None
        if ruta_subtitulos_ass is not None:
            ruta_ass = Path(ruta_subtitulos_ass)
            if not ruta_ass.is_file():
                raise ErrorFFmpeg(f"No se encontró el archivo de subtítulos: {ruta_ass}")
            if ruta_ass.parent.resolve() != directorio.resolve():
                shutil.copy2(ruta_ass, directorio / ruta_ass.name)
            nombre_ass = ruta_ass.name

        ruta_salida = proyecto.obtener_ruta_salida()
        comando_final = self._construir_comando_final(proyecto, ruta_lista, nombre_ass, duracion_total, ruta_salida)

        def progreso_final(segundos: float) -> None:
            fraccion = min(1.0, segundos / duracion_total) if duracion_total > 0 else 0.0
            self._notificar(callback_progreso, PESO_FASE_CLIPS + PESO_FASE_FINAL * fraccion, "Ensamblando video final...")

        self._notificar(callback_progreso, PESO_FASE_CLIPS, "Ensamblando video final...")
        try:
            self._ejecutar_ffmpeg(
                comando_final, directorio, directorio / "log_final.txt", progreso_final, evento_cancelacion
            )
        except BaseException:
            # No dejar un .mp4 corrupto en la carpeta del usuario.
            ruta_salida.unlink(missing_ok=True)
            raise

        self._notificar(callback_progreso, 1.0, f"Video generado: {ruta_salida.name}")
        return ruta_salida

    @staticmethod
    def _calcular_frames_por_segmento(segmentos: list[SegmentoImagen], fps: int) -> list[int]:
        """Frames por segmento usando redondeo acumulado (sin deriva de sincronía)."""
        frames: list[int] = []
        for segmento in segmentos:
            frame_inicio = round(segmento.inicio * fps)
            frame_fin = round(segmento.fin * fps)
            frames.append(max(1, frame_fin - frame_inicio))
        return frames

    # ------------------------------------------------------------------ #
    # Construcción de comandos
    # ------------------------------------------------------------------ #
    def _parametros_codificacion_video(self, crf: int) -> list[str]:
        return ["-c:v", "libx264", "-preset", self.preset_codificacion, "-crf", str(crf), "-pix_fmt", "yuv420p"]

    def _construir_comando_clip(
        self, segmento: SegmentoImagen, cantidad_frames: int, proyecto: ProyectoVideo, ruta_clip: Path
    ) -> list[str]:
        """Comando FFmpeg que convierte una imagen en un clip de ``cantidad_frames`` frames."""
        ancho, alto, fps = proyecto.ancho, proyecto.alto, proyecto.fps
        comando = [self.ruta_ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
        if proyecto.efecto_ken_burns_activado:
            # zoompan genera "d" frames a partir de una única imagen de entrada.
            filtro = self.construir_filtro_ken_burns(
                ancho, alto, cantidad_frames, fps, segmento.indice, self.factor_sobremuestreo_ken_burns
            )
            comando += ["-i", str(segmento.ruta_imagen.resolve())]
        else:
            filtro = self.construir_filtro_estatico(ancho, alto)
            comando += ["-loop", "1", "-framerate", str(fps), "-i", str(segmento.ruta_imagen.resolve())]
        comando += [
            "-vf", filtro,
            "-frames:v", str(cantidad_frames),
            "-r", str(fps),
            "-an",
            *self._parametros_codificacion_video(self.calidad_crf_intermedia),
            "-progress", "pipe:1", "-nostats",
            str(ruta_clip.resolve()),
        ]
        return comando

    def _construir_comando_final(
        self,
        proyecto: ProyectoVideo,
        ruta_lista_clips: Path,
        nombre_archivo_ass: str | None,
        duracion_total: float,
        ruta_salida: Path,
    ) -> list[str]:
        """Comando FFmpeg de ensamblado: concat + subtítulos + mezcla de audio."""
        comando = [
            self.ruta_ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(ruta_lista_clips.resolve()),
            "-i", str(Path(proyecto.ruta_audio_voz).resolve()),
        ]
        if proyecto.tiene_musica_fondo:
            # -stream_loop -1 repite la música indefinidamente; amix la corta con la voz.
            comando += ["-stream_loop", "-1", "-i", str(Path(proyecto.ruta_musica_fondo).resolve())]

        filtros: list[str] = []
        if nombre_archivo_ass:
            filtros.append(f"[0:v]subtitles=filename={nombre_archivo_ass}[video_salida]")
            mapa_video = "[video_salida]"
        else:
            mapa_video = "0:v:0"

        formato_audio = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        if proyecto.tiene_musica_fondo:
            inicio_fundido_salida = max(0.0, duracion_total - 2.0)
            filtros.append(f"[1:a:0]{formato_audio}[voz]")
            filtros.append(
                f"[2:a:0]{formato_audio},volume={proyecto.volumen_musica:.3f},"
                f"afade=t=in:st=0:d=1,afade=t=out:st={inicio_fundido_salida:.3f}:d=2[musica]"
            )
            filtros.append(
                "[voz][musica]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                "alimiter=limit=0.95[audio_salida]"
            )
            mapa_audio = "[audio_salida]"
        else:
            mapa_audio = "1:a:0"

        if filtros:
            comando += ["-filter_complex", ";".join(filtros)]
        comando += ["-map", mapa_video, "-map", mapa_audio]

        if nombre_archivo_ass:
            comando += self._parametros_codificacion_video(self.calidad_crf_final)
        else:
            comando += ["-c:v", "copy"]  # Sin subtítulos no hace falta recodificar.

        comando += [
            "-c:a", "aac", "-b:a", self.bitrate_audio, "-ar", "48000",
            "-t", f"{duracion_total:.3f}",
            "-movflags", "+faststart",
            "-progress", "pipe:1", "-nostats",
            str(ruta_salida.resolve()),
        ]
        return comando

    # ------------------------------------------------------------------ #
    # Ejecución
    # ------------------------------------------------------------------ #
    def _ejecutar_ffmpeg(
        self,
        comando: list[str],
        directorio_trabajo: Path,
        ruta_log: Path,
        callback_segundos: Callable[[float], None] | None,
        evento_cancelacion: threading.Event | None,
    ) -> None:
        """
        Ejecuta FFmpeg leyendo ``-progress pipe:1`` para informar avance.
        La salida de error se guarda en un log temporal para diagnóstico.
        """
        try:
            with open(ruta_log, "w", encoding="utf-8", errors="replace") as archivo_log:
                proceso = subprocess.Popen(
                    comando,
                    stdout=subprocess.PIPE,
                    stderr=archivo_log,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(directorio_trabajo),
                    creationflags=BANDERAS_CREACION_PROCESO,
                )
                assert proceso.stdout is not None
                for linea in proceso.stdout:
                    if evento_cancelacion is not None and evento_cancelacion.is_set():
                        proceso.terminate()
                        proceso.wait(timeout=10)
                        raise RenderizadoCancelado("Renderizado cancelado por el usuario.")
                    clave, _, valor = linea.strip().partition("=")
                    if clave in ("out_time_us", "out_time_ms") and valor.isdigit() and callback_segundos:
                        # Ambas claves vienen en microsegundos (out_time_ms es un nombre histórico).
                        callback_segundos(int(valor) / 1_000_000)
                codigo_salida = proceso.wait()
        except FileNotFoundError as error:
            raise ErrorFFmpeg("No se encontró FFmpeg. Instálalo y agrégalo al PATH.") from error

        if codigo_salida != 0:
            salida_error = ruta_log.read_text(encoding="utf-8", errors="replace") if ruta_log.exists() else ""
            raise ErrorFFmpeg(f"FFmpeg terminó con código {codigo_salida}.", salida_error)

    # ------------------------------------------------------------------ #
    # Auxiliares
    # ------------------------------------------------------------------ #
    @staticmethod
    def _notificar(callback_progreso: CallbackProgreso, fraccion: float, mensaje: str) -> None:
        if callback_progreso is not None:
            callback_progreso(max(0.0, min(1.0, fraccion)), mensaje)

    @staticmethod
    def _verificar_cancelacion(evento_cancelacion: threading.Event | None) -> None:
        if evento_cancelacion is not None and evento_cancelacion.is_set():
            raise RenderizadoCancelado("Renderizado cancelado por el usuario.")
