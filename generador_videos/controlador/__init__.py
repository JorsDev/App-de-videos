"""
Capa CONTROLADOR del Generador de Videos.

Orquesta la Vista y el Modelo, ejecuta el procesamiento pesado en hilos
secundarios y comunica el progreso a la interfaz de forma segura.
"""

from controlador.controlador_video import ControladorVideo, EstadoControlador

__all__ = ["ControladorVideo", "EstadoControlador"]
