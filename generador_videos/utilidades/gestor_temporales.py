"""
Gestor de archivos temporales.

Crea una carpeta de trabajo aislada por cada renderizado (clips intermedios,
subtítulos .ass, listas de concatenación, logs de FFmpeg) y garantiza su
eliminación al terminar, incluso si ocurre un error.

Uso recomendado como gestor de contexto::

    with GestorTemporales() as gestor:
        ruta_ass = gestor.crear_ruta_temporal("subtitulos.ass")
        ...
    # Aquí la carpeta temporal ya fue eliminada.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

PREFIJO_CARPETA_TEMPORAL = "generador_videos_"


class GestorTemporales:
    """Administra el ciclo de vida de una carpeta temporal de trabajo."""

    def __init__(self, directorio_base: str | Path | None = None) -> None:
        """
        Args:
            directorio_base: Carpeta donde crear el directorio temporal.
                Si es ``None`` se usa la carpeta temporal del sistema.
        """
        self._directorio_base = Path(directorio_base) if directorio_base else None
        self._directorio_trabajo: Path | None = None

    # ------------------------------------------------------------------ #
    # Gestión del directorio
    # ------------------------------------------------------------------ #
    def crear_directorio_trabajo(self) -> Path:
        """Crea (si no existe) y devuelve la carpeta temporal de trabajo."""
        if self._directorio_trabajo is None or not self._directorio_trabajo.exists():
            if self._directorio_base is not None:
                self._directorio_base.mkdir(parents=True, exist_ok=True)
            self._directorio_trabajo = Path(
                tempfile.mkdtemp(
                    prefix=PREFIJO_CARPETA_TEMPORAL,
                    dir=str(self._directorio_base) if self._directorio_base else None,
                )
            )
        return self._directorio_trabajo

    @property
    def directorio_trabajo(self) -> Path:
        """Carpeta temporal activa (se crea bajo demanda)."""
        return self.crear_directorio_trabajo()

    def crear_subdirectorio(self, nombre: str) -> Path:
        """Crea una subcarpeta dentro del directorio de trabajo."""
        ruta = self.directorio_trabajo / nombre
        ruta.mkdir(parents=True, exist_ok=True)
        return ruta

    def crear_ruta_temporal(self, nombre_archivo: str) -> Path:
        """Devuelve una ruta (sin crear el archivo) dentro del directorio de trabajo."""
        return self.directorio_trabajo / nombre_archivo

    def limpiar(self) -> None:
        """Elimina la carpeta temporal y todo su contenido."""
        if self._directorio_trabajo is not None and self._directorio_trabajo.exists():
            shutil.rmtree(self._directorio_trabajo, ignore_errors=True)
        self._directorio_trabajo = None

    # ------------------------------------------------------------------ #
    # Mantenimiento
    # ------------------------------------------------------------------ #
    @staticmethod
    def limpiar_residuos_antiguos(horas_antiguedad: float = 24.0) -> int:
        """
        Elimina carpetas temporales huérfanas de ejecuciones anteriores
        (por ejemplo, si la app se cerró de forma abrupta).

        Returns:
            Cantidad de carpetas eliminadas.
        """
        limite = time.time() - horas_antiguedad * 3600
        eliminadas = 0
        for carpeta in Path(tempfile.gettempdir()).glob(f"{PREFIJO_CARPETA_TEMPORAL}*"):
            try:
                if carpeta.is_dir() and carpeta.stat().st_mtime < limite:
                    shutil.rmtree(carpeta, ignore_errors=True)
                    eliminadas += 1
            except OSError:
                continue
        return eliminadas

    # ------------------------------------------------------------------ #
    # Protocolo de gestor de contexto
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "GestorTemporales":
        self.crear_directorio_trabajo()
        return self

    def __exit__(self, tipo_excepcion, valor_excepcion, traza) -> None:
        self.limpiar()
