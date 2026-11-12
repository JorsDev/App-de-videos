"""
Prueba de integración del pipeline completo de la capa Modelo (sin interfaz).

Requiere FFmpeg en el PATH. La primera ejecución descarga el modelo de Whisper.

Uso (desde la carpeta ``generador_videos``)::

    python pruebas/prueba_pipeline_modelo.py --voz voz.mp3 --guion guion.txt ^
        --imagenes carpeta_imagenes --salida C:/Videos [--musica musica.mp3] ^
        [--formato 16:9] [--sin-subtitulos] [--sin-ken-burns] [--modelo small] [--sin-ia]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modelo import (  # noqa: E402
    AlineadorAudio,
    FormatoVideo,
    GeneradorSubtitulos,
    MotorFFmpeg,
    ProyectoVideo,
)
from utilidades import GestorTemporales, verificar_sistema  # noqa: E402

FORMATOS_POR_ATAJO = {
    "9:16": FormatoVideo.VERTICAL_9_16,
    "16:9": FormatoVideo.HORIZONTAL_16_9,
    "1:1": FormatoVideo.CUADRADO_1_1,
    "4:5": FormatoVideo.VERTICAL_FEED_4_5,
}


def mostrar_progreso(fraccion: float, mensaje: str) -> None:
    print(f"\r[{fraccion * 100:5.1f}%] {mensaje:<70}", end="", flush=True)


def main() -> int:
    analizador = argparse.ArgumentParser(description="Prueba del pipeline del Generador de Videos")
    analizador.add_argument("--voz", required=True)
    analizador.add_argument("--guion", required=True, help="Archivo .txt del guion")
    analizador.add_argument("--imagenes", required=True, help="Carpeta con imágenes")
    analizador.add_argument("--salida", required=True, help="Carpeta de destino")
    analizador.add_argument("--musica", default=None)
    analizador.add_argument("--volumen", type=float, default=0.18)
    analizador.add_argument("--formato", choices=FORMATOS_POR_ATAJO.keys(), default="9:16")
    analizador.add_argument("--sin-subtitulos", action="store_true")
    analizador.add_argument("--sin-ken-burns", action="store_true")
    analizador.add_argument("--modelo", default="small", help="Modelo de Whisper")
    analizador.add_argument("--idioma", default=None, help="Código de idioma (es, en...)")
    analizador.add_argument("--sin-ia", action="store_true", help="Reparto proporcional sin Whisper")
    argumentos = analizador.parse_args()

    sistema = verificar_sistema()
    print(sistema.resumen(), "\n")
    if not sistema.sistema_listo:
        return 1

    proyecto = ProyectoVideo(
        ruta_audio_voz=argumentos.voz,
        texto_guion=ProyectoVideo.cargar_guion_desde_archivo(argumentos.guion),
        ruta_musica_fondo=argumentos.musica,
        volumen_musica=argumentos.volumen,
        subtitulos_activados=not argumentos.sin_subtitulos,
        efecto_ken_burns_activado=not argumentos.sin_ken_burns,
        formato_video=FORMATOS_POR_ATAJO[argumentos.formato],
        carpeta_salida=argumentos.salida,
    )
    proyecto.agregar_imagenes_de_carpeta(argumentos.imagenes)
    proyecto.validar_o_lanzar()

    motor = MotorFFmpeg(sistema.ruta_ffmpeg, sistema.ruta_ffprobe)
    duracion_voz = motor.obtener_duracion_medio(proyecto.ruta_audio_voz)
    bloques_guion = proyecto.dividir_guion_en_bloques()
    inicio = time.perf_counter()

    print(f"1) Alineando {len(bloques_guion)} bloques con {duracion_voz:.1f}s de audio")
    if argumentos.sin_ia:
        alineacion = AlineadorAudio.distribuir_proporcionalmente(bloques_guion, duracion_voz)
    else:
        alineador = AlineadorAudio(nombre_modelo=argumentos.modelo, idioma=argumentos.idioma)
        alineacion = alineador.alinear_guion_con_audio(proyecto.ruta_audio_voz, bloques_guion, mostrar_progreso)
        alineador.liberar_modelo()
        print(f"\n   Dispositivo: {alineador.dispositivo_en_uso} | Coincidencia: {alineacion.porcentaje_coincidencia}%")
    for bloque in alineacion.bloques:
        print(f"   [{bloque.inicio:7.2f} → {bloque.fin:7.2f}] {bloque.texto[:60]}")

    with GestorTemporales() as temporales:
        ruta_ass = None
        if proyecto.subtitulos_activados:
            print("2) Generando subtítulos .ass")
            ruta_ass = GeneradorSubtitulos(proyecto.ancho, proyecto.alto).generar_archivo_ass(
                alineacion.bloques, temporales.crear_ruta_temporal("subtitulos.ass"), duracion_voz
            )

        segmentos = motor.calcular_linea_tiempo_imagenes(proyecto.rutas_imagenes, alineacion.bloques, duracion_voz)
        print(f"3) Renderizando {len(segmentos)} imágenes")
        ruta_video = motor.renderizar_video_final(
            proyecto, segmentos, duracion_voz, temporales.directorio_trabajo, ruta_ass, mostrar_progreso
        )

    print(f"\n\n✔ Video generado en {time.perf_counter() - inicio:.1f}s: {ruta_video}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
