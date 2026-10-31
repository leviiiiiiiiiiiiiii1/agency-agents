"""Overlay de arraste para selecionar uma região em um monitor."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from PIL import Image, ImageTk

from .capture import ScreenRegion


class RegionSelector(tk.Toplevel):
    """Exibe um snapshot do monitor e retorna as coordenadas selecionadas."""

    def __init__(
        self,
        master: tk.Misc,
        monitor: dict[str, int],
        screenshot: Image.Image,
        on_selected: Callable[[ScreenRegion], None],
    ) -> None:
        super().__init__(master)
        self.monitor = monitor
        self.on_selected = on_selected
        self.start: tuple[int, int] | None = None
        self.rectangle: int | None = None
        self.photo = ImageTk.PhotoImage(screenshot)

        self.title("Selecione a área do gráfico — Esc para cancelar")
        self.geometry(
            f"{screenshot.width}x{screenshot.height}"
            f"{monitor['left']:+d}{monitor['top']:+d}"
        )
        self.attributes("-topmost", True)
        self.resizable(False, False)

        self.canvas = tk.Canvas(self, width=screenshot.width, height=screenshot.height,
                                cursor="crosshair", highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.create_text(
            18, 18, anchor="nw", text="Marque toda a área das velas (não só a atual). Esc cancela.",
            fill="white", font=("Segoe UI", 14, "bold"),
        )
        self.canvas.bind("<ButtonPress-1>", self._start_selection)
        self.canvas.bind("<B1-Motion>", self._update_selection)
        self.canvas.bind("<ButtonRelease-1>", self._finish_selection)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.focus_force()

    def _start_selection(self, event: tk.Event) -> None:
        self.start = (event.x, event.y)
        if self.rectangle is not None:
            self.canvas.delete(self.rectangle)
        self.rectangle = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#ffe066", width=3, fill="#ffe066", stipple="gray25",
        )

    def _update_selection(self, event: tk.Event) -> None:
        if self.start is not None and self.rectangle is not None:
            self.canvas.coords(self.rectangle, *self.start, event.x, event.y)

    def _finish_selection(self, event: tk.Event) -> None:
        if self.start is None:
            return
        x1, y1 = self.start
        left, top = min(x1, event.x), min(y1, event.y)
        width, height = abs(event.x - x1), abs(event.y - y1)
        self.start = None
        if width < 20 or height < 20:
            return
        region = ScreenRegion(
            left=self.monitor["left"] + left,
            top=self.monitor["top"] + top,
            width=width,
            height=height,
        )
        self.destroy()
        self.on_selected(region)
