"""Monitor local de captura de tela e reconhecimento OCR de etiquetas."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

from .capture import ScreenCapture, ScreenRegion
from .candle_monitor import detect_candle_bars, filter_to_recent_candle
from .candle_timer import PlatformClockReading
from .region_selector import RegionSelector
from .screen_mask import mask_screen_regions
from .settings import find_tesseract_executable, load_settings, save_settings
from .signal_detector import SignalCandidate, TesseractSignalDetector
from .windows_power import set_windows_keep_awake


APP_NAME = "AUTO TRADER IQ"
POLL_MS = 500
OCR_INTERVAL_SECONDS = 0.5
CLOCK_MAX_AGE_SECONDS = 1.5


def _enable_windows_dpi_awareness() -> None:
    """Evita coordenadas virtualizadas em telas Windows com escala >100%."""
    if sys.platform != "win32":
        return
    try:  # Windows 10+
        import ctypes
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:  # Windows 8.1
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:  # fallback legado
                import ctypes
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def _data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        path = base / "AutoTraderIQ"
    else:
        path = Path.home() / ".auto_trader_iq"
    path.mkdir(parents=True, exist_ok=True)
    (path / "screenshots").mkdir(exist_ok=True)
    return path


class AutoTraderApp(tk.Tk):
    def __init__(self) -> None:
        _enable_windows_dpi_awareness()
        super().__init__()
        self.title(f"{APP_NAME} — Monitor OCR")
        self.geometry("1050x760")
        self.minsize(800, 580)

        self.data_dir = _data_dir()
        self.config_path = self.data_dir / "config.json"
        self.monitors: list[dict[str, int]] = []
        self.region: ScreenRegion | None = None
        self.running = False
        self.last_frame_hash: str | None = None
        self.last_change_at = time.monotonic()
        self.last_pil_image: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.compact_preview_photo: ImageTk.PhotoImage | None = None
        self.detector: TesseractSignalDetector | None = None
        self.last_candidates: list[SignalCandidate] = []
        self.last_ocr_at = 0.0
        self.latest_platform_clock: PlatformClockReading | None = None
        self.latest_clock_at: float | None = None
        self.candidates_by_id: dict[str, SignalCandidate] = {}
        self.excluded_regions: list[ScreenRegion] = []
        self.compact_mode = False

        self.monitor_var = tk.StringVar()
        self.clock_status = tk.StringVar(value="Relógio da plataforma aguardando OCR.")
        self.compact_during_capture_var = tk.BooleanVar(value=True)
        self.keep_awake_var = tk.BooleanVar(value=False)
        self.keep_awake_active = False
        self.keep_awake_status = tk.StringVar(
            value="Economia de energia normal; prevenção de suspensão desligada."
        )
        self.ocr_enabled_var = tk.BooleanVar(value=False)
        self.confidence_var = tk.StringVar(value="70")
        self.tesseract_path_var = tk.StringVar(value=find_tesseract_executable())
        self.ocr_status = tk.StringVar(value="OCR desligado; o app apenas reconhece sinais visuais.")
        self.region_vars = {key: tk.StringVar() for key in ("left", "top", "width", "height")}
        self.capture_status = tk.StringVar(value="Captura parada")
        self.heartbeat_status = tk.StringVar(value="Sem captura")
        self.exclusion_status = tk.StringVar(value="nenhuma área ocultada")
        self._build_ui()
        self._load_monitors()
        self._load_config()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.full_ui = ttk.Frame(self)
        self.full_ui.pack(fill="both", expand=True)
        header = ttk.Frame(self.full_ui, padding=(18, 16))
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME, font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(header, text="Monitor de etiquetas COMPRA/VENDER por OCR",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(3, 0))

        warning = ttk.Label(
            self.full_ui,
            text="Este aplicativo captura a tela e reconhece etiquetas visualmente. Não envia, registra nem acompanha operações financeiras.",
            foreground="#8a4b08", background="#fff3cd", padding=9, wraplength=760,
        )
        warning.pack(fill="x", padx=18, pady=(0, 10))

        body = ttk.Frame(self.full_ui, padding=(18, 0, 18, 18))
        body.pack(fill="both", expand=True)
        controls_pane = ttk.Frame(body, width=292)
        controls_pane.pack(side="left", fill="y", padx=(0, 14))
        controls_pane.pack_propagate(False)
        controls_canvas = tk.Canvas(
            controls_pane,
            highlightthickness=0,
            borderwidth=0,
            background=style.lookup("TFrame", "background") or self.cget("background"),
        )
        controls_scrollbar = ttk.Scrollbar(
            controls_pane, orient="vertical", command=controls_canvas.yview
        )
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        controls_canvas.pack(side="left", fill="both", expand=True)
        controls_scrollbar.pack(side="right", fill="y")
        controls = ttk.LabelFrame(controls_canvas, text="Região monitorada", padding=12)
        controls_canvas_window = controls_canvas.create_window(
            (0, 0), window=controls, anchor="nw"
        )
        controls.bind(
            "<Configure>",
            lambda _event: controls_canvas.configure(scrollregion=controls_canvas.bbox("all")),
        )
        controls_canvas.bind(
            "<Configure>",
            lambda event: controls_canvas.itemconfigure(controls_canvas_window, width=event.width),
        )
        ttk.Label(controls, text="Monitor").grid(row=0, column=0, sticky="w")
        self.monitor_combo = ttk.Combobox(controls, textvariable=self.monitor_var,
                                          state="readonly", width=27)
        self.monitor_combo.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        self.monitor_combo.bind("<<ComboboxSelected>>", lambda _event: self._persist_config())

        ttk.Button(controls, text="Selecionar com o mouse…", command=self._open_selector).grid(
            row=2, column=0, sticky="ew", pady=(0, 12)
        )
        ttk.Label(controls, text="Coordenadas (pixels absolutos)").grid(row=3, column=0, sticky="w")
        for row, (key, label) in enumerate((("left", "X / esquerda"), ("top", "Y / topo"),
                                             ("width", "Largura"), ("height", "Altura")), start=4):
            ttk.Label(controls, text=label).grid(row=row, column=0, sticky="w", pady=(5, 0))
            ttk.Entry(controls, textvariable=self.region_vars[key], width=29).grid(
                row=row + 1, column=0, sticky="ew", pady=(2, 0)
            )
        ttk.Button(controls, text="Aplicar coordenadas", command=self._apply_coordinates).grid(
            row=12, column=0, sticky="ew", pady=(12, 5)
        )
        self.start_button = ttk.Button(controls, text="Iniciar visualização", command=self._toggle_capture)
        self.start_button.grid(row=13, column=0, sticky="ew", pady=5)
        ttk.Button(controls, text="Salvar captura atual…", command=self._save_snapshot).grid(
            row=14, column=0, sticky="ew", pady=5
        )
        exclusion_controls = ttk.Frame(controls)
        exclusion_controls.grid(row=15, column=0, sticky="ew", pady=5)
        ttk.Button(
            exclusion_controls, text="Ocultar área…", command=self._open_exclusion_selector
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            exclusion_controls, text="Limpar", command=self._clear_excluded_regions
        ).pack(side="left", padx=(5, 0))
        ttk.Label(controls, textvariable=self.exclusion_status, wraplength=250).grid(
            row=16, column=0, sticky="w", pady=(0, 4)
        )

        ttk.Checkbutton(
            controls,
            text="Ativar reconhecimento OCR COMPRA/VENDER",
            variable=self.ocr_enabled_var,
            command=self._persist_config,
        ).grid(row=17, column=0, sticky="w", pady=(8, 2))
        ttk.Label(controls, text="Confiança OCR mínima (0–100)").grid(row=18, column=0, sticky="w")
        self.confidence_spinbox = ttk.Spinbox(
            controls, from_=0, to=100, textvariable=self.confidence_var, width=8,
            command=self._persist_config,
        )
        self.confidence_spinbox.grid(row=19, column=0, sticky="w", pady=(2, 0))
        self.confidence_spinbox.bind("<FocusOut>", lambda _event: self._persist_config())
        self.confidence_spinbox.bind("<Return>", lambda _event: self._persist_config())

        ttk.Label(controls, text="Executável Tesseract (opcional)").grid(
            row=20, column=0, sticky="w", pady=(6, 0)
        )
        tesseract_row = ttk.Frame(controls)
        tesseract_row.grid(row=21, column=0, sticky="ew", pady=(2, 0))
        ttk.Entry(tesseract_row, textvariable=self.tesseract_path_var, width=22).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(tesseract_row, text="…", width=3, command=self._browse_tesseract).pack(
            side="left", padx=(4, 0)
        )
        for widget in tesseract_row.winfo_children():
            if isinstance(widget, ttk.Entry):
                widget.bind("<FocusOut>", lambda _event: self._persist_config())
                widget.bind("<Return>", lambda _event: self._persist_config())

        ttk.Checkbutton(
            controls, text="Modo compacto ao monitorar (recomendado)",
            variable=self.compact_during_capture_var, command=self._persist_config,
        ).grid(row=22, column=0, sticky="w", pady=(6, 0))

        self.keep_awake_checkbutton = ttk.Checkbutton(
            controls,
            text="Manter tela/computador ativos durante a captura (Windows)",
            variable=self.keep_awake_var,
            command=self._on_keep_awake_toggle,
            state="normal" if sys.platform == "win32" else "disabled",
        )
        self.keep_awake_checkbutton.grid(row=23, column=0, sticky="w", pady=(6, 0))
        ttk.Label(controls, text="Efeito temporário; não move o mouse nem impede bloqueio manual.",
                  wraplength=280).grid(row=24, column=0, sticky="w")


        info = ttk.LabelFrame(controls, text="Estado", padding=10)
        info.grid(row=25, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(info, textvariable=self.capture_status, wraplength=250).pack(anchor="w")
        ttk.Label(info, textvariable=self.heartbeat_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        ttk.Label(info, textvariable=self.keep_awake_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        ttk.Label(info, textvariable=self.ocr_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        ttk.Label(info, textvariable=self.clock_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        controls.columnconfigure(0, weight=1)

        def scroll_controls(event: tk.Event) -> str:
            number = getattr(event, "num", None)
            if number == 4:
                controls_canvas.yview_scroll(-1, "units")
            elif number == 5:
                controls_canvas.yview_scroll(1, "units")
            else:
                delta = int(getattr(event, "delta", 0))
                units = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
                if units:
                    controls_canvas.yview_scroll(units, "units")
            return "break"

        def bind_control_wheel(widget: tk.Widget) -> None:
            widget.bind("<MouseWheel>", scroll_controls, add="+")
            widget.bind("<Button-4>", scroll_controls, add="+")
            widget.bind("<Button-5>", scroll_controls, add="+")
            for child in widget.winfo_children():
                bind_control_wheel(child)

        bind_control_wheel(controls)
        controls_canvas.bind("<MouseWheel>", scroll_controls, add="+")
        controls_canvas.bind("<Button-4>", scroll_controls, add="+")
        controls_canvas.bind("<Button-5>", scroll_controls, add="+")

        right_pane = ttk.Frame(body)
        right_pane.pack(side="left", fill="both", expand=True)
        right_canvas = tk.Canvas(
            right_pane,
            highlightthickness=0,
            borderwidth=0,
            background=style.lookup("TFrame", "background") or self.cget("background"),
        )
        right_scrollbar = ttk.Scrollbar(
            right_pane, orient="vertical", command=right_canvas.yview
        )
        right_canvas.configure(yscrollcommand=right_scrollbar.set)
        right_canvas.pack(side="left", fill="both", expand=True)
        right_scrollbar.pack(side="right", fill="y")
        right_content = ttk.Frame(right_canvas)
        right_canvas_window = right_canvas.create_window(
            (0, 0), window=right_content, anchor="nw"
        )
        right_content.bind(
            "<Configure>",
            lambda _event: right_canvas.configure(scrollregion=right_canvas.bbox("all")),
        )
        right_canvas.bind(
            "<Configure>",
            lambda event: right_canvas.itemconfigure(right_canvas_window, width=event.width),
        )

        preview_box = ttk.LabelFrame(right_content, text="Pré-visualização da região", padding=8)
        preview_box.pack(fill="x")
        self.preview_viewport = ttk.Frame(preview_box, height=340)
        self.preview_viewport.pack(fill="x", expand=False)
        self.preview_viewport.pack_propagate(False)
        self.preview = ttk.Label(
            self.preview_viewport,
            text="Selecione uma região e inicie a visualização.",
            anchor="center",
        )
        self.preview.pack(fill="both", expand=True)

        signal_box = ttk.LabelFrame(right_content, text="Etiquetas reconhecidas", padding=6)
        signal_box.pack(fill="x", pady=(8, 0))
        self.candidate_table = ttk.Treeview(
            signal_box, columns=("label", "confidence", "position"), show="headings", height=5,
        )
        self.candidate_table.heading("label", text="Etiqueta OCR")
        self.candidate_table.heading("confidence", text="Confiança")
        self.candidate_table.heading("position", text="Posição na captura")
        self.candidate_table.column("label", width=150, stretch=True)
        self.candidate_table.column("confidence", width=100, anchor="center")
        self.candidate_table.column("position", width=150, anchor="center")
        self.candidate_table.pack(fill="x")

        def scroll_right(event: tk.Event) -> str:
            number = getattr(event, "num", None)
            if number == 4:
                right_canvas.yview_scroll(-1, "units")
            elif number == 5:
                right_canvas.yview_scroll(1, "units")
            else:
                delta = int(getattr(event, "delta", 0))
                units = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
                if units:
                    right_canvas.yview_scroll(units, "units")
            return "break"

        def bind_right_wheel(widget: tk.Widget) -> None:
            if isinstance(widget, (ttk.Treeview, ttk.Scrollbar)):
                return
            widget.bind("<MouseWheel>", scroll_right, add="+")
            widget.bind("<Button-4>", scroll_right, add="+")
            widget.bind("<Button-5>", scroll_right, add="+")
            for child in widget.winfo_children():
                bind_right_wheel(child)

        bind_right_wheel(right_content)
        right_canvas.bind("<MouseWheel>", scroll_right, add="+")
        right_canvas.bind("<Button-4>", scroll_right, add="+")
        right_canvas.bind("<Button-5>", scroll_right, add="+")

        footer = ttk.Label(self.full_ui, text=f"Configuração e capturas locais: {self.data_dir}", padding=(18, 0, 18, 12))
        footer.pack(fill="x")

        self.compact_frame = ttk.Frame(self, padding=10)
        ttk.Label(
            self.compact_frame,
            text="AUTO TRADER IQ · monitoramento ativo",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            self.compact_frame,
            text="Deixe o painel fora da região monitorada. A prévia mostra a captura já mascarada.",
            wraplength=640,
        ).pack(anchor="w", pady=(2, 4))
        ttk.Label(self.compact_frame, textvariable=self.ocr_status, wraplength=640).pack(
            anchor="w", pady=(0, 2)
        )
        ttk.Label(self.compact_frame, textvariable=self.clock_status, wraplength=640).pack(
            anchor="w", pady=(0, 2)
        )
        ttk.Label(self.compact_frame, textvariable=self.keep_awake_status, wraplength=640).pack(
            anchor="w", pady=(0, 5)
        )

        compact_preview_box = ttk.LabelFrame(self.compact_frame, text="Prévia ao vivo da região", padding=4)
        compact_preview_box.pack(fill="x", pady=(0, 5))
        self.compact_preview_viewport = ttk.Frame(compact_preview_box, height=230)
        self.compact_preview_viewport.pack(fill="x", expand=False)
        self.compact_preview_viewport.pack_propagate(False)
        self.compact_preview_label = ttk.Label(
            self.compact_preview_viewport,
            text="Aguardando a primeira imagem…",
            anchor="center",
        )
        self.compact_preview_label.pack(fill="both", expand=True)

        self.compact_candidate_table = ttk.Treeview(
            self.compact_frame, columns=("label", "confidence", "position"),
            show="headings", height=2, selectmode="browse",
        )
        self.compact_candidate_table.heading("label", text="Sinal reconhecido")
        self.compact_candidate_table.heading("confidence", text="Confiança OCR")
        self.compact_candidate_table.heading("position", text="Posição")
        self.compact_candidate_table.column("label", width=190, stretch=True)
        self.compact_candidate_table.column("confidence", width=110, anchor="center")
        self.compact_candidate_table.column("position", width=130, anchor="center")
        self.compact_candidate_table.pack(fill="x", expand=False)

        compact_controls = ttk.Frame(self.compact_frame)
        compact_controls.pack(fill="x", pady=(5, 2))
        ttk.Button(
            compact_controls,
            text="Configurações (pausar)",
            command=self._return_to_full_ui,
        ).pack(side="right")

    def _load_monitors(self) -> None:
        try:
            self.monitors = ScreenCapture.list_monitors()
        except Exception as exc:
            self.capture_status.set(f"Não foi possível listar os monitores: {exc}")
            self.monitors = []
            return
        labels = [self._monitor_label(i, monitor) for i, monitor in enumerate(self.monitors)]
        self.monitor_combo["values"] = labels
        if labels:
            self.monitor_combo.current(0)

    @staticmethod
    def _monitor_label(index: int, monitor: dict[str, int]) -> str:
        return (f"Monitor {index + 1} — {monitor['width']}×{monitor['height']} px "
                f"({monitor['left']}, {monitor['top']})")

    def _selected_monitor_index(self) -> int | None:
        index = self.monitor_combo.current()
        return index if 0 <= index < len(self.monitors) else None

    def _open_selector(self) -> None:
        if self.running:
            self._stop_capture("Captura pausada para selecionar a região.")
        index = self._selected_monitor_index()
        if index is None:
            messagebox.showerror(APP_NAME, "Nenhum monitor disponível para captura.", parent=self)
            return
        monitor = self.monitors[index]
        # Esconda o próprio AUTO TRADER antes do screenshot para não selecionar a janela dele.
        self.withdraw()
        self.update_idletasks()
        self.after(350, lambda: self._show_region_overlay(monitor))

    def _show_region_overlay(self, monitor: dict[str, int]) -> None:
        try:
            image = ScreenCapture.capture(ScreenRegion(monitor["left"], monitor["top"],
                                                       monitor["width"], monitor["height"]))
        except Exception as exc:
            self.deiconify()
            messagebox.showerror(APP_NAME, f"Falha ao capturar o monitor:\n{exc}", parent=self)
            return

        def selected(region: ScreenRegion) -> None:
            self.deiconify()
            self._set_region(region)
            self._persist_config()

        def cancelled(_event: tk.Event | None = None) -> None:
            if not self.winfo_viewable():
                self.deiconify()

        overlay = RegionSelector(self, monitor, image, selected)
        overlay.bind("<Destroy>", lambda event: cancelled() if event.widget is overlay else None, add="+")

    def _set_region(self, region: ScreenRegion) -> None:
        self.region = region
        for key, value in (("left", region.left), ("top", region.top),
                           ("width", region.width), ("height", region.height)):
            self.region_vars[key].set(str(value))
        self.capture_status.set(f"Região definida: {region.width}×{region.height} px")

    @staticmethod
    def _regions_intersect(first: ScreenRegion, second: ScreenRegion) -> bool:
        return (
            first.left < second.left + second.width
            and second.left < first.left + first.width
            and first.top < second.top + second.height
            and second.top < first.top + first.height
        )

    def _open_exclusion_selector(self) -> None:
        if self.running:
            self._stop_capture("Captura pausada para ocultar os controles da plataforma.")
        index = self._selected_monitor_index()
        if index is None:
            messagebox.showerror(APP_NAME, "Nenhum monitor disponível para selecionar a área a ocultar.", parent=self)
            return
        monitor = self.monitors[index]
        self.withdraw()
        self.update_idletasks()
        self.after(350, lambda: self._show_exclusion_overlay(monitor))

    def _show_exclusion_overlay(self, monitor: dict[str, int]) -> None:
        try:
            screenshot = ScreenCapture.capture(ScreenRegion(
                monitor["left"], monitor["top"], monitor["width"], monitor["height"]
            ))
        except Exception as exc:
            self.deiconify()
            messagebox.showerror(APP_NAME, f"Falha ao capturar o monitor:\n{exc}", parent=self)
            return

        def selected(region: ScreenRegion) -> None:
            self.deiconify()
            if self.region is None or not self._regions_intersect(region, self.region):
                messagebox.showinfo(
                    APP_NAME,
                    "A área escolhida não cruza a região monitorada. Selecione os botões dentro do recorte atual.",
                    parent=self,
                )
                return
            self.excluded_regions.append(region)
            self.exclusion_status.set(f"{len(self.excluded_regions)} área(s) serão ocultadas antes do OCR e da prévia")
            self._persist_config()
            self.last_pil_image = None
            self.preview.configure(text="Área de exclusão atualizada. Inicie a visualização para conferir o recorte mascarado.", image="")

        def cancelled(_event: tk.Event | None = None) -> None:
            if not self.winfo_viewable():
                self.deiconify()

        overlay = RegionSelector(self, monitor, screenshot, selected)
        overlay.bind("<Destroy>", lambda event: cancelled() if event.widget is overlay else None, add="+")

    def _clear_excluded_regions(self) -> None:
        self.excluded_regions.clear()
        self.exclusion_status.set("nenhuma área ocultada")
        self._persist_config()
        self.last_pil_image = None
        self.preview.configure(text="Áreas ocultas removidas. Inicie a visualização para atualizar o recorte.", image="")

    def _mask_excluded_regions(self, image: Image.Image) -> None:
        if self.region is not None:
            mask_screen_regions(image, self.region, self.excluded_regions)

    def _apply_coordinates(self) -> None:
        try:
            region = ScreenRegion(**{key: int(var.get().strip()) for key, var in self.region_vars.items()})
        except (ValueError, TypeError) as exc:
            messagebox.showerror(APP_NAME, f"Coordenadas inválidas. Informe inteiros; largura e altura > 0.\n{exc}", parent=self)
            return
        self._set_region(region)
        self._persist_config()

    def _browse_tesseract(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="Selecione tesseract.exe",
            filetypes=(("Executável Tesseract", "tesseract.exe"), ("Executáveis", "*.exe"), ("Todos", "*.*")),
        )
        if selected:
            self.tesseract_path_var.set(selected)
            self._persist_config()

    def _set_capture_keep_awake(self, enabled: bool) -> bool:
        if enabled == self.keep_awake_active:
            return True
        try:
            set_windows_keep_awake(enabled)
        except Exception as exc:
            self.keep_awake_status.set(
                f"Não foi possível alterar a suspensão do Windows: {exc}"
            )
            if enabled:
                self.keep_awake_var.set(False)
                self.keep_awake_active = False
            return False
        self.keep_awake_active = enabled
        self.keep_awake_status.set(
            "Tela/computador mantidos ativos enquanto a captura roda."
            if enabled else "Pedido de tela ativa liberado; economia normal restaurada."
        )
        return True

    def _on_keep_awake_toggle(self) -> None:
        if not self.keep_awake_var.get():
            self._set_capture_keep_awake(False)
            if not self.keep_awake_active:
                self.keep_awake_status.set(
                    "Economia de energia normal; prevenção de suspensão desligada."
                )
            return
        if self.running:
            self._set_capture_keep_awake(True)
        else:
            self.keep_awake_status.set(
                "Será ativado apenas enquanto a captura estiver rodando."
            )

    def _toggle_capture(self) -> None:
        if self.running:
            self._stop_capture("Captura parada pelo usuário.")
            return
        if self.region is None:
            self._apply_coordinates()
            if self.region is None:
                return
        self._persist_config()
        self.detector = None
        if self.ocr_enabled_var.get():
            try:
                confidence = float(self.confidence_var.get())
                executable = self.tesseract_path_var.get().strip().strip('"') or find_tesseract_executable()
                detector = TesseractSignalDetector(confidence, executable or None)
                detector.check_ready()
                self.detector = detector
                self.ocr_status.set(f"OCR ativo · confiança mínima {confidence:.0f}% · apenas candidatos visuais")
            except (ValueError, RuntimeError) as exc:
                messagebox.showerror(APP_NAME, f"Não foi possível ativar o OCR:\n{exc}", parent=self)
                return
        else:
            self.ocr_status.set("OCR desligado; etiquetas não serão reconhecidas.")
        self.last_candidates = []
        self.last_ocr_at = 0.0
        self.latest_platform_clock = None
        self.latest_clock_at = None
        self._update_clock_status()
        self.running = True
        if self.keep_awake_var.get():
            self._set_capture_keep_awake(True)
        else:
            self.keep_awake_status.set(
                "Economia de energia normal; prevenção de suspensão desligada."
            )
        self.last_frame_hash = None
        self.last_change_at = time.monotonic()
        self.start_button.configure(text="Parar visualização")
        self.capture_status.set("Capturando…")
        if self.compact_during_capture_var.get():
            self._enter_compact_mode()
            self.capture_status.set("Captura ativa em modo compacto; deixe este painel fora da região monitorada.")
            # Espera a janela redimensionar antes do primeiro screenshot.
            self.after(350, self._capture_tick)
        else:
            self._capture_tick()

    def _enter_compact_mode(self) -> None:
        if self.compact_mode:
            return
        self.full_ui.pack_forget()
        self.compact_frame.pack(fill="both", expand=True)
        self.compact_mode = True
        self.minsize(640, 600)
        self.geometry("700x660+0+0")
        self.update_idletasks()

    def _exit_compact_mode(self) -> None:
        if not self.compact_mode:
            return
        self.compact_frame.pack_forget()
        self.full_ui.pack(fill="both", expand=True)
        self.compact_mode = False
        self.minsize(800, 580)
        self.geometry("1050x760")
        self.update_idletasks()

    def _return_to_full_ui(self) -> None:
        self._stop_capture("Captura pausada para ajustes.")

    def _stop_capture(self, reason: str) -> None:
        self._set_capture_keep_awake(False)
        self.running = False
        self.start_button.configure(text="Iniciar visualização")
        self.capture_status.set(reason)
        self.heartbeat_status.set("Sem captura")
        self.last_candidates = []
        self.latest_platform_clock = None
        self.latest_clock_at = None
        self._update_candidate_table([])
        self.clock_status.set("Captura parada; sem leitura OCR atual.")
        self._exit_compact_mode()
        if self.last_pil_image is not None:
            self._show_preview(self.last_pil_image)

    def _capture_tick(self) -> None:
        if not self.running or self.region is None:
            return
        try:
            image = ScreenCapture.capture(self.region)
            self._mask_excluded_regions(image)
            self.last_pil_image = image
            digest = hashlib.blake2b(image.tobytes(), digest_size=8).hexdigest()
            now = time.monotonic()
            if digest != self.last_frame_hash:
                self.last_frame_hash = digest
                self.last_change_at = now
                self.heartbeat_status.set("Imagem atualizando")
            else:
                unchanged = int(now - self.last_change_at)
                self.heartbeat_status.set(
                    f"Sem mudança visual há {unchanged}s (heurística; não confirma congelamento)"
                    if unchanged >= 5 else "Captura ativa; quadro sem mudança momentânea"
                )
            if self.detector is not None and now - self.last_ocr_at >= OCR_INTERVAL_SECONDS:
                try:
                    raw_candidates, self.latest_platform_clock = self.detector.detect_frame(image)
                    self.latest_clock_at = now if self.latest_platform_clock is not None else None
                    bars = detect_candle_bars(image)
                    self.last_candidates = filter_to_recent_candle(raw_candidates, bars)
                    self.last_ocr_at = now
                    self._update_ocr_status(self.last_candidates, len(raw_candidates), len(bars))
                    # OCR may be slower than one frame; assess freshness after processing,
                    # not against the frame-start timestamp captured before the OCR work.
                    self._update_clock_status()
                except Exception as exc:
                    self.detector = None
                    self.latest_platform_clock = None
                    self.latest_clock_at = None
                    self.last_candidates = []
                    self._update_candidate_table([])
                    self.ocr_status.set(f"OCR interrompido por erro: {exc}")
                    self._update_clock_status()
            self._show_preview(image)
            self.capture_status.set(f"Captura ativa · {image.width}×{image.height} px · 2 quadros/s")
        except Exception as exc:
            self._stop_capture(f"Erro de captura: {exc}")
            if self.state() == "iconic":
                self.deiconify()
            messagebox.showerror(APP_NAME, f"A captura foi interrompida:\n{exc}", parent=self)
            return
        self.after(POLL_MS, self._capture_tick)

    def _update_ocr_status(
        self, candidates: list[SignalCandidate], raw_count: int = 0, candle_count: int = 0
    ) -> None:
        self._update_candidate_table(candidates)
        if not candidates:
            if raw_count and candle_count < 2:
                self.ocr_status.set(
                    f"OCR viu {raw_count} etiqueta(s), mas não localizou 2 velas com segurança; "
                    "candidatos bloqueados."
                )
            elif raw_count:
                self.ocr_status.set(
                    f"OCR viu {raw_count} etiqueta(s); todas parecem históricas ou desalinhadas "
                    "das 2 velas mais recentes e foram ignoradas."
                )
            else:
                self.ocr_status.set("Nenhuma etiqueta recente legível; rótulos de velas passadas são ignorados.")
            return
        summary = " | ".join(
            f"{'COMPRA' if item.direction == 'BUY' else 'VENDER'} {item.confidence:.0f}% "
            f"(OCR: {item.observed_text}) em ({item.left},{item.top})"
            for item in candidates[:4]
        )
        if len(candidates) > 4:
            summary += f" | +{len(candidates) - 4}"
        self.ocr_status.set(
            f"Candidato(s) nas velas mais recentes — revise: {summary} "
            f"(OCR bruto: {raw_count}; barras detectadas: {candle_count})"
        )

    @staticmethod
    def _candidate_row_id(candidate: SignalCandidate) -> str:
        center_x = candidate.left + candidate.width // 2
        center_y = candidate.top + candidate.height // 2
        return f"{candidate.direction}-{center_x // 12}-{center_y // 12}"

    def _update_candidate_table(self, candidates: list[SignalCandidate]) -> None:
        main_selection = self.candidate_table.selection()
        compact_selection = self.compact_candidate_table.selection()
        main_id = main_selection[0] if main_selection else None
        compact_id = compact_selection[0] if compact_selection else None
        for table in (self.candidate_table, self.compact_candidate_table):
            for item_id in table.get_children():
                table.delete(item_id)
        self.candidates_by_id.clear()
        for candidate in candidates:
            item_id = self._candidate_row_id(candidate)
            # OCR pode reportar um mesmo rótulo mais de uma vez; mantém a maior confiança.
            old = self.candidates_by_id.get(item_id)
            if old is None or candidate.confidence > old.confidence:
                self.candidates_by_id[item_id] = candidate
        for item_id, candidate in self.candidates_by_id.items():
            label = "COMPRA" if candidate.direction == "BUY" else "VENDER"
            values = (f"{label} ({candidate.observed_text})", f"{candidate.confidence:.0f}%",
                      f"{candidate.left}, {candidate.top}")
            self.candidate_table.insert("", "end", iid=item_id, values=values)
            self.compact_candidate_table.insert("", "end", iid=item_id, values=values)
        if main_id in self.candidates_by_id:
            self.candidate_table.selection_set(main_id)
        if compact_id in self.candidates_by_id:
            self.compact_candidate_table.selection_set(compact_id)

    def _update_clock_status(self, now: float | None = None) -> None:
        observed_at = time.monotonic() if now is None else now
        clock = self.latest_platform_clock
        fresh = (
            clock is not None
            and self.latest_clock_at is not None
            and observed_at - self.latest_clock_at <= CLOCK_MAX_AGE_SECONDS
        )
        if not fresh or clock is None:
            self.clock_status.set("HORA ATUAL não disponível ou desatualizada.")
            return
        self.clock_status.set(
            f"HORA ATUAL reconhecida {clock.hour:02d}:{clock.minute:02d}:"
            f"{clock.second:02d}. Leitura informativa; não controla operações."
        )

    def _show_preview(self, image: Image.Image) -> None:
        annotated = image.copy()
        if self.last_candidates:
            draw = ImageDraw.Draw(annotated)
            for item in self.last_candidates:
                color = "#19a05b" if item.direction == "BUY" else "#e34141"
                box = (item.left, item.top, item.left + item.width, item.top + item.height)
                draw.rectangle(box, outline=color, width=3)
                label = "COMPRA" if item.direction == "BUY" else "VENDER"
                draw.text((item.left, max(0, item.top - 16)),
                          f"{label} {item.confidence:.0f}%", fill=color)

        if self.full_ui.winfo_viewable():
            full_width = max(200, self.preview.winfo_width() - 20)
            full_height = max(150, self.preview.winfo_height() - 20)
        else:
            full_width, full_height = 900, 480
        full_image = annotated.copy()
        full_image.thumbnail((full_width, full_height), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(full_image)
        self.preview.configure(image=self.preview_photo, text="")

        compact_width = self.compact_preview_label.winfo_width()
        if compact_width <= 1:
            compact_width = 640
        compact_image = annotated.copy()
        compact_image.thumbnail((min(640, max(240, compact_width - 12)), 220), Image.Resampling.LANCZOS)
        self.compact_preview_photo = ImageTk.PhotoImage(compact_image)
        self.compact_preview_label.configure(image=self.compact_preview_photo, text="")

    def _save_snapshot(self) -> None:
        if self.last_pil_image is None:
            messagebox.showinfo(APP_NAME, "Inicie a visualização antes de salvar uma captura.", parent=self)
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        destination = self.data_dir / "screenshots" / f"screen-{stamp}.png"
        try:
            self.last_pil_image.save(destination)
            self.capture_status.set(f"Captura salva: {destination.name}")
            messagebox.showinfo(APP_NAME, f"Imagem salva em:\n{destination}", parent=self)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível salvar a imagem:\n{exc}", parent=self)

    def _load_persisted_excluded_regions(self, config: dict[str, object]) -> None:
        raw_regions = config.get("excluded_regions", [])
        if not isinstance(raw_regions, list):
            return
        restored: list[ScreenRegion] = []
        for item in raw_regions:
            try:
                restored.append(ScreenRegion.from_dict(item))
            except (TypeError, ValueError):
                continue
        self.excluded_regions = restored
        self.exclusion_status.set(
            f"{len(restored)} área(s) ocultada(s)" if restored else "nenhuma área ocultada"
        )

    def _persist_config(self) -> None:
        payload: dict[str, object] = {
            "confidence": self.confidence_var.get(),
            "ocr_enabled": self.ocr_enabled_var.get(),
            "compact_during_capture": self.compact_during_capture_var.get(),
            "tesseract_executable": self.tesseract_path_var.get().strip().strip('"'),
            "excluded_regions": [region.as_mss_dict() for region in self.excluded_regions],
        }
        if self.region is not None:
            payload["region"] = self.region.as_mss_dict()
        monitor_index = self._selected_monitor_index()
        if monitor_index is not None:
            payload["monitor_index"] = monitor_index
        try:
            save_settings(self.config_path, payload)
        except (OSError, TypeError, ValueError) as exc:
            self.capture_status.set(f"Configuração aplicada, mas não foi possível salvar: {exc}")

    def _load_config(self) -> None:
        try:
            config = load_settings(self.config_path)
            if "region" in config:
                self._set_region(ScreenRegion.from_dict(config["region"]))
            index = config.get("monitor_index")
            if isinstance(index, int) and 0 <= index < len(self.monitors):
                self.monitor_combo.current(index)
            confidence = config.get("confidence")
            if confidence is not None:
                self.confidence_var.set(str(confidence))
            if isinstance(config.get("ocr_enabled"), bool):
                self.ocr_enabled_var.set(config["ocr_enabled"])
            if isinstance(config.get("compact_during_capture"), bool):
                self.compact_during_capture_var.set(config["compact_during_capture"])
            tesseract_executable = config.get("tesseract_executable")
            if isinstance(tesseract_executable, str) and tesseract_executable.strip():
                self.tesseract_path_var.set(tesseract_executable.strip().strip('"'))
            self._load_persisted_excluded_regions(config)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.capture_status.set(f"Configuração anterior ignorada ({exc}).")

    def _on_close(self) -> None:
        self._set_capture_keep_awake(False)
        self._persist_config()
        self.running = False
        self.destroy()


def main() -> None:
    app = AutoTraderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
