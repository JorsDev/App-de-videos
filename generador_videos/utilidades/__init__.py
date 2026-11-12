"""
Paquete de utilidades transversales del Generador de Videos.

Contiene herramientas que no pertenecen a ninguna capa MVC concreta:
verificación del entorno (FFmpeg, GPU) y gestión de archivos temporales.
"""

from utilidades.gestor_temporales import GestorTemporales
from utilidades.verificador_sistema import InformacionSistema, verificar_sistema

__all__ = ["GestorTemporales", "InformacionSistema", "verificar_sistema"]
