"""
Componentes modulares de la interfaz.

Cada panel encapsula sus widgets y comunica las acciones del usuario mediante
callbacks recibidos en el constructor. Los paneles NO conocen al Controlador
ni al Modelo: solo reciben datos simples (rutas, textos, números) para mostrar.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageOps

from vista import estilos
from vista.estilos import COLORES, ESPACIADO, ESPACIADO_INTERNO, FUENTES

CallbackSinArgumentos = Optional[Callable[[], None]]
CallbackRuta = Optional[Callable[[str], None]]


def recortar_texto(texto: str, longitud_maxima: int) -> str:
    """Acorta un texto largo agregando '…' en el medio."""
    if len(texto) <= longitud_maxima:
        return texto
    mitad = (longitud_maxima - 1) // 2
    return f"{texto[:mitad]}…{texto[-mitad:]}"


# ====================================================================== #
# Base
# ====================================================================== #
class TarjetaPanel(ctk.CTkFrame):
    """Contenedor con estilo de tarjeta, título y área de contenido."""

    def __init__(self, master, titulo: str, icono: str = "", **kwargs) -> None:
        super().__init__(master, fg_color=COLORES["panel"], corner_radius=estilos.RADIO_ESQUINAS, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.etiqueta_titulo = ctk.CTkLabel(
            self, text=f"{icono}  {titulo}".strip(), font=FUENTES["subtitulo"], anchor="w"
        )
        self.etiqueta_titulo.grid(row=0, column=0, sticky="ew", padx=ESPACIADO, pady=(ESPACIADO, 4))
        self.contenido = ctk.CTkFrame(self, fg_color="transparent")
        self.contenido.grid(row=1, column=0, sticky="nsew", padx=ESPACIADO, pady=(0, ESPACIADO))
        self.contenido.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)


def crear_boton_secundario(master, texto: str, comando, ancho: int = 120) -> ctk.CTkButton:
    """Botón de estilo secundario reutilizable."""
    return ctk.CTkButton(
        master,
        text=texto,
        command=comando,
        width=ancho,
        fg_color=COLORES["panel_secundario"],
        hover_color=COLORES["borde"],
        border_width=1,
        border_color=COLORES["borde"],
        font=FUENTES["normal"],
    )


# ====================================================================== #
# Audio de voz
# ====================================================================== #
class PanelAudioVoz(TarjetaPanel):
    """Selector del audio principal (voz)."""

    def __init__(
        self,
        master,
        al_seleccionar_audio: CallbackRuta = None,
        al_quitar_audio: CallbackSinArgumentos = None,
        **kwargs,
    ) -> None:
        super().__init__(master, "Audio principal (voz)", "🎙️", **kwargs)
        self._al_seleccionar_audio = al_seleccionar_audio

        self.etiqueta_archivo = ctk.CTkLabel(
            self.contenido, text=estilos.TEXTO_SIN_ARCHIVO, anchor="w",
            text_color=COLORES["texto_secundario"], font=FUENTES["normal"],
        )
        self.etiqueta_archivo.grid(row=0, column=0, sticky="ew", padx=(0, ESPACIADO_INTERNO))
        self.boton_seleccionar = ctk.CTkButton(
            self.contenido, text="Seleccionar audio", width=130, command=self._abrir_dialogo,
            fg_color=COLORES["acento"], hover_color=COLORES["acento_hover"],
        )
        self.boton_seleccionar.grid(row=0, column=1)
        self.boton_quitar = ctk.CTkButton(
            self.contenido, text="✕ Quitar", width=85, command=al_quitar_audio, state="disabled",
            fg_color=COLORES["peligro"], hover_color=COLORES["peligro_hover"],
        )
        self.boton_quitar.grid(row=0, column=2, padx=(ESPACIADO_INTERNO, 0))

    def _abrir_dialogo(self) -> None:
        ruta = filedialog.askopenfilename(title="Seleccionar audio de voz", filetypes=estilos.TIPOS_ARCHIVO_AUDIO)
        if ruta and self._al_seleccionar_audio:
            self._al_seleccionar_audio(ruta)

    def mostrar_archivo(self, nombre_archivo: str | None, detalle: str = "") -> None:
        """Muestra el archivo seleccionado (y un detalle opcional como la duración)."""
        if not nombre_archivo:
            self.etiqueta_archivo.configure(text=estilos.TEXTO_SIN_ARCHIVO, text_color=COLORES["texto_secundario"])
            self.boton_seleccionar.configure(text="Seleccionar audio")
            self.boton_quitar.configure(state="disabled")
            return
        texto = recortar_texto(nombre_archivo, 40) + (f"   ·   {detalle}" if detalle else "")
        self.etiqueta_archivo.configure(text=f"✔ {texto}", text_color=COLORES["texto"])
        self.boton_seleccionar.configure(text="Cambiar audio")
        self.boton_quitar.configure(state="normal")


# ====================================================================== #
# Guion
# ====================================================================== #
class PanelGuion(TarjetaPanel):
    """Editor del guion con carga desde archivo .txt."""

    def __init__(self, master, al_cargar_archivo: CallbackRuta = None, **kwargs) -> None:
        super().__init__(master, "Guion escrito", "📝", **kwargs)
        self._al_cargar_archivo = al_cargar_archivo
        self.contenido.grid_rowconfigure(1, weight=1)

        barra = ctk.CTkFrame(self.contenido, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", pady=(0, ESPACIADO_INTERNO))
        barra.grid_columnconfigure(2, weight=1)
        crear_boton_secundario(barra, "📂 Cargar .txt", self._abrir_dialogo, 120).grid(row=0, column=0)
        crear_boton_secundario(barra, "🗑 Limpiar", self.limpiar, 90).grid(row=0, column=1, padx=ESPACIADO_INTERNO)
        self.etiqueta_contador = ctk.CTkLabel(
            barra, text="0 palabras", font=FUENTES["pequena"], text_color=COLORES["texto_secundario"], anchor="e"
        )
        self.etiqueta_contador.grid(row=0, column=2, sticky="e")

        self.editor = ctk.CTkTextbox(
            self.contenido, font=FUENTES["editor"], wrap="word",
            fg_color=COLORES["panel_secundario"], border_width=1, border_color=COLORES["borde"],
        )
        self.editor.grid(row=1, column=0, sticky="nsew")
        self.editor.bind("<KeyRelease>", lambda _evento: self._actualizar_contador())

        ctk.CTkLabel(
            self.contenido,
            text="Consejo: separa los bloques con una línea en blanco (cada bloque ≈ una imagen).",
            font=FUENTES["pequena"], text_color=COLORES["texto_secundario"], anchor="w",
        ).grid(row=2, column=0, sticky="ew", pady=(4, 0))

    def _abrir_dialogo(self) -> None:
        ruta = filedialog.askopenfilename(title="Cargar guion", filetypes=estilos.TIPOS_ARCHIVO_GUION)
        if ruta and self._al_cargar_archivo:
            self._al_cargar_archivo(ruta)

    def _actualizar_contador(self) -> None:
        texto = self.obtener_texto()
        palabras = len(texto.split())
        bloques = len([parrafo for parrafo in texto.replace("\r", "").split("\n\n") if parrafo.strip()])
        self.etiqueta_contador.configure(text=f"{palabras} palabras · {bloques} bloque(s)")

    def obtener_texto(self) -> str:
        return self.editor.get("1.0", "end-1c")

    def establecer_texto(self, texto: str) -> None:
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", texto)
        self._actualizar_contador()

    def limpiar(self) -> None:
        self.establecer_texto("")


# ====================================================================== #
# Imágenes
# ====================================================================== #
class FilaImagen(ctk.CTkFrame):
    """Fila de la lista de imágenes: miniatura, nombre y botones de orden."""

    def __init__(
        self, master, indice: int, ruta: str, miniatura: ctk.CTkImage | None, seleccionada: bool,
        al_seleccionar: Callable[[int], None], al_mover: Callable[[int, int], None], al_quitar: Callable[[int], None],
    ) -> None:
        color = COLORES["fila_seleccionada"] if seleccionada else COLORES["fila_normal"]
        super().__init__(master, fg_color=color, corner_radius=8)
        self.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(self, text=f"{indice + 1}", width=26, font=FUENTES["negrita"]).grid(row=0, column=0, padx=(6, 2))
        etiqueta_miniatura = ctk.CTkLabel(self, text="" if miniatura else "🖼", image=miniatura, width=64, height=64)
        etiqueta_miniatura.grid(row=0, column=1, padx=4, pady=4)
        etiqueta_nombre = ctk.CTkLabel(self, text=recortar_texto(Path(ruta).name, 26), anchor="w", font=FUENTES["normal"])
        etiqueta_nombre.grid(row=0, column=2, sticky="ew", padx=4)

        for columna, (texto, comando) in enumerate(
            (("▲", lambda: al_mover(indice, -1)), ("▼", lambda: al_mover(indice, 1)), ("✕", lambda: al_quitar(indice))),
            start=3,
        ):
            ctk.CTkButton(
                self, text=texto, width=28, height=28, command=comando,
                fg_color=COLORES["peligro"] if texto == "✕" else COLORES["panel"],
                hover_color=COLORES["peligro_hover"] if texto == "✕" else COLORES["borde"],
            ).grid(row=0, column=columna, padx=2)

        for widget in (self, etiqueta_miniatura, etiqueta_nombre):
            widget.bind("<Button-1>", lambda _evento: al_seleccionar(indice))


class PanelImagenes(TarjetaPanel):
    """Lista ordenable de imágenes con miniaturas y vista previa del encuadre."""

    def __init__(
        self,
        master,
        al_agregar_archivos: Optional[Callable[[list[str]], None]] = None,
        al_agregar_carpeta: CallbackRuta = None,
        al_mover_imagen: Optional[Callable[[int, int], None]] = None,
        al_quitar_imagen: Optional[Callable[[int], None]] = None,
        al_ordenar_por_nombre: CallbackSinArgumentos = None,
        al_limpiar_imagenes: CallbackSinArgumentos = None,
        **kwargs,
    ) -> None:
        super().__init__(master, "Imágenes de apoyo", "🖼️", **kwargs)
        self._al_agregar_archivos = al_agregar_archivos
        self._al_agregar_carpeta = al_agregar_carpeta
        self._al_mover_imagen = al_mover_imagen
        self._al_quitar_imagen = al_quitar_imagen

        self._rutas: list[str] = []
        self._indice_seleccionado: int | None = None
        self._cache_miniaturas: dict[str, ctk.CTkImage | None] = {}
        self._imagen_previsualizacion: ctk.CTkImage | None = None
        # CTkLabel no limpia la imagen con image=None: se usa una imagen transparente de 1 px.
        self._imagen_vacia = ctk.CTkImage(Image.new("RGBA", (1, 1), (0, 0, 0, 0)), size=(1, 1))
        self._formato_actual = estilos.obtener_formato_por_etiqueta(estilos.FORMATO_POR_DEFECTO)

        self.contenido.grid_rowconfigure(1, weight=1)

        # Barra de acciones
        barra = ctk.CTkFrame(self.contenido, fg_color="transparent")
        barra.grid(row=0, column=0, sticky="ew", pady=(0, ESPACIADO_INTERNO))
        crear_boton_secundario(barra, "➕ Archivos", self._abrir_dialogo_archivos, 100).pack(side="left")
        crear_boton_secundario(barra, "📁 Carpeta", self._abrir_dialogo_carpeta, 95).pack(side="left", padx=6)
        crear_boton_secundario(barra, "A→Z", al_ordenar_por_nombre, 55).pack(side="left")
        crear_boton_secundario(barra, "🗑", al_limpiar_imagenes, 40).pack(side="left", padx=6)
        self.etiqueta_cantidad = ctk.CTkLabel(
            barra, text="0 imágenes", font=FUENTES["pequena"], text_color=COLORES["texto_secundario"]
        )
        self.etiqueta_cantidad.pack(side="right")

        # Lista desplazable
        self.lista = ctk.CTkScrollableFrame(self.contenido, fg_color=COLORES["panel_secundario"])
        self.lista.grid(row=1, column=0, sticky="nsew")
        self.lista.grid_columnconfigure(0, weight=1)
        self._mostrar_mensaje_lista_vacia()

        # Vista previa
        marco_previa = ctk.CTkFrame(self.contenido, fg_color=COLORES["panel_secundario"], corner_radius=8)
        marco_previa.grid(row=2, column=0, sticky="ew", pady=(ESPACIADO_INTERNO, 0))
        marco_previa.grid_columnconfigure(0, weight=1)
        self.etiqueta_titulo_previa = ctk.CTkLabel(
            marco_previa, text="Vista previa del encuadre", font=FUENTES["pequena"],
            text_color=COLORES["texto_secundario"],
        )
        self.etiqueta_titulo_previa.grid(row=0, column=0, pady=(4, 0))
        self.etiqueta_previa = ctk.CTkLabel(
            marco_previa, text="Selecciona una imagen", height=estilos.TAMANO_MAXIMO_PREVISUALIZACION[1],
            text_color=COLORES["texto_secundario"],
        )
        self.etiqueta_previa.grid(row=1, column=0, pady=(0, 6))

    # -------------------------- Diálogos -------------------------- #
    def _abrir_dialogo_archivos(self) -> None:
        rutas = filedialog.askopenfilenames(title="Seleccionar imágenes", filetypes=estilos.TIPOS_ARCHIVO_IMAGEN)
        if rutas and self._al_agregar_archivos:
            self._al_agregar_archivos(list(rutas))

    def _abrir_dialogo_carpeta(self) -> None:
        carpeta = filedialog.askdirectory(title="Seleccionar carpeta de imágenes")
        if carpeta and self._al_agregar_carpeta:
            self._al_agregar_carpeta(carpeta)

    # -------------------------- Miniaturas ------------------------ #
    def _obtener_miniatura(self, ruta: str) -> ctk.CTkImage | None:
        if ruta not in self._cache_miniaturas:
            try:
                with Image.open(ruta) as imagen:
                    imagen = ImageOps.exif_transpose(imagen).convert("RGB")
                    imagen = ImageOps.fit(imagen, estilos.TAMANO_MINIATURA, Image.Resampling.LANCZOS)
                self._cache_miniaturas[ruta] = ctk.CTkImage(imagen, imagen, size=estilos.TAMANO_MINIATURA)
            except (OSError, ValueError):
                self._cache_miniaturas[ruta] = None
        return self._cache_miniaturas[ruta]

    def _construir_previsualizacion(self, ruta: str) -> ctk.CTkImage | None:
        """Recorta la imagen con la relación de aspecto del formato elegido."""
        ancho_formato, alto_formato = self._formato_actual["ancho"], self._formato_actual["alto"]
        ancho_maximo, alto_maximo = estilos.TAMANO_MAXIMO_PREVISUALIZACION
        escala = min(ancho_maximo / ancho_formato, alto_maximo / alto_formato)
        tamano = (max(1, int(ancho_formato * escala)), max(1, int(alto_formato * escala)))
        try:
            with Image.open(ruta) as imagen:
                imagen = ImageOps.exif_transpose(imagen).convert("RGB")
                imagen = ImageOps.fit(imagen, tamano, Image.Resampling.LANCZOS)
            return ctk.CTkImage(imagen, imagen, size=tamano)
        except (OSError, ValueError):
            return None

    # -------------------------- Render de la lista ---------------- #
    def _mostrar_mensaje_lista_vacia(self) -> None:
        ctk.CTkLabel(
            self.lista, text="Agrega imágenes (.jpg, .png, .webp)\no una carpeta completa.",
            text_color=COLORES["texto_secundario"], font=FUENTES["normal"],
        ).grid(row=0, column=0, pady=40)

    def mostrar_imagenes(self, rutas: list[str], indice_seleccionado: int | None = None) -> None:
        """Reconstruye la lista con las rutas recibidas (en el orden indicado)."""
        self._rutas = list(rutas)
        if indice_seleccionado is None and self._indice_seleccionado is not None:
            indice_seleccionado = min(self._indice_seleccionado, len(rutas) - 1)
        self._indice_seleccionado = indice_seleccionado if rutas and indice_seleccionado is not None and indice_seleccionado >= 0 else None

        for hijo in self.lista.winfo_children():
            hijo.destroy()
        if not self._rutas:
            self._mostrar_mensaje_lista_vacia()
        for indice, ruta in enumerate(self._rutas):
            FilaImagen(
                self.lista, indice, ruta, self._obtener_miniatura(ruta), indice == self._indice_seleccionado,
                self._seleccionar_imagen, self._emitir_mover, self._emitir_quitar,
            ).grid(row=indice, column=0, sticky="ew", pady=2, padx=2)

        self.etiqueta_cantidad.configure(text=f"{len(self._rutas)} imagen(es)")
        # Libera miniaturas de imágenes que ya no están en la lista.
        self._cache_miniaturas = {ruta: self._cache_miniaturas.get(ruta) for ruta in self._rutas if ruta in self._cache_miniaturas}
        self._actualizar_previsualizacion()

    def _seleccionar_imagen(self, indice: int) -> None:
        self.mostrar_imagenes(self._rutas, indice)

    def _emitir_mover(self, indice: int, desplazamiento: int) -> None:
        if self._al_mover_imagen:
            self._al_mover_imagen(indice, desplazamiento)

    def _emitir_quitar(self, indice: int) -> None:
        if self._al_quitar_imagen:
            self._al_quitar_imagen(indice)

    def _actualizar_previsualizacion(self) -> None:
        etiqueta_formato = self._formato_actual["etiqueta"]
        if self._indice_seleccionado is None or not self._rutas:
            self._imagen_previsualizacion = None
            self.etiqueta_previa.configure(image=self._imagen_vacia, text="Selecciona una imagen")
            self.etiqueta_titulo_previa.configure(text=f"Vista previa del encuadre ({etiqueta_formato})")
            return
        ruta = self._rutas[self._indice_seleccionado]
        self._imagen_previsualizacion = self._construir_previsualizacion(ruta)
        if self._imagen_previsualizacion is None:
            self.etiqueta_previa.configure(image=self._imagen_vacia, text="No se pudo abrir la imagen")
        else:
            self.etiqueta_previa.configure(image=self._imagen_previsualizacion, text="")
        self.etiqueta_titulo_previa.configure(
            text=f"Encuadre {etiqueta_formato} · {recortar_texto(Path(ruta).name, 30)}"
        )

    def establecer_formato_previsualizacion(self, etiqueta_formato: str) -> None:
        """Actualiza la relación de aspecto usada en la vista previa."""
        self._formato_actual = estilos.obtener_formato_por_etiqueta(etiqueta_formato)
        self._actualizar_previsualizacion()


# ====================================================================== #
# Música de fondo
# ====================================================================== #
class PanelMusica(TarjetaPanel):
    """Selector opcional de música de fondo con control de volumen."""

    def __init__(
        self, master, al_seleccionar_musica: CallbackRuta = None, al_quitar_musica: CallbackSinArgumentos = None, **kwargs
    ) -> None:
        super().__init__(master, "Música de fondo (opcional)", "🎵", **kwargs)
        self._al_seleccionar_musica = al_seleccionar_musica

        self.etiqueta_archivo = ctk.CTkLabel(
            self.contenido, text=estilos.TEXTO_SIN_MUSICA, anchor="w",
            text_color=COLORES["texto_secundario"], font=FUENTES["normal"],
        )
        self.etiqueta_archivo.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, ESPACIADO_INTERNO))

        crear_boton_secundario(self.contenido, "Seleccionar", self._abrir_dialogo, 110).grid(row=1, column=0, sticky="w")
        self.boton_quitar = ctk.CTkButton(
            self.contenido, text="✕ Quitar", width=90, command=al_quitar_musica, state="disabled",
            fg_color=COLORES["peligro"], hover_color=COLORES["peligro_hover"],
        )
        self.boton_quitar.grid(row=1, column=1, sticky="e")

        marco_volumen = ctk.CTkFrame(self.contenido, fg_color="transparent")
        marco_volumen.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(ESPACIADO_INTERNO, 0))
        marco_volumen.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(marco_volumen, text="Volumen", font=FUENTES["normal"]).grid(row=0, column=0, padx=(0, 8))
        self.deslizador_volumen = ctk.CTkSlider(
            marco_volumen, from_=0, to=estilos.VOLUMEN_MUSICA_MAXIMO_PORCENTAJE,
            number_of_steps=estilos.VOLUMEN_MUSICA_MAXIMO_PORCENTAJE, command=self._actualizar_etiqueta_volumen,
            button_color=COLORES["acento"], progress_color=COLORES["acento"],
        )
        self.deslizador_volumen.set(estilos.VOLUMEN_MUSICA_POR_DEFECTO_PORCENTAJE)
        self.deslizador_volumen.grid(row=0, column=1, sticky="ew")
        self.etiqueta_volumen = ctk.CTkLabel(marco_volumen, text="", width=44, font=FUENTES["negrita"])
        self.etiqueta_volumen.grid(row=0, column=2, padx=(8, 0))
        self._actualizar_etiqueta_volumen(estilos.VOLUMEN_MUSICA_POR_DEFECTO_PORCENTAJE)

    def _abrir_dialogo(self) -> None:
        ruta = filedialog.askopenfilename(title="Seleccionar música de fondo", filetypes=estilos.TIPOS_ARCHIVO_AUDIO)
        if ruta and self._al_seleccionar_musica:
            self._al_seleccionar_musica(ruta)

    def _actualizar_etiqueta_volumen(self, valor: float) -> None:
        self.etiqueta_volumen.configure(text=f"{int(round(valor))}%")

    def mostrar_archivo(self, nombre_archivo: str | None) -> None:
        if nombre_archivo:
            self.etiqueta_archivo.configure(text=f"✔ {recortar_texto(nombre_archivo, 34)}", text_color=COLORES["texto"])
            self.boton_quitar.configure(state="normal")
        else:
            self.etiqueta_archivo.configure(text=estilos.TEXTO_SIN_MUSICA, text_color=COLORES["texto_secundario"])
            self.boton_quitar.configure(state="disabled")

    def obtener_volumen(self) -> float:
        """Volumen seleccionado como fracción 0..1."""
        return round(self.deslizador_volumen.get() / 100.0, 3)


# ====================================================================== #
# Exportación
# ====================================================================== #
class PanelExportacion(TarjetaPanel):
    """Formato, subtítulos, Ken Burns, opciones de IA y destino."""

    def __init__(
        self, master, al_seleccionar_carpeta: CallbackRuta = None,
        al_cambiar_formato: Optional[Callable[[str], None]] = None, **kwargs,
    ) -> None:
        super().__init__(master, "Exportación", "⚙️", **kwargs)
        self._al_seleccionar_carpeta = al_seleccionar_carpeta
        self._al_cambiar_formato = al_cambiar_formato
        self.contenido.grid_columnconfigure(1, weight=1)

        self.variable_formato = ctk.StringVar(value=estilos.FORMATO_POR_DEFECTO)
        self.variable_subtitulos = ctk.BooleanVar(value=True)
        self.variable_ken_burns = ctk.BooleanVar(value=True)
        self.variable_modelo = ctk.StringVar(value=estilos.MODELO_WHISPER_POR_DEFECTO)
        self.variable_idioma = ctk.StringVar(value=estilos.IDIOMA_POR_DEFECTO)
        self.variable_nombre = ctk.StringVar(value="")

        fila = 0
        fila = self._agregar_etiqueta("Formato", fila)
        ctk.CTkOptionMenu(
            self.contenido, values=estilos.ETIQUETAS_FORMATOS, variable=self.variable_formato,
            command=self._formato_cambiado, fg_color=COLORES["acento"], button_color=COLORES["acento_hover"],
        ).grid(row=fila - 1, column=1, sticky="ew")
        self.etiqueta_descripcion_formato = ctk.CTkLabel(
            self.contenido, text="", font=FUENTES["pequena"], text_color=COLORES["texto_secundario"], anchor="w"
        )
        self.etiqueta_descripcion_formato.grid(row=fila, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        fila += 1

        ctk.CTkSwitch(
            self.contenido, text="Subtítulos dinámicos", variable=self.variable_subtitulos,
            onvalue=True, offvalue=False, progress_color=COLORES["acento"],
        ).grid(row=fila, column=0, columnspan=2, sticky="w", pady=3)
        fila += 1
        ctk.CTkSwitch(
            self.contenido, text="Movimiento suave (Ken Burns)", variable=self.variable_ken_burns,
            onvalue=True, offvalue=False, progress_color=COLORES["acento"],
        ).grid(row=fila, column=0, columnspan=2, sticky="w", pady=(3, 8))
        fila += 1

        fila = self._agregar_etiqueta("Modelo IA", fila)
        ctk.CTkOptionMenu(
            self.contenido, values=estilos.MODELOS_WHISPER, variable=self.variable_modelo,
            command=lambda _valor: self._actualizar_descripciones(),
        ).grid(row=fila - 1, column=1, sticky="ew", pady=2)
        self.etiqueta_descripcion_modelo = ctk.CTkLabel(
            self.contenido, text="", font=FUENTES["pequena"], text_color=COLORES["texto_secundario"], anchor="w"
        )
        self.etiqueta_descripcion_modelo.grid(row=fila, column=0, columnspan=2, sticky="ew")
        fila += 1

        fila = self._agregar_etiqueta("Idioma", fila)
        ctk.CTkOptionMenu(
            self.contenido, values=list(estilos.IDIOMAS_DISPONIBLES.keys()), variable=self.variable_idioma
        ).grid(row=fila - 1, column=1, sticky="ew", pady=(2, 8))

        fila = self._agregar_etiqueta("Destino", fila)
        marco_destino = ctk.CTkFrame(self.contenido, fg_color="transparent")
        marco_destino.grid(row=fila - 1, column=1, sticky="ew")
        marco_destino.grid_columnconfigure(0, weight=1)
        self.etiqueta_carpeta = ctk.CTkLabel(
            marco_destino, text="Sin carpeta", anchor="w", font=FUENTES["pequena"], text_color=COLORES["texto_secundario"]
        )
        self.etiqueta_carpeta.grid(row=0, column=0, sticky="ew")
        crear_boton_secundario(marco_destino, "📁", self._abrir_dialogo_carpeta, 36).grid(row=0, column=1, padx=(4, 0))

        fila = self._agregar_etiqueta("Nombre", fila)
        ctk.CTkEntry(
            self.contenido, textvariable=self.variable_nombre, placeholder_text="video_fecha_hora (automático)"
        ).grid(row=fila - 1, column=1, sticky="ew", pady=(4, 0))

        self._actualizar_descripciones()

    def _agregar_etiqueta(self, texto: str, fila: int) -> int:
        ctk.CTkLabel(self.contenido, text=texto, font=FUENTES["normal"], anchor="w", width=80).grid(
            row=fila, column=0, sticky="w", pady=2
        )
        return fila + 1

    def _formato_cambiado(self, etiqueta: str) -> None:
        self._actualizar_descripciones()
        if self._al_cambiar_formato:
            self._al_cambiar_formato(etiqueta)

    def _actualizar_descripciones(self) -> None:
        formato = estilos.obtener_formato_por_etiqueta(self.variable_formato.get())
        self.etiqueta_descripcion_formato.configure(
            text=f"{formato['ancho']}x{formato['alto']} — {formato['plataformas']}"
        )
        self.etiqueta_descripcion_modelo.configure(
            text=estilos.DESCRIPCION_MODELOS_WHISPER.get(self.variable_modelo.get(), "")
        )

    def _abrir_dialogo_carpeta(self) -> None:
        carpeta = filedialog.askdirectory(title="Carpeta de destino del video")
        if carpeta and self._al_seleccionar_carpeta:
            self._al_seleccionar_carpeta(carpeta)

    def mostrar_carpeta_salida(self, ruta: str | None) -> None:
        if ruta:
            self.etiqueta_carpeta.configure(text=recortar_texto(ruta, 32), text_color=COLORES["texto"])
        else:
            self.etiqueta_carpeta.configure(text="Sin carpeta", text_color=COLORES["texto_secundario"])

    def obtener_configuracion(self) -> dict:
        """Opciones de exportación como diccionario de tipos simples."""
        return {
            "etiqueta_formato": self.variable_formato.get(),
            "subtitulos_activados": bool(self.variable_subtitulos.get()),
            "efecto_ken_burns_activado": bool(self.variable_ken_burns.get()),
            "modelo_whisper": self.variable_modelo.get(),
            "idioma": estilos.IDIOMAS_DISPONIBLES.get(self.variable_idioma.get()),
            "nombre_archivo_salida": self.variable_nombre.get().strip(),
        }


# ====================================================================== #
# Progreso y acciones principales
# ====================================================================== #
class PanelProgreso(ctk.CTkFrame):
    """Barra de progreso, mensaje de estado y botones Generar/Cancelar/Abrir."""

    def __init__(
        self, master, al_generar: CallbackSinArgumentos = None, al_cancelar: CallbackSinArgumentos = None,
        al_abrir_resultado: CallbackSinArgumentos = None, **kwargs,
    ) -> None:
        super().__init__(master, fg_color=COLORES["panel"], corner_radius=estilos.RADIO_ESQUINAS, **kwargs)
        self.grid_columnconfigure(0, weight=1)

        self.etiqueta_estado = ctk.CTkLabel(self, text=estilos.TEXTO_ESTADO_INICIAL, anchor="w", font=FUENTES["normal"])
        self.etiqueta_estado.grid(row=0, column=0, sticky="ew", padx=ESPACIADO, pady=(ESPACIADO, 4))
        self.etiqueta_porcentaje = ctk.CTkLabel(self, text="0%", width=50, font=FUENTES["negrita"])
        self.etiqueta_porcentaje.grid(row=0, column=1, padx=(0, ESPACIADO), pady=(ESPACIADO, 4))

        self.barra_progreso = ctk.CTkProgressBar(self, height=14, progress_color=COLORES["acento"])
        self.barra_progreso.set(0)
        self.barra_progreso.grid(row=1, column=0, columnspan=2, sticky="ew", padx=ESPACIADO, pady=(0, ESPACIADO))

        marco_botones = ctk.CTkFrame(self, fg_color="transparent")
        marco_botones.grid(row=0, column=2, rowspan=2, padx=ESPACIADO, pady=ESPACIADO)
        self.boton_abrir = crear_boton_secundario(marco_botones, "📂 Abrir video", al_abrir_resultado, 120)
        self.boton_abrir.configure(state="disabled")
        self.boton_abrir.pack(side="left")
        self.boton_cancelar = ctk.CTkButton(
            marco_botones, text="⏹ Cancelar", width=110, command=al_cancelar, state="disabled",
            fg_color=COLORES["peligro"], hover_color=COLORES["peligro_hover"],
        )
        self.boton_cancelar.pack(side="left", padx=ESPACIADO_INTERNO)
        self.boton_generar = ctk.CTkButton(
            marco_botones, text="🎬 Generar video", width=170, height=40, command=al_generar,
            font=FUENTES["subtitulo"], fg_color=COLORES["exito"], hover_color=COLORES["exito_hover"],
        )
        self.boton_generar.pack(side="left")

    def actualizar_progreso(self, fraccion: float, mensaje: str | None = None) -> None:
        fraccion = max(0.0, min(1.0, fraccion))
        self.barra_progreso.set(fraccion)
        self.etiqueta_porcentaje.configure(text=f"{int(fraccion * 100)}%")
        if mensaje:
            self.etiqueta_estado.configure(text=mensaje, text_color=COLORES["texto"])

    def mostrar_mensaje(self, mensaje: str, tipo: str = "normal") -> None:
        """tipo: 'normal', 'exito', 'error' o 'advertencia'."""
        colores = {"exito": COLORES["exito"], "error": COLORES["peligro"], "advertencia": COLORES["advertencia"]}
        self.etiqueta_estado.configure(text=mensaje, text_color=colores.get(tipo, COLORES["texto"]))

    def establecer_procesando(self, procesando: bool) -> None:
        self.boton_generar.configure(state="disabled" if procesando else "normal")
        self.boton_cancelar.configure(state="normal" if procesando else "disabled")
        if procesando:
            self.boton_abrir.configure(state="disabled")

    def habilitar_abrir_resultado(self, habilitado: bool) -> None:
        self.boton_abrir.configure(state="normal" if habilitado else "disabled")
