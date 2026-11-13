"""
Pruebas unitarias de la capa Modelo (no requieren FFmpeg ni descargar Whisper).

Ejecutar desde la carpeta ``generador_videos``::

    python -m unittest discover -s pruebas -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modelo.alineador_audio import AlineadorAudio, BloqueAlineado, PalabraAlineada, _PalabraTranscrita  # noqa: E402
from modelo.generador_subtitulos import (  # noqa: E402
    GeneradorSubtitulos,
    convertir_color_hex_a_ass,
    formatear_tiempo_ass,
)
from modelo.motor_ffmpeg import MotorFFmpeg  # noqa: E402
from modelo.proyecto_video import FormatoVideo, ProyectoVideo  # noqa: E402
from utilidades.gestor_temporales import GestorTemporales  # noqa: E402


def crear_bloques(intervalos: list[tuple[float, float]]) -> list[BloqueAlineado]:
    return [
        BloqueAlineado(i, f"bloque {i}", inicio, fin, [PalabraAlineada(f"p{i}", inicio, fin)])
        for i, (inicio, fin) in enumerate(intervalos)
    ]


class PruebasProyectoVideo(unittest.TestCase):
    def test_dividir_guion_por_parrafos(self):
        proyecto = ProyectoVideo(texto_guion="Hola mundo.\n\nSegundo párrafo\ncon salto.\n\n\nTercero.")
        self.assertEqual(
            proyecto.dividir_guion_en_bloques(), ["Hola mundo.", "Segundo párrafo con salto.", "Tercero."]
        )

    def test_dividir_guion_por_oraciones(self):
        proyecto = ProyectoVideo(texto_guion="Uno. ¿Dos? ¡Tres!")
        self.assertEqual(proyecto.dividir_guion_en_bloques(), ["Uno.", "¿Dos?", "¡Tres!"])

    def test_validacion_detecta_faltantes(self):
        errores = ProyectoVideo().validar()
        self.assertTrue(any("audio de voz" in error for error in errores))
        self.assertTrue(any("guion" in error for error in errores))
        self.assertTrue(any("imagen" in error for error in errores))
        self.assertTrue(any("carpeta" in error for error in errores))

    def test_validacion_correcta_y_ruta_salida_unica(self):
        with tempfile.TemporaryDirectory() as carpeta:
            carpeta = Path(carpeta)
            (carpeta / "voz.mp3").write_bytes(b"x")
            (carpeta / "a.png").write_bytes(b"x")
            proyecto = ProyectoVideo(
                ruta_audio_voz=carpeta / "voz.mp3",
                texto_guion="Hola",
                rutas_imagenes=[carpeta / "a.png"],
                carpeta_salida=carpeta,
                nombre_archivo_salida="mi_video",
            )
            self.assertEqual(proyecto.validar(), [])
            self.assertEqual(proyecto.obtener_ruta_salida().name, "mi_video.mp4")
            (carpeta / "mi_video.mp4").write_bytes(b"x")
            self.assertEqual(proyecto.obtener_ruta_salida().name, "mi_video_1.mp4")

    def test_orden_natural_y_mover_imagen(self):
        with tempfile.TemporaryDirectory() as carpeta:
            for nombre in ("img10.jpg", "img2.jpg", "img1.png", "nota.txt"):
                (Path(carpeta) / nombre).write_bytes(b"x")
            proyecto = ProyectoVideo()
            self.assertEqual(proyecto.agregar_imagenes_de_carpeta(carpeta), 3)
            self.assertEqual([r.name for r in proyecto.rutas_imagenes], ["img1.png", "img2.jpg", "img10.jpg"])
            proyecto.mover_imagen(2, -1)
            self.assertEqual([r.name for r in proyecto.rutas_imagenes], ["img1.png", "img10.jpg", "img2.jpg"])

    def test_formatos(self):
        self.assertEqual(FormatoVideo.VERTICAL_9_16.resolucion, (1080, 1920))
        self.assertEqual(FormatoVideo.HORIZONTAL_16_9.resolucion, (1920, 1080))
        self.assertEqual(FormatoVideo.desde_etiqueta("4:5 Vertical Feed"), FormatoVideo.VERTICAL_FEED_4_5)
        self.assertEqual(
            FormatoVideo.desde_etiqueta("16:9 Horizontal (1920×1080 Full HD)"),
            FormatoVideo.HORIZONTAL_16_9,
        )

    def test_quitar_audio_voz(self):
        proyecto = ProyectoVideo(ruta_audio_voz="voz.mp3")
        self.assertIsNotNone(proyecto.ruta_audio_voz)
        proyecto.quitar_audio_voz()
        self.assertIsNone(proyecto.ruta_audio_voz)


class PruebasAlineador(unittest.TestCase):
    def test_normalizar_palabra(self):
        self.assertEqual(AlineadorAudio.normalizar_palabra("¡Canción,"), "cancion")

    def test_emparejamiento_con_interpolacion(self):
        bloques = ["Hola a todos.", "Bienvenidos al canal 2024."]
        tokens = AlineadorAudio.tokenizar_guion(bloques)
        transcritas = [
            _PalabraTranscrita("hola", 0.0, 0.4),
            _PalabraTranscrita("a", 0.4, 0.5),
            _PalabraTranscrita("todos", 0.5, 1.0),
            _PalabraTranscrita("bienvenidos", 1.5, 2.0),
            _PalabraTranscrita("al", 2.0, 2.1),
            _PalabraTranscrita("canal", 2.1, 2.5),
            _PalabraTranscrita("dos", 2.6, 2.8),
            _PalabraTranscrita("mil", 2.8, 3.0),
            _PalabraTranscrita("veinticuatro", 3.0, 3.6),
        ]
        tiempos, exactas = AlineadorAudio._emparejar_tiempos(tokens, transcritas, 4.0)
        self.assertEqual(exactas, 6)
        resultado = AlineadorAudio._construir_resultado(bloques, tokens, tiempos, 4.0)
        self.assertEqual(len(resultado.bloques), 2)
        self.assertAlmostEqual(resultado.bloques[1].inicio, 1.5)
        self.assertAlmostEqual(resultado.bloques[1].palabras[-1].inicio, 2.6)  # "2024." ← "dos mil veinticuatro"
        self.assertAlmostEqual(resultado.bloques[1].fin, 3.6)

    def test_distribucion_proporcional(self):
        resultado = AlineadorAudio.distribuir_proporcionalmente(["uno dos", "tres"], 10.0)
        self.assertAlmostEqual(resultado.bloques[0].inicio, 0.0)
        self.assertAlmostEqual(resultado.bloques[-1].fin, 10.0)


class PruebasLineaTiempo(unittest.TestCase):
    def comprobar_cobertura(self, segmentos, duracion):
        self.assertAlmostEqual(segmentos[0].inicio, 0.0)
        self.assertAlmostEqual(segmentos[-1].fin, duracion)
        for anterior, siguiente in zip(segmentos, segmentos[1:]):
            self.assertAlmostEqual(anterior.fin, siguiente.inicio)
            self.assertGreater(anterior.duracion, 0)

    def test_igual_cantidad(self):
        bloques = crear_bloques([(0.5, 3), (3.2, 6), (6.5, 9.5)])
        segmentos = MotorFFmpeg.calcular_linea_tiempo_imagenes(["a", "b", "c"], bloques, 10.0)
        self.comprobar_cobertura(segmentos, 10.0)
        self.assertAlmostEqual(segmentos[1].inicio, 3.2)

    def test_menos_imagenes_que_bloques(self):
        bloques = crear_bloques([(0, 2), (2, 4), (4, 6), (6, 8), (8, 10)])
        segmentos = MotorFFmpeg.calcular_linea_tiempo_imagenes(["a", "b"], bloques, 10.0)
        self.assertEqual(len(segmentos), 2)
        self.comprobar_cobertura(segmentos, 10.0)

    def test_mas_imagenes_que_bloques(self):
        bloques = crear_bloques([(0, 8), (8, 10)])
        segmentos = MotorFFmpeg.calcular_linea_tiempo_imagenes(list("abcde"), bloques, 10.0)
        self.assertEqual(len(segmentos), 5)
        self.comprobar_cobertura(segmentos, 10.0)
        self.assertAlmostEqual(segmentos[-1].inicio, 8.0)  # el bloque corto recibe 1 imagen

    def test_frames_sin_deriva(self):
        bloques = crear_bloques([(0, 1.111), (1.111, 2.222), (2.222, 3.333)])
        segmentos = MotorFFmpeg.calcular_linea_tiempo_imagenes(list("abc"), bloques, 3.333)
        frames = MotorFFmpeg._calcular_frames_por_segmento(segmentos, 30)
        self.assertEqual(sum(frames), round(3.333 * 30))


class PruebasSubtitulos(unittest.TestCase):
    def test_utilidades_ass(self):
        self.assertEqual(convertir_color_hex_a_ass("#FFD400"), "&H0000D4FF")
        self.assertEqual(formatear_tiempo_ass(3725.456), "1:02:05.46")

    def test_generar_archivo(self):
        resultado = AlineadorAudio.distribuir_proporcionalmente(
            ["Hola a todos, esto es una prueba.", "Segundo bloque {raro}."], 6.0
        )
        generador = GeneradorSubtitulos(1080, 1920)
        with GestorTemporales() as gestor:
            ruta = generador.generar_archivo_ass(resultado.bloques, gestor.crear_ruta_temporal("s.ass"), 6.0)
            contenido = ruta.read_text(encoding="utf-8")
            directorio = gestor.directorio_trabajo
        self.assertFalse(directorio.exists())  # limpieza automática
        self.assertIn("PlayResY: 1920", contenido)
        self.assertIn("Dialogue:", contenido)
        self.assertIn("(raro)", contenido)
        self.assertIn(r"\c&H0000D4FF&", contenido)


if __name__ == "__main__":
    unittest.main()
