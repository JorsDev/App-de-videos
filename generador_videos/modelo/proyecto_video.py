"""
Entidad principal del dominio: ``ProyectoVideo``.

Actúa como DTO (objeto de transferencia de datos) entre la Vista, el
Controlador y el resto del Modelo. Contiene todas las entradas del usuario
y las reglas de validación que deben cumplirse antes de renderizar.

Este módulo NO depende de ninguna librería gráfica ni de FFmpeg/Whisper.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

# ---------------------------------------------------------------------- #
# Constantes del dominio
# ---------------------------------------------------------------------- #
EXTENSIONES_AUDIO_PERMITIDAS: tuple[str, ...] = (".mp3", ".wav", ".m4a")
EXTENSIONES_IMAGEN_PERMITIDAS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")
EXTENSIONES_GUION_PERMITIDAS: tuple[str, ...] = (".txt",)

VOLUMEN_MUSICA_POR_DEFECTO: float = 0.18  # 18 % (rango sugerido 15 % - 20 %)
FPS_POR_DEFECTO: int = 30

# Codificaciones probadas, en orden, al leer guiones .txt.
CODIFICACIONES_GUION: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


class FormatoVideo(Enum):
    """Formatos/plataformas de exportación soportados."""

    VERTICAL_9_16 = ("9:16 Vertical", 1080, 1920, "TikTok, Reels, YouTube Shorts")
    HORIZONTAL_16_9 = ("16:9 Horizontal", 1920, 1080, "YouTube estándar (1920×1080 Full HD)")
    CUADRADO_1_1 = ("1:1 Cuadrado", 1080, 1080, "Instagram/Facebook Post")
    VERTICAL_FEED_4_5 = ("4:5 Vertical Feed", 1080, 1350, "Instagram Feed")

    def __init__(self, etiqueta: str, ancho: int, alto: int, plataformas: str) -> None:
        self.etiqueta = etiqueta
        self.ancho = ancho
        self.alto = alto
        self.plataformas = plataformas

    @property
    def resolucion(self) -> tuple[int, int]:
        """Tupla (ancho, alto) en píxeles."""
        return self.ancho, self.alto

    @property
    def es_vertical(self) -> bool:
        """True si el video es más alto que ancho."""
        return self.alto > self.ancho

    @property
    def descripcion_completa(self) -> str:
        """Texto descriptivo, ej: '9:16 Vertical (1080x1920) — TikTok, Reels...'."""
        return f"{self.etiqueta} ({self.ancho}x{self.alto}) — {self.plataformas}"

    @classmethod
    def desde_etiqueta(cls, texto: str) -> "FormatoVideo":
        """Obtiene el formato a partir de su etiqueta o descripción completa."""
        texto_limpio = texto.strip()
        for formato in cls:
            if (
                texto_limpio in (formato.etiqueta, formato.descripcion_completa, formato.name)
                or texto_limpio.startswith(formato.etiqueta)
            ):
                return formato
        raise ValueError(f"Formato de video desconocido: {texto!r}")


class ErrorValidacionProyecto(Exception):
    """Se lanza cuando el proyecto no cumple los requisitos para renderizar."""

    def __init__(self, errores: list[str]) -> None:
        self.errores = errores
        super().__init__("El proyecto tiene errores:\n- " + "\n- ".join(errores))


def clave_orden_natural(ruta: Path | str) -> list:
    """Clave de ordenamiento 'natural' (img2 < img10)."""
    nombre = Path(ruta).name.lower()
    return [int(parte) if parte.isdigit() else parte for parte in re.split(r"(\d+)", nombre)]


# ---------------------------------------------------------------------- #
# Entidad principal
# ---------------------------------------------------------------------- #
@dataclass
class ProyectoVideo:
    """Datos completos de un proyecto de video y sus validaciones."""

    # --- Entradas obligatorias ---
    ruta_audio_voz: Path | None = None
    texto_guion: str = ""
    rutas_imagenes: list[Path] = field(default_factory=list)

    # --- Audio secundario opcional ---
    ruta_musica_fondo: Path | None = None
    volumen_musica: float = VOLUMEN_MUSICA_POR_DEFECTO

    # --- Opciones de exportación ---
    subtitulos_activados: bool = True
    efecto_ken_burns_activado: bool = True
    formato_video: FormatoVideo = FormatoVideo.VERTICAL_9_16
    carpeta_salida: Path | None = None
    nombre_archivo_salida: str = ""
    fps: int = FPS_POR_DEFECTO

    def __post_init__(self) -> None:
        # Normaliza cualquier str recibido a Path para trabajar de forma uniforme.
        self.ruta_audio_voz = Path(self.ruta_audio_voz) if self.ruta_audio_voz else None
        self.ruta_musica_fondo = Path(self.ruta_musica_fondo) if self.ruta_musica_fondo else None
        self.carpeta_salida = Path(self.carpeta_salida) if self.carpeta_salida else None
        self.rutas_imagenes = [Path(ruta) for ruta in self.rutas_imagenes]

    # ------------------------------------------------------------------ #
    # Propiedades de conveniencia
    # ------------------------------------------------------------------ #
    @property
    def tiene_musica_fondo(self) -> bool:
        """True si el usuario seleccionó música de fondo."""
        return self.ruta_musica_fondo is not None

    @property
    def ancho(self) -> int:
        return self.formato_video.ancho

    @property
    def alto(self) -> int:
        return self.formato_video.alto

    # ------------------------------------------------------------------ #
    # Gestión de imágenes
    # ------------------------------------------------------------------ #
    def agregar_imagenes(self, rutas: list[str | Path]) -> int:
        """Agrega imágenes válidas (sin duplicados). Devuelve cuántas se agregaron."""
        agregadas = 0
        existentes = {ruta.resolve() for ruta in self.rutas_imagenes}
        for ruta in map(Path, rutas):
            if ruta.suffix.lower() in EXTENSIONES_IMAGEN_PERMITIDAS and ruta.resolve() not in existentes:
                self.rutas_imagenes.append(ruta)
                existentes.add(ruta.resolve())
                agregadas += 1
        return agregadas

    def agregar_imagenes_de_carpeta(self, carpeta: str | Path) -> int:
        """Agrega todas las imágenes de una carpeta en orden natural."""
        return self.agregar_imagenes(self.listar_imagenes_de_carpeta(carpeta))

    def mover_imagen(self, indice: int, desplazamiento: int) -> int:
        """
        Mueve una imagen dentro de la lista (desplazamiento -1 = subir, +1 = bajar).

        Returns:
            El nuevo índice de la imagen.
        """
        if not 0 <= indice < len(self.rutas_imagenes):
            raise IndexError(f"Índice de imagen fuera de rango: {indice}")
        nuevo_indice = max(0, min(len(self.rutas_imagenes) - 1, indice + desplazamiento))
        imagen = self.rutas_imagenes.pop(indice)
        self.rutas_imagenes.insert(nuevo_indice, imagen)
        return nuevo_indice

    def quitar_imagen(self, indice: int) -> None:
        """Elimina una imagen de la lista por su índice."""
        del self.rutas_imagenes[indice]

    def quitar_audio_voz(self) -> None:
        """Limpia la selección del audio principal de voz."""
        self.ruta_audio_voz = None

    def quitar_musica_fondo(self) -> None:
        """Limpia la selección de música de fondo (renderizará solo con la voz)."""
        self.ruta_musica_fondo = None

    # ------------------------------------------------------------------ #
    # Guion
    # ------------------------------------------------------------------ #
    def dividir_guion_en_bloques(self) -> list[str]:
        """
        Divide el guion en bloques (frases/párrafos) que servirán para
        sincronizar imágenes y subtítulos.

        Estrategia:
            1. Párrafos separados por líneas en blanco.
            2. Si solo hay un párrafo: cada línea no vacía es un bloque.
            3. Si sigue siendo uno solo: se divide por oraciones (. ! ? …).
        """
        texto = self.texto_guion.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not texto:
            return []

        def limpiar(fragmentos: list[str]) -> list[str]:
            return [" ".join(fragmento.split()) for fragmento in fragmentos if fragmento.strip()]

        bloques = limpiar(re.split(r"\n\s*\n", texto))
        if len(bloques) <= 1:
            bloques = limpiar(texto.split("\n"))
        if len(bloques) <= 1:
            bloques = limpiar(re.split(r"(?<=[.!?…])\s+", texto))
        return bloques

    @staticmethod
    def cargar_guion_desde_archivo(ruta_archivo: str | Path) -> str:
        """Lee un guion .txt probando varias codificaciones comunes."""
        ruta = Path(ruta_archivo)
        if ruta.suffix.lower() not in EXTENSIONES_GUION_PERMITIDAS:
            raise ValueError(f"El guion debe ser un archivo .txt: {ruta.name}")
        datos = ruta.read_bytes()
        for codificacion in CODIFICACIONES_GUION:
            try:
                return datos.decode(codificacion)
            except UnicodeDecodeError:
                continue
        return datos.decode("utf-8", errors="replace")

    @staticmethod
    def listar_imagenes_de_carpeta(carpeta: str | Path) -> list[Path]:
        """Devuelve las imágenes permitidas de una carpeta, en orden natural."""
        ruta_carpeta = Path(carpeta)
        if not ruta_carpeta.is_dir():
            raise NotADirectoryError(f"No es una carpeta válida: {ruta_carpeta}")
        imagenes = [
            ruta
            for ruta in ruta_carpeta.iterdir()
            if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES_IMAGEN_PERMITIDAS
        ]
        return sorted(imagenes, key=clave_orden_natural)

    # ------------------------------------------------------------------ #
    # Salida
    # ------------------------------------------------------------------ #
    def obtener_ruta_salida(self) -> Path:
        """
        Calcula la ruta final del .mp4 sin sobrescribir archivos existentes
        (agrega sufijos _1, _2, ... si es necesario).
        """
        if self.carpeta_salida is None:
            raise ValueError("No se ha definido la carpeta de salida.")
        nombre_base = self.nombre_archivo_salida.strip() or datetime.now().strftime(
            "video_%Y%m%d_%H%M%S"
        )
        nombre_base = re.sub(r'[<>:"/\\|?*]', "_", Path(nombre_base).stem)
        ruta_salida = self.carpeta_salida / f"{nombre_base}.mp4"
        contador = 1
        while ruta_salida.exists():
            ruta_salida = self.carpeta_salida / f"{nombre_base}_{contador}.mp4"
            contador += 1
        return ruta_salida

    # ------------------------------------------------------------------ #
    # Validaciones
    # ------------------------------------------------------------------ #
    def validar(self) -> list[str]:
        """Devuelve la lista de errores encontrados (vacía si todo es válido)."""
        errores: list[str] = []

        # Audio de voz (obligatorio)
        errores.extend(self._validar_archivo(self.ruta_audio_voz, "audio de voz", EXTENSIONES_AUDIO_PERMITIDAS, True))

        # Guion (obligatorio)
        if not self.texto_guion.strip():
            errores.append("El guion está vacío.")

        # Imágenes (obligatorias)
        if not self.rutas_imagenes:
            errores.append("Debes seleccionar al menos una imagen.")
        for ruta_imagen in self.rutas_imagenes:
            errores.extend(self._validar_archivo(ruta_imagen, "imagen", EXTENSIONES_IMAGEN_PERMITIDAS, True))

        # Música de fondo (opcional)
        if self.ruta_musica_fondo is not None:
            errores.extend(
                self._validar_archivo(self.ruta_musica_fondo, "música de fondo", EXTENSIONES_AUDIO_PERMITIDAS, True)
            )
        if not 0.0 <= self.volumen_musica <= 1.0:
            errores.append("El volumen de la música debe estar entre 0 % y 100 %.")

        # Exportación
        if self.carpeta_salida is None:
            errores.append("Debes seleccionar la carpeta de destino.")
        elif not self.carpeta_salida.is_dir():
            errores.append(f"La carpeta de destino no existe: {self.carpeta_salida}")
        if not isinstance(self.formato_video, FormatoVideo):
            errores.append("El formato de video no es válido.")
        if not 1 <= int(self.fps) <= 120:
            errores.append("Los FPS deben estar entre 1 y 120.")

        return errores

    def es_valido(self) -> bool:
        """True si el proyecto puede renderizarse."""
        return not self.validar()

    def validar_o_lanzar(self) -> None:
        """Lanza ``ErrorValidacionProyecto`` si existen errores."""
        errores = self.validar()
        if errores:
            raise ErrorValidacionProyecto(errores)

    @staticmethod
    def _validar_archivo(
        ruta: Path | None, descripcion: str, extensiones: tuple[str, ...], obligatorio: bool
    ) -> list[str]:
        """Valida existencia y extensión de un archivo."""
        if ruta is None:
            return [f"Falta seleccionar el {descripcion}."] if obligatorio else []
        if not ruta.is_file():
            return [f"No se encontró el archivo de {descripcion}: {ruta}"]
        if ruta.suffix.lower() not in extensiones:
            return [f"Formato no permitido para {descripcion} ({ruta.name}). Usa: {', '.join(extensiones)}"]
        return []
