# 📈 Progreso del Proyecto — Generador de Videos Automático

Bitácora de desarrollo por fases. Se actualiza al terminar cada fase de trabajo.

**Rama activa:** `version-inicial-modelo`

| Fase | Descripción | Estado |
|---|---|---|
| 1 | Infraestructura + capa Modelo + utilidades | ✅ Completada |
| 2 | Capa Vista (CustomTkinter) | ✅ Completada |
| 3 | Capa Controlador (hilos, estados, orquestación) | ✅ Completada |
| 4 | Punto de entrada `principal.py` + integración | ✅ Completada |
| 5 | Pruebas de extremo a extremo con FFmpeg + Whisper reales | ⏳ Pendiente (requiere instalar FFmpeg) |

**Siguiente paso:** instalar FFmpeg (`winget install Gyan.FFmpeg`), ejecutar `python principal.py` y generar un video real con voz, guion e imágenes de prueba.

---

## ✅ Fase 1 — Infraestructura y capa Modelo
**Fecha:** 2026-11-12

**Archivos creados**
- `requirements.txt` — `customtkinter==5.2.2`, `Pillow==10.4.0`, `faster-whisper==1.2.1`.
- `utilidades/verificador_sistema.py` — detecta FFmpeg/FFprobe (PATH o `RUTA_FFMPEG`), soporte `libass` y GPU CUDA (ctranslate2).
- `utilidades/gestor_temporales.py` — carpeta temporal por renderizado con limpieza automática (gestor de contexto) y limpieza de residuos antiguos.
- `modelo/proyecto_video.py` — DTO `ProyectoVideo`, enum `FormatoVideo` (9:16, 16:9, 1:1, 4:5), validaciones, división del guion en bloques, orden natural de imágenes, ruta de salida sin sobrescritura.
- `modelo/alineador_audio.py` — alineación forzada: faster-whisper (palabras con tiempos) + emparejamiento `difflib` + interpolación de palabras no reconocidas; fallback a CPU si CUDA falla; cancelable.
- `modelo/generador_subtitulos.py` — `.ass` dinámico con resaltado de la palabra activa, escalado por resolución y margen seguro en vertical.
- `modelo/motor_ffmpeg.py` — línea de tiempo de imágenes sin huecos, Ken Burns (5 movimientos), render en 2 fases (clips → concat + subtítulos + mezcla de música en loop con fundidos y limitador), progreso por `-progress pipe:1`, cancelación.
- `pruebas/test_modelo.py` (15 pruebas ✅) y `pruebas/prueba_pipeline_modelo.py` (integración por CLI).

**Decisiones**
- `faster-whisper` 1.0.3 → 1.2.1 (la 1.0.3 falla con las dependencias actuales por falta de `requests`).
- FFmpeg se ejecuta con la carpeta temporal como `cwd` para evitar problemas de escapado de rutas de Windows en el filtro `subtitles`.

**Pendiente detectado**
- FFmpeg no está instalado en el equipo de desarrollo → el render real aún no se ha probado.
- Sin GPU CUDA detectada → Whisper correrá en CPU.

---

## ✅ Fase 2 — Capa Vista
**Fecha:** 2026-11-13

**Objetivo:** interfaz CustomTkinter desacoplada (sin FFmpeg ni Whisper), que expone eventos al Controlador y métodos para actualizar la UI.

- [x] `vista/estilos.py` — colores, fuentes, formatos/resoluciones, modelos e idiomas de Whisper, filtros de diálogos.
- [x] `vista/paneles.py` — paneles de voz, guion (contador de palabras/bloques), imágenes (miniaturas, ▲▼✕, A→Z, vista previa del encuadre según el formato elegido), música (quitar + volumen 18 % por defecto), exportación y progreso.
- [x] `vista/ventana_principal.py` — ventana de 3 columnas + barra de progreso; API pública para el Controlador.

**Decisiones**
- Patrón de eventos: el Controlador registra funciones con `registrar_accion(nombre, funcion)`; la Vista solo emite eventos con datos simples (rutas, índices). Los diálogos de archivo pertenecen a la Vista.
- La Vista no importa el Modelo: las etiquetas de formato en `estilos.py` coinciden con `FormatoVideo` y el Controlador hace la conversión.
- `CTkLabel` no limpia imágenes con `image=None` → se usa una imagen transparente de 1 px.

**Verificación:** prueba de humo instanciando la ventana, cargando imágenes, cambiando formato y leyendo la configuración ✅.

---

## ✅ Fase 3 — Capa Controlador
**Fecha:** 2026-11-13

- [x] `controlador/controlador_video.py` — `ControladorVideo` + `EstadoControlador` (INACTIVO / PROCESANDO / CANCELANDO).

**Cómo funciona**
- Registra los 16 eventos de la Vista y mantiene el `ProyectoVideo` actualizado (voz con opción de quitar/cambiar, guion, imágenes, música, carpeta).
- Los formatos muestran su resolución explícita en el selector, destacando `16:9 Horizontal (1920×1080 Full HD)` para YouTube estándar.
- Al pulsar «Generar»: copia la configuración del formulario al proyecto → valida proyecto + sistema → congela una copia (`deepcopy`) → lanza `threading.Thread`.
- Pipeline en el hilo secundario: duración (ffprobe) → alineación Whisper → subtítulos `.ass` → línea de tiempo → render FFmpeg. Progreso global repartido: preparación 0–3 %, alineación 3–45 %, subtítulos 45–48 %, render 48–100 %.
- **Comunicación segura:** el hilo de trabajo nunca toca widgets; encola tareas en `queue.Queue` y el hilo de la UI las vacía cada 80 ms con `after()` (agrupando actualizaciones de progreso).
- Verificación del sistema y cálculo de la duración de la voz en hilos secundarios (la UI no se congela al arrancar).
- Reutiliza el modelo Whisper cargado entre videos si no cambia el modelo elegido.
- Cancelación cooperativa (`threading.Event`) que detiene Whisper y termina el proceso FFmpeg; el `.mp4` parcial se elimina.
- Cierre seguro: si hay un proceso activo, pide confirmación, cancela y espera (máx. 10 s) antes de cerrar.
- Aviso si la coincidencia guion-audio es menor al 60 %; botón «Abrir video» que muestra el archivo en el Explorador.

**Verificación:** `pruebas/test_controlador.py` con Vista simulada (7 pruebas: acciones, audio voz, imágenes, música, validación, flujo completo en hilo y cancelación) ✅ — total 23/23 pruebas.

---

## ✅ Fase 4 — Punto de entrada e integración
**Fecha:** 2026-11-13

- [x] `principal.py` — instancia Modelo (`ProyectoVideo`), Vista (`VentanaPrincipal`) y Controlador (`ControladorVideo`); configura logging y DPI alto en Windows.

**Verificación**
- Prueba de humo con la app real: arranca, detecta el sistema (“⚠ FFmpeg no encontrado · CPU”), fija `~/Videos` como destino y muestra los errores de validación correctos.
- Auditoría MVC: la Vista no importa Modelo/Controlador/subprocess/Whisper; Modelo y Controlador no importan tkinter/customtkinter ✅.

---

## ⏳ Fase 5 — Pruebas reales de extremo a extremo
- [ ] Instalar FFmpeg y verificar `libass`.
- [ ] Generar un video de cada formato (9:16, 16:9, 1:1, 4:5).
- [ ] Probar con y sin música, con y sin subtítulos, con y sin Ken Burns.
- [ ] Medir tiempos de alineación en CPU y ajustar el modelo por defecto si es necesario.
