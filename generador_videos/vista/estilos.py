"""
Constantes de diseño de la interfaz.

Colores, tipografías, dimensiones, formatos de video disponibles y opciones
de configuración que la Vista muestra al usuario. Este módulo es puramente
declarativo: no importa ni el Modelo ni customtkinter.
"""

from __future__ import annotations

# ---------------------------------------------------------------------- #
# Apariencia general
# ---------------------------------------------------------------------- #
MODO_APARIENCIA = "dark"
TEMA_COLOR = "blue"

TITULO_APLICACION = "Generador de Videos Automático"
TAMANO_VENTANA_INICIAL = "1400x860"
TAMANO_VENTANA_MINIMO = (1180, 740)

COLORES = {
    "fondo": "#14141C",
    "panel": "#1E1E2A",
    "panel_secundario": "#272736",
    "borde": "#33334A",
    "acento": "#7C5CFF",
    "acento_hover": "#6A4BE8",
    "exito": "#2ECC71",
    "exito_hover": "#27AE60",
    "peligro": "#E74C3C",
    "peligro_hover": "#C0392B",
    "advertencia": "#F1C40F",
    "texto": "#ECECF1",
    "texto_secundario": "#9A9AB0",
    "fila_seleccionada": "#3A3360",
    "fila_normal": "#272736",
}

FUENTE_BASE = "Segoe UI"
FUENTES = {
    "titulo": (FUENTE_BASE, 22, "bold"),
    "subtitulo": (FUENTE_BASE, 15, "bold"),
    "normal": (FUENTE_BASE, 13),
    "negrita": (FUENTE_BASE, 13, "bold"),
    "pequena": (FUENTE_BASE, 11),
    "editor": ("Consolas", 13),
}

RADIO_ESQUINAS = 10
ESPACIADO = 10
ESPACIADO_INTERNO = 8

# ---------------------------------------------------------------------- #
# Formatos de exportación (las etiquetas coinciden con el Modelo)
# ---------------------------------------------------------------------- #
FORMATOS_VIDEO: list[dict] = [
    {
        "etiqueta": "9:16 Vertical (1080×1920)",
        "clave": "9:16 Vertical",
        "ancho": 1080,
        "alto": 1920,
        "plataformas": "TikTok, Reels, YouTube Shorts (Full HD Vertical)",
    },
    {
        "etiqueta": "16:9 Horizontal (1920×1080 Full HD)",
        "clave": "16:9 Horizontal",
        "ancho": 1920,
        "alto": 1080,
        "plataformas": "YouTube estándar — Full HD 1080p",
    },
    {
        "etiqueta": "1:1 Cuadrado (1080×1080)",
        "clave": "1:1 Cuadrado",
        "ancho": 1080,
        "alto": 1080,
        "plataformas": "Instagram/Facebook Post",
    },
    {
        "etiqueta": "4:5 Vertical Feed (1080×1350)",
        "clave": "4:5 Vertical Feed",
        "ancho": 1080,
        "alto": 1350,
        "plataformas": "Instagram Feed",
    },
]
ETIQUETAS_FORMATOS = [formato["etiqueta"] for formato in FORMATOS_VIDEO]
FORMATO_POR_DEFECTO = ETIQUETAS_FORMATOS[0]


def obtener_formato_por_etiqueta(etiqueta: str) -> dict:
    """Devuelve el diccionario del formato con esa etiqueta o clave (o el primero)."""
    etiqueta_limpia = etiqueta.strip()
    for formato in FORMATOS_VIDEO:
        clave = formato.get("clave", "")
        if etiqueta_limpia in (formato["etiqueta"], clave) or (clave and etiqueta_limpia.startswith(clave)):
            return formato
    return FORMATOS_VIDEO[0]


# ---------------------------------------------------------------------- #
# Opciones de IA (Whisper)
# ---------------------------------------------------------------------- #
MODELOS_WHISPER = ["tiny", "base", "small", "medium", "large-v3"]
MODELO_WHISPER_POR_DEFECTO = "small"
DESCRIPCION_MODELOS_WHISPER = {
    "tiny": "Muy rápido, menor precisión",
    "base": "Rápido",
    "small": "Equilibrado (recomendado)",
    "medium": "Preciso, más lento",
    "large-v3": "Máxima precisión (ideal con GPU)",
}

IDIOMAS_DISPONIBLES: dict[str, str | None] = {
    "Detección automática": None,
    "Español": "es",
    "Inglés": "en",
    "Portugués": "pt",
    "Francés": "fr",
    "Italiano": "it",
    "Alemán": "de",
}
IDIOMA_POR_DEFECTO = "Español"

# ---------------------------------------------------------------------- #
# Audio
# ---------------------------------------------------------------------- #
VOLUMEN_MUSICA_POR_DEFECTO_PORCENTAJE = 18
VOLUMEN_MUSICA_MAXIMO_PORCENTAJE = 100

# ---------------------------------------------------------------------- #
# Imágenes
# ---------------------------------------------------------------------- #
TAMANO_MINIATURA = (64, 64)
TAMANO_MAXIMO_PREVISUALIZACION = (260, 260)

# ---------------------------------------------------------------------- #
# Filtros de los diálogos de archivo
# ---------------------------------------------------------------------- #
TIPOS_ARCHIVO_AUDIO = [("Archivos de audio", "*.mp3 *.wav *.m4a"), ("Todos los archivos", "*.*")]
TIPOS_ARCHIVO_IMAGEN = [("Imágenes", "*.jpg *.jpeg *.png *.webp"), ("Todos los archivos", "*.*")]
TIPOS_ARCHIVO_GUION = [("Texto plano", "*.txt")]

# ---------------------------------------------------------------------- #
# Textos de estado
# ---------------------------------------------------------------------- #
TEXTO_SIN_ARCHIVO = "Ningún archivo seleccionado"
TEXTO_SIN_MUSICA = "Sin música (solo voz)"
TEXTO_ESTADO_INICIAL = "Listo. Completa las entradas y pulsa «Generar video»."
