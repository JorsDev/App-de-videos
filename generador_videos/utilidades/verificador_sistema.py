"""
Verificador del sistema.

Comprueba que el entorno tenga todo lo necesario para generar videos:
    * Ejecutables de FFmpeg y FFprobe accesibles (PATH o variable RUTA_FFMPEG).
    * Soporte del filtro ``subtitles`` (libass) para quemar subtítulos .ass.
    * Disponibilidad de GPU CUDA para acelerar faster-whisper (vía ctranslate2).

No depende de ninguna librería de interfaz gráfica.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# En Windows evita que se abra una consola negra por cada subproceso.
BANDERAS_CREACION_PROCESO: int = (
    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined]
)

# Variable de entorno opcional que apunta a la carpeta donde están ffmpeg/ffprobe.
VARIABLE_ENTORNO_RUTA_FFMPEG = "RUTA_FFMPEG"


@dataclass
class InformacionSistema:
    """Resultado de la verificación del entorno."""

    ruta_ffmpeg: str | None
    ruta_ffprobe: str | None
    version_ffmpeg: str | None
    soporta_subtitulos_ass: bool
    cantidad_gpus_cuda: int
    dispositivo_recomendado: str  # "cuda" o "cpu"
    tipo_computo_recomendado: str  # "float16" (GPU) o "int8" (CPU)
    advertencias: list[str] = field(default_factory=list)

    @property
    def ffmpeg_disponible(self) -> bool:
        """True si existen tanto ffmpeg como ffprobe."""
        return self.ruta_ffmpeg is not None and self.ruta_ffprobe is not None

    @property
    def gpu_cuda_disponible(self) -> bool:
        """True si se detectó al menos una GPU CUDA utilizable."""
        return self.cantidad_gpus_cuda > 0

    @property
    def sistema_listo(self) -> bool:
        """True si el sistema puede renderizar videos (FFmpeg presente)."""
        return self.ffmpeg_disponible

    def resumen(self) -> str:
        """Devuelve un texto legible con el estado del sistema."""
        lineas = [
            f"FFmpeg: {self.version_ffmpeg or 'NO ENCONTRADO'}",
            f"Ruta FFmpeg: {self.ruta_ffmpeg or '-'}",
            f"Ruta FFprobe: {self.ruta_ffprobe or '-'}",
            f"Subtítulos .ass (libass): {'Sí' if self.soporta_subtitulos_ass else 'No'}",
            f"GPU CUDA: {self.cantidad_gpus_cuda} detectada(s)",
            f"Dispositivo IA: {self.dispositivo_recomendado} ({self.tipo_computo_recomendado})",
        ]
        lineas.extend(f"⚠ {advertencia}" for advertencia in self.advertencias)
        return "\n".join(lineas)


def localizar_ejecutable(nombre_ejecutable: str) -> str | None:
    """
    Busca un ejecutable primero en la carpeta indicada por ``RUTA_FFMPEG``
    y, si no está, en el PATH del sistema.
    """
    carpeta_personalizada = os.environ.get(VARIABLE_ENTORNO_RUTA_FFMPEG)
    if carpeta_personalizada:
        for candidato in (nombre_ejecutable, f"{nombre_ejecutable}.exe"):
            ruta_candidata = Path(carpeta_personalizada) / candidato
            if ruta_candidata.is_file():
                return str(ruta_candidata)
    return shutil.which(nombre_ejecutable)


def obtener_version_ffmpeg(ruta_ffmpeg: str) -> str | None:
    """Ejecuta ``ffmpeg -version`` y extrae la versión de la primera línea."""
    try:
        resultado = subprocess.run(
            [ruta_ffmpeg, "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=BANDERAS_CREACION_PROCESO,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    coincidencia = re.search(r"ffmpeg version (\S+)", resultado.stdout)
    return coincidencia.group(1) if coincidencia else None


def verificar_soporte_subtitulos(ruta_ffmpeg: str) -> bool:
    """Comprueba si FFmpeg fue compilado con el filtro ``subtitles`` (libass)."""
    try:
        resultado = subprocess.run(
            [ruta_ffmpeg, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=BANDERAS_CREACION_PROCESO,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return re.search(r"^\s*\S+\s+subtitles\s", resultado.stdout, re.MULTILINE) is not None


def detectar_gpus_cuda() -> int:
    """
    Devuelve la cantidad de GPUs CUDA visibles para ctranslate2
    (motor de inferencia de faster-whisper). Devuelve 0 si no hay
    GPU o si ctranslate2 no está instalado.
    """
    try:
        import ctranslate2  # Importación diferida: solo se necesita aquí.

        return int(ctranslate2.get_cuda_device_count())
    except Exception:  # noqa: BLE001 - cualquier fallo implica "sin GPU"
        return 0


def verificar_sistema() -> InformacionSistema:
    """Ejecuta todas las comprobaciones y devuelve un ``InformacionSistema``."""
    advertencias: list[str] = []

    ruta_ffmpeg = localizar_ejecutable("ffmpeg")
    ruta_ffprobe = localizar_ejecutable("ffprobe")
    version_ffmpeg = obtener_version_ffmpeg(ruta_ffmpeg) if ruta_ffmpeg else None
    soporta_subtitulos = verificar_soporte_subtitulos(ruta_ffmpeg) if ruta_ffmpeg else False

    if ruta_ffmpeg is None:
        advertencias.append(
            "FFmpeg no está instalado o no está en el PATH (Windows: winget install Gyan.FFmpeg)."
        )
    if ruta_ffprobe is None:
        advertencias.append("FFprobe no está instalado o no está en el PATH.")
    if ruta_ffmpeg and not soporta_subtitulos:
        advertencias.append(
            "Tu FFmpeg no incluye libass: no se podrán quemar subtítulos en el video."
        )

    cantidad_gpus = detectar_gpus_cuda()
    if cantidad_gpus > 0:
        dispositivo, tipo_computo = "cuda", "float16"
    else:
        dispositivo, tipo_computo = "cpu", "int8"
        advertencias.append("No se detectó GPU CUDA: la alineación con Whisper usará la CPU.")

    return InformacionSistema(
        ruta_ffmpeg=ruta_ffmpeg,
        ruta_ffprobe=ruta_ffprobe,
        version_ffmpeg=version_ffmpeg,
        soporta_subtitulos_ass=soporta_subtitulos,
        cantidad_gpus_cuda=cantidad_gpus,
        dispositivo_recomendado=dispositivo,
        tipo_computo_recomendado=tipo_computo,
        advertencias=advertencias,
    )


if __name__ == "__main__":
    print(verificar_sistema().resumen())
