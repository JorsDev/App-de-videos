"""
Capa MODELO del Generador de Videos.

Contiene la lógica de negocio y el procesamiento multimedia. Esta capa
NO importa nada de la interfaz gráfica (customtkinter).

Módulos:
    proyecto_video        → Entidad/DTO con datos del proyecto y validaciones.
    alineador_audio       → Alineación forzada voz ↔ guion con faster-whisper.
    generador_subtitulos  → Subtítulos dinámicos .ass a partir del guion alineado.
    motor_ffmpeg          → Línea de tiempo de imágenes y pipeline de FFmpeg.
"""

from modelo.alineador_audio import (
    AlineacionCancelada,
    AlineadorAudio,
    BloqueAlineado,
    ErrorAlineacion,
    PalabraAlineada,
    ResultadoAlineacion,
)
from modelo.generador_subtitulos import EstiloSubtitulos, GeneradorSubtitulos
from modelo.motor_ffmpeg import ErrorFFmpeg, MotorFFmpeg, RenderizadoCancelado, SegmentoImagen
from modelo.proyecto_video import (
    EXTENSIONES_AUDIO_PERMITIDAS,
    EXTENSIONES_GUION_PERMITIDAS,
    EXTENSIONES_IMAGEN_PERMITIDAS,
    VOLUMEN_MUSICA_POR_DEFECTO,
    ErrorValidacionProyecto,
    FormatoVideo,
    ProyectoVideo,
)

__all__ = [
    "AlineacionCancelada",
    "AlineadorAudio",
    "BloqueAlineado",
    "ErrorAlineacion",
    "ErrorFFmpeg",
    "ErrorValidacionProyecto",
    "EstiloSubtitulos",
    "EXTENSIONES_AUDIO_PERMITIDAS",
    "EXTENSIONES_GUION_PERMITIDAS",
    "EXTENSIONES_IMAGEN_PERMITIDAS",
    "FormatoVideo",
    "GeneradorSubtitulos",
    "MotorFFmpeg",
    "PalabraAlineada",
    "ProyectoVideo",
    "RenderizadoCancelado",
    "ResultadoAlineacion",
    "SegmentoImagen",
    "VOLUMEN_MUSICA_POR_DEFECTO",
]
