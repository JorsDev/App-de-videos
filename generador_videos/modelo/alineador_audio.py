"""
Alineación forzada entre el audio de voz y el guion escrito.

Pipeline:
    1. ``faster-whisper`` transcribe el audio en local con marcas de tiempo
       por palabra (GPU CUDA si está disponible, si no CPU int8).
    2. Se normalizan las palabras del guion y de la transcripción
       (minúsculas, sin tildes ni puntuación).
    3. ``difflib.SequenceMatcher`` empareja ambas secuencias. Las palabras
       del guion que coinciden heredan los tiempos exactos de Whisper.
    4. Las palabras sin coincidencia (números escritos distinto, errores de
       reconocimiento, etc.) se interpolan proporcionalmente a su longitud
       entre los vecinos con tiempo conocido.
    5. Se reagrupan por bloques del guion → inicio/fin de cada frase/párrafo.

El resultado conserva SIEMPRE el texto exacto del guion (no el de Whisper),
que es lo que luego se usa para los subtítulos.
"""

from __future__ import annotations

import difflib
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Firma del callback de progreso: (fraccion 0..1, mensaje descriptivo)
CallbackProgreso = Optional[Callable[[float, str], None]]

# Marcador imposible de emparejar para "palabras" sin letras ni números (ej: "—").
_MARCADOR_SIN_CONTENIDO = "\x00"


class ErrorAlineacion(Exception):
    """Error durante la carga del modelo o la alineación."""


class AlineacionCancelada(Exception):
    """El usuario canceló el proceso de alineación."""


# ---------------------------------------------------------------------- #
# Estructuras de datos del resultado
# ---------------------------------------------------------------------- #
@dataclass
class PalabraAlineada:
    """Palabra del guion con su intervalo temporal en el audio (segundos)."""

    texto: str
    inicio: float
    fin: float
    coincidencia_exacta: bool = True  # False si el tiempo fue interpolado/aproximado

    @property
    def duracion(self) -> float:
        return max(0.0, self.fin - self.inicio)


@dataclass
class BloqueAlineado:
    """Bloque (frase/párrafo) del guion con sus tiempos de inicio y fin."""

    indice: int
    texto: str
    inicio: float
    fin: float
    palabras: list[PalabraAlineada] = field(default_factory=list)

    @property
    def duracion(self) -> float:
        return max(0.0, self.fin - self.inicio)


@dataclass
class ResultadoAlineacion:
    """Resultado completo de la alineación audio-guion."""

    bloques: list[BloqueAlineado]
    duracion_audio: float
    idioma_detectado: str | None = None
    porcentaje_coincidencia: float = 0.0  # 0..100 palabras emparejadas exactamente

    @property
    def todas_las_palabras(self) -> list[PalabraAlineada]:
        return [palabra for bloque in self.bloques for palabra in bloque.palabras]


@dataclass
class _PalabraTranscrita:
    """Palabra reconocida por Whisper (uso interno)."""

    texto_normalizado: str
    inicio: float
    fin: float


@dataclass
class _TokenGuion:
    """Palabra del guion preparada para el emparejamiento (uso interno)."""

    texto_original: str
    texto_normalizado: str
    indice_bloque: int


