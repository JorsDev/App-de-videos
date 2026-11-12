"""
Generador de subtítulos dinámicos en formato Advanced SubStation Alpha (.ass).

A partir del guion alineado (palabra por palabra) crea un archivo .ass
estilizado para quemarlo con el filtro ``subtitles`` de FFmpeg (libass):

    * Agrupa las palabras en frases cortas y legibles (pocas palabras por
      pantalla en formatos verticales, más en horizontales).
    * Resalta la palabra que se está pronunciando (estilo TikTok/Reels).
    * Escala tipografía, borde y márgenes según la resolución del video.
    * Usa SIEMPRE el texto exacto del guion, no el reconocido por Whisper.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from modelo.alineador_audio import BloqueAlineado, PalabraAlineada

# Signos que indican un buen punto para cortar un grupo de subtítulo.
SIGNOS_FIN_DE_FRASE = (".", "!", "?", "…", ";", ":", ",")
# Pausa (segundos) entre palabras a partir de la cual se fuerza un nuevo grupo.
PAUSA_MAXIMA_ENTRE_PALABRAS = 0.6
# Tiempo extra que un subtítulo permanece tras la última palabra (si no choca con el siguiente).
PERMANENCIA_EXTRA = 0.25


@dataclass
class EstiloSubtitulos:
    """Parámetros visuales configurables de los subtítulos."""

    fuente: str = "Arial"
    proporcion_tamano: float = 0.065  # Tamaño de letra relativo al lado menor del video
    color_texto: str = "#FFFFFF"
    color_resaltado: str = "#FFD400"
    color_borde: str = "#000000"
    color_sombra: str = "#000000"
    opacidad_sombra: float = 0.5  # 0 = opaca, 1 = transparente
    negrita: bool = True
    mayusculas: bool = False
    resaltar_palabra_activa: bool = True
    escala_palabra_activa: int = 110  # % de tamaño de la palabra resaltada
    max_palabras_por_grupo: int | None = None  # None = automático según formato
    proporcion_margen_inferior: float | None = None  # None = automático según formato


def convertir_color_hex_a_ass(color_hex: str, transparencia: float = 0.0) -> str:
    """
    Convierte '#RRGGBB' al formato de color ASS '&HAABBGGRR'.

    Args:
        transparencia: 0.0 (opaco) a 1.0 (totalmente transparente).
    """
    color = color_hex.lstrip("#")
    if len(color) != 6:
        raise ValueError(f"Color hexadecimal inválido: {color_hex!r}")
    rojo, verde, azul = color[0:2], color[2:4], color[4:6]
    alfa = int(round(max(0.0, min(1.0, transparencia)) * 255))
    return f"&H{alfa:02X}{azul}{verde}{rojo}".upper()


def formatear_tiempo_ass(segundos: float) -> str:
    """Convierte segundos al formato de tiempo ASS 'H:MM:SS.cc'."""
    centesimas_totales = int(round(max(0.0, segundos) * 100))
    horas, resto = divmod(centesimas_totales, 360000)
    minutos, resto = divmod(resto, 6000)
    segundos_enteros, centesimas = divmod(resto, 100)
    return f"{horas}:{minutos:02d}:{segundos_enteros:02d}.{centesimas:02d}"


def escapar_texto_ass(texto: str) -> str:
    """Neutraliza caracteres con significado especial en ASS."""
    return texto.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


class GeneradorSubtitulos:
    """Construye archivos .ass dinámicos a partir del guion alineado."""

    NOMBRE_ESTILO = "Principal"

    def __init__(self, ancho_video: int, alto_video: int, estilo: EstiloSubtitulos | None = None) -> None:
        self.ancho_video = ancho_video
        self.alto_video = alto_video
        self.estilo = estilo or EstiloSubtitulos()

    # ------------------------------------------------------------------ #
    # Métricas derivadas de la resolución
    # ------------------------------------------------------------------ #
    @property
    def es_vertical(self) -> bool:
        return self.alto_video > self.ancho_video

    @property
    def tamano_fuente(self) -> int:
        return max(16, int(min(self.ancho_video, self.alto_video) * self.estilo.proporcion_tamano))

    @property
    def grosor_borde(self) -> float:
        return round(max(2.0, self.tamano_fuente * 0.07), 1)

    @property
    def distancia_sombra(self) -> float:
        return round(max(1.0, self.tamano_fuente * 0.04), 1)

    @property
    def margen_vertical(self) -> int:
        proporcion = self.estilo.proporcion_margen_inferior
        if proporcion is None:
            # En vertical se sube el texto para no quedar bajo la interfaz de TikTok/Reels.
            proporcion = 0.22 if self.es_vertical else 0.08
        return int(self.alto_video * proporcion)

    @property
    def margen_lateral(self) -> int:
        return int(self.ancho_video * 0.08)

    @property
    def max_palabras_por_grupo(self) -> int:
        if self.estilo.max_palabras_por_grupo:
            return self.estilo.max_palabras_por_grupo
        if self.es_vertical:
            return 4
        if self.ancho_video == self.alto_video:
            return 5
        return 7

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def generar_archivo_ass(
        self,
        bloques_alineados: list[BloqueAlineado],
        ruta_salida: str | Path,
        duracion_total: float | None = None,
    ) -> Path:
        """
        Genera el archivo .ass y devuelve su ruta.

        Args:
            bloques_alineados: Resultado de ``AlineadorAudio.alinear_guion_con_audio``.
            ruta_salida: Ruta del archivo .ass a crear.
            duracion_total: Duración del audio (limita el último subtítulo).
        """
        ruta = Path(ruta_salida)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        contenido = self.construir_contenido_ass(bloques_alineados, duracion_total)
        ruta.write_text(contenido, encoding="utf-8")
        return ruta

    def construir_contenido_ass(
        self, bloques_alineados: list[BloqueAlineado], duracion_total: float | None = None
    ) -> str:
        """Devuelve el contenido completo del .ass como texto."""
        grupos = self.agrupar_palabras(bloques_alineados)
        eventos = self._construir_eventos(grupos, duracion_total)
        return self._construir_cabecera() + "\n".join(eventos) + "\n"

    def agrupar_palabras(self, bloques_alineados: list[BloqueAlineado]) -> list[list[PalabraAlineada]]:
        """
        Agrupa las palabras en "pantallas" de subtítulo. Un grupo nunca
        cruza el límite entre bloques del guion y se corta en signos de
        puntuación, pausas largas o al alcanzar el máximo de palabras.
        """
        grupos: list[list[PalabraAlineada]] = []
        maximo = self.max_palabras_por_grupo
        for bloque in bloques_alineados:
            grupo_actual: list[PalabraAlineada] = []
            for palabra in bloque.palabras:
                if grupo_actual:
                    pausa = palabra.inicio - grupo_actual[-1].fin
                    if len(grupo_actual) >= maximo or pausa > PAUSA_MAXIMA_ENTRE_PALABRAS:
                        grupos.append(grupo_actual)
                        grupo_actual = []
                grupo_actual.append(palabra)
                # Cortar tras puntuación si el grupo ya tiene un tamaño razonable.
                if palabra.texto.endswith(SIGNOS_FIN_DE_FRASE) and len(grupo_actual) >= max(2, maximo // 2):
                    grupos.append(grupo_actual)
                    grupo_actual = []
                elif palabra.texto.endswith((".", "!", "?", "…")):
                    grupos.append(grupo_actual)
                    grupo_actual = []
            if grupo_actual:
                grupos.append(grupo_actual)
        return grupos

    # ------------------------------------------------------------------ #
    # Construcción interna
    # ------------------------------------------------------------------ #
    def _construir_cabecera(self) -> str:
        estilo = self.estilo
        color_texto = convertir_color_hex_a_ass(estilo.color_texto)
        color_resaltado = convertir_color_hex_a_ass(estilo.color_resaltado)
        color_borde = convertir_color_hex_a_ass(estilo.color_borde)
        color_sombra = convertir_color_hex_a_ass(estilo.color_sombra, estilo.opacidad_sombra)
        negrita = -1 if estilo.negrita else 0
        return (
            "[Script Info]\n"
            "; Generado automáticamente por Generador de Videos\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {self.ancho_video}\n"
            f"PlayResY: {self.alto_video}\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n"
            "YCbCr Matrix: TV.709\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: {self.NOMBRE_ESTILO},{estilo.fuente},{self.tamano_fuente},{color_texto},"
            f"{color_resaltado},{color_borde},{color_sombra},{negrita},0,0,0,100,100,0,0,1,"
            f"{self.grosor_borde},{self.distancia_sombra},2,{self.margen_lateral},"
            f"{self.margen_lateral},{self.margen_vertical},1\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

    def _formatear_palabra(self, texto: str) -> str:
        texto = escapar_texto_ass(texto)
        return texto.upper() if self.estilo.mayusculas else texto

    def _linea_dialogo(self, inicio: float, fin: float, texto: str) -> str:
        return (
            f"Dialogue: 0,{formatear_tiempo_ass(inicio)},{formatear_tiempo_ass(fin)},"
            f"{self.NOMBRE_ESTILO},,0,0,0,,{texto}"
        )

    def _construir_eventos(
        self, grupos: list[list[PalabraAlineada]], duracion_total: float | None
    ) -> list[str]:
        eventos: list[str] = []
        color_resaltado = convertir_color_hex_a_ass(self.estilo.color_resaltado)
        escala = self.estilo.escala_palabra_activa

        for indice_grupo, grupo in enumerate(grupos):
            inicio_grupo = grupo[0].inicio
            fin_grupo = grupo[-1].fin + PERMANENCIA_EXTRA
            if indice_grupo + 1 < len(grupos):
                fin_grupo = min(fin_grupo, grupos[indice_grupo + 1][0].inicio)
            if duracion_total is not None:
                fin_grupo = min(fin_grupo, duracion_total)
            fin_grupo = max(fin_grupo, grupo[-1].fin)
            if fin_grupo - inicio_grupo < 0.01:
                continue

            textos = [self._formatear_palabra(palabra.texto) for palabra in grupo]

            if not self.estilo.resaltar_palabra_activa:
                eventos.append(self._linea_dialogo(inicio_grupo, fin_grupo, r"{\fad(80,40)}" + " ".join(textos)))
                continue

            # Un evento por palabra: el grupo completo visible y la palabra activa resaltada.
            for indice_palabra, palabra in enumerate(grupo):
                inicio_evento = inicio_grupo if indice_palabra == 0 else palabra.inicio
                fin_evento = grupo[indice_palabra + 1].inicio if indice_palabra + 1 < len(grupo) else fin_grupo
                fin_evento = min(fin_evento, fin_grupo)
                if round(fin_evento, 2) <= round(inicio_evento, 2):
                    continue
                piezas = []
                for posicion, texto in enumerate(textos):
                    if posicion == indice_palabra:
                        piezas.append(
                            rf"{{\c{color_resaltado}&\fscx{escala}\fscy{escala}}}{texto}{{\r}}"
                        )
                    else:
                        piezas.append(texto)
                prefijo = r"{\fad(60,0)}" if indice_palabra == 0 else ""
                eventos.append(self._linea_dialogo(inicio_evento, fin_evento, prefijo + " ".join(piezas)))
        return eventos
