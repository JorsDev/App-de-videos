"""
Punto de entrada del Generador de Videos Automático.

Instancia las tres capas MVC y arranca el bucle de la interfaz:

    Modelo      → ProyectoVideo (estado del proyecto)
    Vista       → VentanaPrincipal (CustomTkinter)
    Controlador → ControladorVideo (orquestación, hilos, progreso)

Uso:
    python principal.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Permite ejecutar el archivo desde cualquier carpeta.
DIRECTORIO_APLICACION = Path(__file__).resolve().parent
if str(DIRECTORIO_APLICACION) not in sys.path:
    sys.path.insert(0, str(DIRECTORIO_APLICACION))

from controlador import ControladorVideo  # noqa: E402
from modelo import ProyectoVideo  # noqa: E402
from vista import VentanaPrincipal  # noqa: E402


def configurar_registro() -> None:
    """Registro en consola con formato legible."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def activar_alta_resolucion_windows() -> None:
    """Evita que Windows muestre la interfaz borrosa en pantallas con escalado."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def main() -> None:
    configurar_registro()
    activar_alta_resolucion_windows()

    proyecto = ProyectoVideo()                       # Modelo
    ventana = VentanaPrincipal()                     # Vista
    ControladorVideo(vista=ventana, proyecto=proyecto)  # Controlador

    ventana.mainloop()


if __name__ == "__main__":
    main()