# ---------------------------------------------------------------------- #
# Alineador
# ---------------------------------------------------------------------- #
class AlineadorAudio:
    """Alinea un guion escrito con el audio de voz usando faster-whisper."""

    def __init__(
        self,
        nombre_modelo: str = "small",
        dispositivo: str = "auto",
        tipo_computo: str = "auto",
        idioma: str | None = None,
        directorio_modelos: str | Path | None = None,
        usar_guion_como_contexto: bool = True,
    ) -> None:
        """
        Args:
            nombre_modelo: Modelo de Whisper ("tiny", "base", "small", "medium",
                "large-v3"...). "small" ofrece buen equilibrio velocidad/precisión.
            dispositivo: "auto", "cuda" o "cpu".
            tipo_computo: "auto", "float16", "int8_float16", "int8"...
            idioma: Código ISO ("es", "en"...). ``None`` = detección automática.
            directorio_modelos: Carpeta de caché de modelos descargados.
            usar_guion_como_contexto: Pasa el inicio del guion como
                ``initial_prompt`` para mejorar vocabulario y puntuación.
        """
        self.nombre_modelo = nombre_modelo
        self.dispositivo_solicitado = dispositivo
        self.tipo_computo_solicitado = tipo_computo
        self.idioma = idioma
        self.directorio_modelos = str(directorio_modelos) if directorio_modelos else None
        self.usar_guion_como_contexto = usar_guion_como_contexto

        self._modelo = None
        self.dispositivo_en_uso: str | None = None
        self.tipo_computo_en_uso: str | None = None

    # ------------------------------------------------------------------ #
    # Gestión del modelo
    # ------------------------------------------------------------------ #
    @staticmethod
    def detectar_dispositivo_optimo() -> tuple[str, str]:
        """Devuelve (dispositivo, tipo_computo) óptimos según el hardware."""
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda", "float16"
        except Exception:  # noqa: BLE001
            pass
        return "cpu", "int8"

    def _resolver_configuracion(self) -> tuple[str, str]:
        dispositivo_optimo, computo_optimo = self.detectar_dispositivo_optimo()
        dispositivo = dispositivo_optimo if self.dispositivo_solicitado == "auto" else self.dispositivo_solicitado
        if self.tipo_computo_solicitado != "auto":
            tipo_computo = self.tipo_computo_solicitado
        else:
            tipo_computo = "float16" if dispositivo == "cuda" else "int8"
        return dispositivo, tipo_computo

    def cargar_modelo(self, callback_progreso: CallbackProgreso = None) -> None:
        """Carga el modelo de Whisper (una sola vez). Si CUDA falla, usa CPU."""
        if self._modelo is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise ErrorAlineacion(
                "No está instalado faster-whisper. Ejecuta: pip install -r requirements.txt"
            ) from error

        dispositivo, tipo_computo = self._resolver_configuracion()
        self._notificar(callback_progreso, 0.02, f"Cargando modelo Whisper '{self.nombre_modelo}' en {dispositivo.upper()}...")
        try:
            self._modelo = WhisperModel(
                self.nombre_modelo,
                device=dispositivo,
                compute_type=tipo_computo,
                download_root=self.directorio_modelos,
            )
        except Exception as error_gpu:  # noqa: BLE001
            if dispositivo != "cuda":
                raise ErrorAlineacion(f"No se pudo cargar el modelo Whisper: {error_gpu}") from error_gpu
            # Fallo típico en Windows: faltan cuBLAS/cuDNN → reintento en CPU.
            self._notificar(callback_progreso, 0.04, "La GPU no está disponible para Whisper, usando CPU...")
            dispositivo, tipo_computo = "cpu", "int8"
            try:
                self._modelo = WhisperModel(
                    self.nombre_modelo,
                    device=dispositivo,
                    compute_type=tipo_computo,
                    download_root=self.directorio_modelos,
                )
            except Exception as error_cpu:  # noqa: BLE001
                raise ErrorAlineacion(f"No se pudo cargar el modelo Whisper: {error_cpu}") from error_cpu

        self.dispositivo_en_uso = dispositivo
        self.tipo_computo_en_uso = tipo_computo

    def liberar_modelo(self) -> None:
        """Libera el modelo de memoria (RAM/VRAM)."""
        self._modelo = None

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def alinear_guion_con_audio(
        self,
        ruta_audio_voz: str | Path,
        bloques_guion: list[str],
        callback_progreso: CallbackProgreso = None,
        evento_cancelacion: threading.Event | None = None,
    ) -> ResultadoAlineacion:
        """
        Calcula los tiempos de inicio y fin de cada bloque del guion.

        Args:
            ruta_audio_voz: Archivo de audio con la locución.
            bloques_guion: Frases/párrafos (``ProyectoVideo.dividir_guion_en_bloques()``).
            callback_progreso: Función ``(fraccion, mensaje)`` para informar avance.
            evento_cancelacion: Si se activa, el proceso se interrumpe.

        Returns:
            ``ResultadoAlineacion`` con bloques y palabras alineadas.
        """
        bloques_guion = [bloque for bloque in bloques_guion if bloque.strip()]
        if not bloques_guion:
            raise ErrorAlineacion("El guion no contiene texto para alinear.")
        ruta_audio = Path(ruta_audio_voz)
        if not ruta_audio.is_file():
            raise ErrorAlineacion(f"No se encontró el audio de voz: {ruta_audio}")

        self.cargar_modelo(callback_progreso)
        self._verificar_cancelacion(evento_cancelacion)

        texto_contexto = " ".join(bloques_guion) if self.usar_guion_como_contexto else None
        palabras_transcritas, duracion_audio, idioma = self._transcribir_palabras(
            ruta_audio, texto_contexto, callback_progreso, evento_cancelacion
        )

        self._notificar(callback_progreso, 0.92, "Alineando guion con el audio...")
        tokens_guion = self.tokenizar_guion(bloques_guion)

        if not palabras_transcritas:
            # Audio sin voz reconocible: reparto proporcional como último recurso.
            resultado = self.distribuir_proporcionalmente(bloques_guion, duracion_audio)
            resultado.idioma_detectado = idioma
            return resultado

        tiempos, cantidad_exactas = self._emparejar_tiempos(tokens_guion, palabras_transcritas, duracion_audio)
        resultado = self._construir_resultado(bloques_guion, tokens_guion, tiempos, duracion_audio)
        resultado.idioma_detectado = idioma
        resultado.porcentaje_coincidencia = round(100.0 * cantidad_exactas / max(1, len(tokens_guion)), 1)

        self._notificar(
            callback_progreso, 1.0, f"Alineación completada ({resultado.porcentaje_coincidencia}% de coincidencia)."
        )
        return resultado

    # ------------------------------------------------------------------ #
    # Transcripción
    # ------------------------------------------------------------------ #
    def _transcribir_palabras(
        self,
        ruta_audio: Path,
        texto_contexto: str | None,
        callback_progreso: CallbackProgreso,
        evento_cancelacion: threading.Event | None,
    ) -> tuple[list[_PalabraTranscrita], float, str | None]:
        """Transcribe el audio y devuelve palabras con tiempos, duración e idioma."""
        self._notificar(callback_progreso, 0.08, "Transcribiendo audio con Whisper...")
        try:
            segmentos, informacion = self._modelo.transcribe(
                str(ruta_audio),
                language=self.idioma,
                word_timestamps=True,
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                initial_prompt=texto_contexto[:800] if texto_contexto else None,
            )
        except Exception as error:  # noqa: BLE001
            raise ErrorAlineacion(f"Error al transcribir el audio: {error}") from error

        duracion_audio = float(informacion.duration or 0.0)
        palabras: list[_PalabraTranscrita] = []
        try:
            # ``segmentos`` es un generador: la transcripción real ocurre al iterar.
            for segmento in segmentos:
                self._verificar_cancelacion(evento_cancelacion)
                for palabra in segmento.words or []:
                    normalizada = self.normalizar_palabra(palabra.word)
                    if normalizada:
                        palabras.append(_PalabraTranscrita(normalizada, float(palabra.start), float(palabra.end)))
                if duracion_audio > 0:
                    fraccion = 0.08 + 0.82 * min(1.0, segmento.end / duracion_audio)
                    self._notificar(callback_progreso, fraccion, f"Transcribiendo... {segmento.end:.0f}s / {duracion_audio:.0f}s")
        except AlineacionCancelada:
            raise
        except Exception as error:  # noqa: BLE001
            raise ErrorAlineacion(f"Error al transcribir el audio: {error}") from error

        if duracion_audio <= 0 and palabras:
            duracion_audio = palabras[-1].fin
        if duracion_audio <= 0:
            raise ErrorAlineacion("No se pudo determinar la duración del audio de voz.")
        return palabras, duracion_audio, getattr(informacion, "language", None)

    # ------------------------------------------------------------------ #
    # Normalización y tokenización
    # ------------------------------------------------------------------ #
    @staticmethod
    def normalizar_palabra(texto: str) -> str:
        """Minúsculas, sin tildes ni signos: 'Canción,' → 'cancion'."""
        descompuesto = unicodedata.normalize("NFD", texto.lower())
        sin_tildes = "".join(caracter for caracter in descompuesto if unicodedata.category(caracter) != "Mn")
        return re.sub(r"[^\w]", "", sin_tildes).replace("_", "")

    @classmethod
    def tokenizar_guion(cls, bloques_guion: list[str]) -> list[_TokenGuion]:
        """Divide cada bloque en palabras conservando el texto original."""
        tokens: list[_TokenGuion] = []
        for indice_bloque, bloque in enumerate(bloques_guion):
            for palabra in bloque.split():
                normalizada = cls.normalizar_palabra(palabra) or _MARCADOR_SIN_CONTENIDO
                tokens.append(_TokenGuion(palabra, normalizada, indice_bloque))
        return tokens

    # ------------------------------------------------------------------ #
    # Emparejamiento
    # ------------------------------------------------------------------ #
    @classmethod
    def _emparejar_tiempos(
        cls,
        tokens_guion: list[_TokenGuion],
        palabras_transcritas: list[_PalabraTranscrita],
        duracion_audio: float,
    ) -> tuple[list[tuple[float, float, bool]], int]:
        """
        Asigna (inicio, fin, exacta) a cada token del guion.

        Returns:
            Lista de tiempos paralela a ``tokens_guion`` y la cantidad de
            coincidencias exactas.
        """
        secuencia_guion = [token.texto_normalizado for token in tokens_guion]
        secuencia_audio = [palabra.texto_normalizado for palabra in palabras_transcritas]
        comparador = difflib.SequenceMatcher(None, secuencia_guion, secuencia_audio, autojunk=False)

        tiempos: list[tuple[float, float, bool] | None] = [None] * len(tokens_guion)
        cantidad_exactas = 0

        for operacion, i1, i2, j1, j2 in comparador.get_opcodes():
            if operacion == "equal":
                for desplazamiento in range(i2 - i1):
                    palabra = palabras_transcritas[j1 + desplazamiento]
                    tiempos[i1 + desplazamiento] = (palabra.inicio, palabra.fin, True)
                    cantidad_exactas += 1
            elif operacion == "replace":
                if i2 - i1 == j2 - j1:
                    # Misma cantidad de palabras: probablemente errores ortográficos → 1 a 1.
                    for desplazamiento in range(i2 - i1):
                        palabra = palabras_transcritas[j1 + desplazamiento]
                        tiempos[i1 + desplazamiento] = (palabra.inicio, palabra.fin, False)
                else:
                    # Distinta cantidad (ej: "2024" vs "dos mil veinticuatro"): se reparte el tramo.
                    inicio_tramo = palabras_transcritas[j1].inicio
                    fin_tramo = palabras_transcritas[j2 - 1].fin
                    tramos = cls._repartir_por_longitud(
                        [tokens_guion[i].texto_original for i in range(i1, i2)], inicio_tramo, fin_tramo
                    )
                    for desplazamiento, (inicio, fin) in enumerate(tramos):
                        tiempos[i1 + desplazamiento] = (inicio, fin, False)
            # "delete": palabras del guion no pronunciadas/reconocidas → se interpolan después.
            # "insert": palabras extra de Whisper → se ignoran.

        tiempos_completos = cls._interpolar_huecos(tokens_guion, tiempos, duracion_audio)
        return cls._forzar_monotonia(tiempos_completos, duracion_audio), cantidad_exactas

    @classmethod
    def _interpolar_huecos(
        cls,
        tokens_guion: list[_TokenGuion],
        tiempos: list[tuple[float, float, bool] | None],
        duracion_audio: float,
    ) -> list[tuple[float, float, bool]]:
        """Rellena los tokens sin tiempo repartiendo el hueco entre vecinos conocidos."""
        resultado: list[tuple[float, float, bool]] = []
        indice = 0
        total = len(tiempos)
        while indice < total:
            if tiempos[indice] is not None:
                resultado.append(tiempos[indice])  # type: ignore[arg-type]
                indice += 1
                continue
            # Localiza el tramo consecutivo de tokens sin tiempo.
            fin_hueco = indice
            while fin_hueco < total and tiempos[fin_hueco] is None:
                fin_hueco += 1
            limite_inferior = resultado[-1][1] if resultado else 0.0
            limite_superior = tiempos[fin_hueco][0] if fin_hueco < total else duracion_audio  # type: ignore[index]
            limite_superior = max(limite_superior, limite_inferior)
            tramos = cls._repartir_por_longitud(
                [tokens_guion[i].texto_original for i in range(indice, fin_hueco)],
                limite_inferior,
                limite_superior,
            )
            resultado.extend((inicio, fin, False) for inicio, fin in tramos)
            indice = fin_hueco
        return resultado

    @staticmethod
    def _repartir_por_longitud(textos: list[str], inicio: float, fin: float) -> list[tuple[float, float]]:
        """Reparte el intervalo [inicio, fin] entre textos según su cantidad de caracteres."""
        if not textos:
            return []
        pesos = [max(1, len(texto)) for texto in textos]
        peso_total = sum(pesos)
        duracion = max(0.0, fin - inicio)
        tramos: list[tuple[float, float]] = []
        cursor = inicio
        for peso in pesos:
            siguiente = cursor + duracion * peso / peso_total
            tramos.append((cursor, siguiente))
            cursor = siguiente
        return tramos

    @staticmethod
    def _forzar_monotonia(
        tiempos: list[tuple[float, float, bool]], duracion_audio: float
    ) -> list[tuple[float, float, bool]]:
        """Garantiza tiempos crecientes, dentro de [0, duración] y con fin >= inicio."""
        corregidos: list[tuple[float, float, bool]] = []
        inicio_anterior = 0.0
        for inicio, fin, exacta in tiempos:
            inicio = min(max(inicio, inicio_anterior, 0.0), duracion_audio)
            fin = min(max(fin, inicio), duracion_audio)
            corregidos.append((inicio, fin, exacta))
            inicio_anterior = inicio
        return corregidos

    # ------------------------------------------------------------------ #
    # Construcción del resultado
    # ------------------------------------------------------------------ #
    @staticmethod
    def _construir_resultado(
        bloques_guion: list[str],
        tokens_guion: list[_TokenGuion],
        tiempos: list[tuple[float, float, bool]],
        duracion_audio: float,
    ) -> ResultadoAlineacion:
        palabras_por_bloque: list[list[PalabraAlineada]] = [[] for _ in bloques_guion]
        for token, (inicio, fin, exacta) in zip(tokens_guion, tiempos):
            palabras_por_bloque[token.indice_bloque].append(
                PalabraAlineada(token.texto_original, round(inicio, 3), round(fin, 3), exacta)
            )

        bloques: list[BloqueAlineado] = []
        for indice, (texto, palabras) in enumerate(zip(bloques_guion, palabras_por_bloque)):
            if not palabras:
                continue
            bloques.append(BloqueAlineado(indice, texto, palabras[0].inicio, palabras[-1].fin, palabras))
        return ResultadoAlineacion(bloques=bloques, duracion_audio=duracion_audio)

    @classmethod
    def distribuir_proporcionalmente(cls, bloques_guion: list[str], duracion_audio: float) -> ResultadoAlineacion:
        """
        Plan B sin IA: reparte la duración total entre las palabras según su
        longitud. Útil si Whisper no reconoce voz o para pruebas rápidas.
        """
        tokens = cls.tokenizar_guion(bloques_guion)
        tramos = cls._repartir_por_longitud([token.texto_original for token in tokens], 0.0, duracion_audio)
        tiempos = [(inicio, fin, False) for inicio, fin in tramos]
        return cls._construir_resultado(bloques_guion, tokens, tiempos, duracion_audio)

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
            raise AlineacionCancelada("Alineación cancelada por el usuario.")
