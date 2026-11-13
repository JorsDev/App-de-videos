"""
Capa VISTA del Generador de Videos (CustomTkinter).

La Vista solo muestra información y emite eventos del usuario. Nunca
ejecuta FFmpeg ni Whisper: toda acción se delega al Controlador.
"""

from vista.ventana_principal import VentanaPrincipal

__all__ = ["VentanaPrincipal"]
