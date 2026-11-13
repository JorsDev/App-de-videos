"""
Pruebas del Controlador con una Vista simulada (sin ventana real, FFmpeg ni Whisper).

Verifican el registro de acciones, la edición del proyecto, la validación
y el flujo completo en hilo secundario → cola → hilo de la interfaz.

    python -m unittest discover -s pruebas -v
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controlador import controlador_video as modulo_controlador  # noqa: E402
from controlador.controlador_video import ControladorVideo, EstadoControlador  # noqa: E402
from modelo import AlineadorAudio, ProyectoVideo  # noqa: E402
from utilidades.verificador_sistema import InformacionSistema  # noqa: E402


class VistaSimulada:
    """Implementa la API pública de VentanaPrincipal registrando las llamadas."""

    def __init__(self) -> None:
        self.acciones: dict = {}
        self.llamadas: list[tuple] = []
        self.texto_guion = ""
        self.configuracion = {
            "etiqueta_formato": "16:9 Horizontal",
            "subtitulos_activados": True,
            "efecto_ken_burns_activado": True,
            "modelo_whisper": "tiny",
            "idioma": "es",
            "nombre_archivo_salida": "prueba",
            "volumen_musica": 0.2,
        }
        self.respuesta_confirmacion = True

    def registrar_accion(self, nombre, funcion):
        self.acciones[nombre] = funcion

    def programar(self, milisegundos, funcion):
        return "id"  # El bucle se dispara manualmente en las pruebas.

    def obtener_texto_guion(self):
        return self.texto_guion

    def obtener_configuracion(self):
        return dict(self.configuracion)

    def preguntar_confirmacion(self, titulo, mensaje):
        return self.respuesta_confirmacion

    def __getattr__(self, nombre):
        # Cualquier otro método de la Vista se registra como llamada.
        def registrar(*argumentos):
            self.llamadas.append((nombre, argumentos))

        return registrar

    def nombres_llamadas(self):
        return [nombre for nombre, _ in self.llamadas]


def informacion_sistema_ficticia() -> InformacionSistema:
    return InformacionSistema("ffmpeg", "ffprobe", "7.0", True, 0, "cpu", "int8")


class PruebasControlador(unittest.TestCase):
    def setUp(self):
        parche = mock.patch.object(modulo_controlador, "verificar_sistema", side_effect=informacion_sistema_ficticia)
        parche.start()
        self.addCleanup(parche.stop)

        self.carpeta = Path(tempfile.mkdtemp())
        (self.carpeta / "voz.mp3").write_bytes(b"x")
        for nombre in ("b10.png", "b2.png", "a.png"):
            (self.carpeta / nombre).write_bytes(b"x")

        self.vista = VistaSimulada()
        self.controlador = ControladorVideo(self.vista, ProyectoVideo(carpeta_salida=self.carpeta))
        self.esperar_cola(lambda: self.controlador._informacion_sistema is not None)

    def esperar_cola(self, condicion, limite=5.0):
        """Simula el bucle after(): procesa la cola hasta cumplir la condición."""
        inicio = time.monotonic()
        while time.monotonic() - inicio < limite:
            self.controlador._procesar_cola_vista()
            if condicion():
                return
            time.sleep(0.02)
        self.fail("Se agotó el tiempo de espera")

    def test_registra_todas_las_acciones(self):
        from vista.ventana_principal import ACCIONES_DISPONIBLES

        self.assertEqual(set(self.vista.acciones), set(ACCIONES_DISPONIBLES))

    def test_gestion_de_imagenes(self):
        self.vista.acciones["agregar_carpeta_imagenes"](str(self.carpeta))
        nombres = [ruta.name for ruta in self.controlador.proyecto.rutas_imagenes]
        self.assertEqual(nombres, ["a.png", "b2.png", "b10.png"])
        self.vista.acciones["mover_imagen"](0, 1)
        self.assertEqual(self.controlador.proyecto.rutas_imagenes[1].name, "a.png")
        self.vista.acciones["ordenar_imagenes"]()
        self.assertEqual(self.controlador.proyecto.rutas_imagenes[0].name, "a.png")
        self.vista.acciones["quitar_imagen"](0)
        self.assertEqual(len(self.controlador.proyecto.rutas_imagenes), 2)
        self.vista.acciones["limpiar_imagenes"]()
        self.assertEqual(self.controlador.proyecto.rutas_imagenes, [])

    def test_musica_opcional(self):
        self.vista.acciones["seleccionar_musica"](str(self.carpeta / "voz.mp3"))
        self.assertTrue(self.controlador.proyecto.tiene_musica_fondo)
        self.vista.acciones["quitar_musica"]()
        self.assertFalse(self.controlador.proyecto.tiene_musica_fondo)

    def test_generar_con_errores_no_lanza_hilo(self):
        self.vista.acciones["generar_video"]()
        self.assertIn("mostrar_errores_validacion", self.vista.nombres_llamadas())
        self.assertEqual(self.controlador.estado, EstadoControlador.INACTIVO)

    def test_flujo_completo_en_hilo_secundario(self):
        ruta_video_esperada = self.carpeta / "prueba.mp4"

        class AlineadorFicticio:
            nombre_modelo = "tiny"
            idioma = "es"
            _modelo = object()

            def alinear_guion_con_audio(self, ruta, bloques, callback, evento):
                callback(0.5, "alineando")
                return AlineadorAudio.distribuir_proporcionalmente(bloques, 9.0)

            def liberar_modelo(self):
                pass

        def renderizar_ficticio(motor, proyecto, segmentos, duracion, directorio, ruta_ass, callback, evento):
            assert proyecto.formato_video.etiqueta == "16:9 Horizontal"
            assert ruta_ass is not None and Path(ruta_ass).is_file()
            assert len(segmentos) == 3 and abs(segmentos[-1].fin - 9.0) < 1e-6
            callback(1.0, "listo")
            ruta_video_esperada.write_bytes(b"video")
            return ruta_video_esperada

        self.vista.texto_guion = "Uno dos.\n\nTres cuatro.\n\nCinco seis."
        self.vista.acciones["seleccionar_audio_voz"](str(self.carpeta / "voz.mp3"))
        self.vista.acciones["agregar_carpeta_imagenes"](str(self.carpeta))

        with mock.patch.object(modulo_controlador, "AlineadorAudio", return_value=AlineadorFicticio()), \
             mock.patch.object(modulo_controlador.MotorFFmpeg, "obtener_duracion_medio", return_value=9.0), \
             mock.patch.object(modulo_controlador.MotorFFmpeg, "renderizar_video_final", renderizar_ficticio):
            self.vista.acciones["generar_video"]()
            self.assertEqual(self.controlador.estado, EstadoControlador.PROCESANDO)
            self.esperar_cola(lambda: self.controlador.estado == EstadoControlador.INACTIVO)

        self.assertEqual(self.controlador._ruta_ultimo_video, ruta_video_esperada)
        self.assertIn(("habilitar_abrir_resultado", (True,)), self.vista.llamadas)
        self.assertNotIn("mostrar_error", self.vista.nombres_llamadas())

    def test_cancelacion(self):
        class AlineadorLento:
            nombre_modelo = "tiny"
            idioma = None
            _modelo = object()

            def alinear_guion_con_audio(self, ruta, bloques, callback, evento):
                while not evento.is_set():
                    time.sleep(0.01)
                raise modulo_controlador.AlineacionCancelada()

            def liberar_modelo(self):
                pass

        self.vista.texto_guion = "Hola."
        self.vista.acciones["seleccionar_audio_voz"](str(self.carpeta / "voz.mp3"))
        self.vista.acciones["agregar_imagenes"]([str(self.carpeta / "a.png")])
        with mock.patch.object(modulo_controlador, "AlineadorAudio", return_value=AlineadorLento()), \
             mock.patch.object(modulo_controlador.MotorFFmpeg, "obtener_duracion_medio", return_value=3.0):
            self.vista.acciones["generar_video"]()
            self.vista.acciones["cancelar_proceso"]()
            self.esperar_cola(lambda: self.controlador.estado == EstadoControlador.INACTIVO)
        mensajes = [argumentos for nombre, argumentos in self.vista.llamadas if nombre == "mostrar_mensaje_estado"]
        self.assertTrue(any("cancelado" in argumentos[0] for argumentos in mensajes))


if __name__ == "__main__":
    unittest.main()
