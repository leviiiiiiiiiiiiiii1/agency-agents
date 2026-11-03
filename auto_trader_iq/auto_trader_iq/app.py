"""Interface com simulação assistida e teste experimental de cliques em conta DEMO."""

from __future__ import annotations

import csv
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
from .demo_clock import WindowsUtcMinusThreeClock
from .demo_click import (
    ClickTarget,
    click_demo_direction,
    windows_last_input_idle_seconds,
    windows_mouse_click,
    windows_mouse_move,
    windows_mouse_position,
    windows_window_at_point,
)
from .candle_monitor import detect_candle_bars, filter_to_recent_candle
from .candle_timer import (
    PlatformClockReading,
    PlatformMinuteTracker,
    m1_entry_window_open,
    m1_next_candle_entry_window_open,
    platform_clock_elapsed_seconds,
    platform_minute_advanced,
    platform_minute_offset,
)
from .region_selector import RegionSelector
from .sequence_recorder import SequenceRecorder
from .screen_mask import mask_screen_regions, point_is_masked_with_margin
from .settings import find_tesseract_executable, load_settings, save_settings
from .demo_signal_guard import DemoSignalRepeatGuard
from .signal_detector import SignalCandidate, TesseractSignalDetector
from .simulation_history import SimulationHistoryStore, append_event_best_effort
from .simulation import SimulationWorkflow
from .windows_power import set_windows_keep_awake


APP_NAME = "AUTO TRADER IQ"
DEMO_CLOCK_SOURCE = "windows_utc_minus_3"
POLL_MS = 500
OCR_INTERVAL_SECONDS = 0.5
TIMER_MAX_AGE_SECONDS = 1.5
DEFAULT_DEMO_ACTIVATION_TIMEOUT_SECONDS = 75
MIN_DEMO_ACTIVATION_TIMEOUT_SECONDS = 15
MAX_DEMO_ACTIVATION_TIMEOUT_SECONDS = 3600
DEFAULT_DEMO_ENTRY_DEADLINE_SECONDS = 15
MIN_DEMO_ENTRY_DEADLINE_SECONDS = 1
MAX_DEMO_ENTRY_DEADLINE_SECONDS = 15
DEFAULT_DEMO_MOUSE_KEEPALIVE_SECONDS = 60
MIN_DEMO_MOUSE_KEEPALIVE_SECONDS = 30
MAX_DEMO_MOUSE_KEEPALIVE_SECONDS = 600
DEMO_MOUSE_KEEPALIVE_POLL_MS = 5000
DEMO_MOUSE_KEEPALIVE_CLEARANCE_PX = 100
DEMO_MOUSE_KEEPALIVE_NUDGE_PX = 4


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
        self.title(f"{APP_NAME} — Teste DEMO assistido")
        self.geometry("1050x760")
        self.minsize(800, 580)

        self.data_dir = _data_dir()
        self.config_path = self.data_dir / "config.json"
        self.simulation_history = SimulationHistoryStore(self.data_dir / "simulation_history.csv")
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
        self.pending_armed_clock: PlatformClockReading | None = None
        self.pending_rollover_notified = False
        self.latest_bar_count = 0
        self.sequence_recorder = SequenceRecorder(self.data_dir / "sequences")
        self.sequence_status = tk.StringVar(value="Gravação de teste inativa; nenhuma imagem está sendo salva.")
        self.simulation = SimulationWorkflow()
        self.demo_clock = WindowsUtcMinusThreeClock()
        self.demo_signal_guard = DemoSignalRepeatGuard()
        self.candidates_by_id: dict[str, SignalCandidate] = {}
        self.simulation_status = tk.StringVar(value="Simulação parada; nenhuma entrada foi registrada.")
        self.demo_status = tk.StringVar(value="Cliques DEMO desligados; esta opção nunca é reativada automaticamente.")
        self.demo_automation_enabled = False
        self.demo_account_confirmed = False
        self.demo_timeout_after_id: str | None = None
        self.demo_activation_timeout_var = tk.StringVar(
            value=str(DEFAULT_DEMO_ACTIVATION_TIMEOUT_SECONDS)
        )
        self.demo_entry_deadline_var = tk.StringVar(
            value=str(DEFAULT_DEMO_ENTRY_DEADLINE_SECONDS)
        )
        self.demo_activation_timeout_active = DEFAULT_DEMO_ACTIVATION_TIMEOUT_SECONDS
        self.demo_entry_deadline_active = DEFAULT_DEMO_ENTRY_DEADLINE_SECONDS
        self.demo_entries_this_activation = 0
        self.demo_minute_tracker = PlatformMinuteTracker()
        self.last_demo_entry_candle_id: int | None = None
        self.demo_click_targets: dict[str, ClickTarget | None] = {"BUY": None, "SELL": None}
        self.demo_click_target_windows: dict[str, int | None] = {"BUY": None, "SELL": None}
        self.demo_mouse_keepalive_target: ClickTarget | None = None
        self.demo_mouse_keepalive_alternate: ClickTarget | None = None
        self.demo_mouse_keepalive_window: int | None = None
        self.demo_mouse_keepalive_after_id: str | None = None
        self.demo_mouse_keepalive_last_move_at = 0.0
        self.demo_mouse_keepalive_use_alternate = False
        self.excluded_regions: list[ScreenRegion] = []
        self.compact_mode = False

        self.monitor_var = tk.StringVar()
        self.timeframe_var = tk.StringVar(value="M1")
        self.timer_status = tk.StringVar(value="M1: aguardando leitura de HORA ATUAL da plataforma.")
        self.compact_during_capture_var = tk.BooleanVar(value=True)
        self.keep_awake_var = tk.BooleanVar(value=False)
        self.keep_awake_active = False
        self.keep_awake_status = tk.StringVar(
            value="Economia de energia normal; prevenção de suspensão desligada."
        )
        self.demo_mouse_keepalive_var = tk.BooleanVar(value=False)
        self.demo_mouse_keepalive_interval_var = tk.StringVar(
            value=str(DEFAULT_DEMO_MOUSE_KEEPALIVE_SECONDS)
        )
        self.demo_mouse_keepalive_status = tk.StringVar(
            value="Movimento automático do cursor desligado; nenhum movimento será feito."
        )
        self.ocr_enabled_var = tk.BooleanVar(value=False)
        self.confidence_var = tk.StringVar(value="70")
        self.tesseract_path_var = tk.StringVar(value=find_tesseract_executable())
        self.ocr_status = tk.StringVar(value="OCR desligado; nenhuma operação é executada.")
        self.region_vars = {key: tk.StringVar() for key in ("left", "top", "width", "height")}
        self.capture_status = tk.StringVar(value="Captura parada")
        self.heartbeat_status = tk.StringVar(value="Sem captura")
        self.buy_target_status = tk.StringVar(value="não calibrado")
        self.sell_target_status = tk.StringVar(value="não calibrado")
        self.exclusion_status = tk.StringVar(value="nenhuma área ocultada")
        self._build_ui()
        self._load_persisted_simulation_history()
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
        ttk.Label(header, text="OCR COMPRA/VENDER · simulação assistida e teste de clique DEMO",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(3, 0))

        warning = ttk.Label(
            self.full_ui,
            text="Cliques automáticos são experimentais e desligados por padrão. A ativação DEMO pode tratar vários sinais, no máximo uma tentativa por vela M1; o app não verifica tipo de conta nem aceitação da ordem.",
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
        self.sequence_button = ttk.Button(
            controls, text="Gravar sequência de teste (75 s)", command=self._toggle_sequence_recording
        )
        self.sequence_button.grid(row=15, column=0, sticky="ew", pady=5)
        ttk.Label(controls, textvariable=self.sequence_status, wraplength=250).grid(
            row=16, column=0, sticky="w", pady=(0, 4)
        )

        ttk.Checkbutton(
            controls,
            text="Ativar OCR experimental COMPRA/VENDER",
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

        ttk.Label(controls, text="Período do gráfico").grid(row=25, column=0, sticky="w", pady=(6, 0))
        self.timeframe_combo = ttk.Combobox(
            controls, textvariable=self.timeframe_var, values=("M1", "M5", "M15", "M30"),
            state="readonly", width=10,
        )
        self.timeframe_combo.grid(row=26, column=0, sticky="w", pady=(2, 0))
        self.timeframe_combo.bind("<<ComboboxSelected>>", self._on_timeframe_change)

        info = ttk.LabelFrame(controls, text="Estado", padding=10)
        info.grid(row=27, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(info, textvariable=self.capture_status, wraplength=250).pack(anchor="w")
        ttk.Label(info, textvariable=self.heartbeat_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        ttk.Label(info, textvariable=self.keep_awake_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        ttk.Label(info, textvariable=self.ocr_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        ttk.Label(info, textvariable=self.timer_status, wraplength=250).pack(anchor="w", pady=(5, 0))
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

        simulation_box = ttk.LabelFrame(
            right_content,
            text="Simulação assistida · cliques experimentais apenas em DEMO",
            padding=6,
        )
        simulation_box.pack(fill="x", pady=(8, 0))
        self.candidate_table = ttk.Treeview(
            simulation_box, columns=("label", "confidence", "position"), show="headings", height=3,
            selectmode="browse",
        )
        self.candidate_table.heading("label", text="Etiqueta OCR")
        self.candidate_table.heading("confidence", text="Confiança")
        self.candidate_table.heading("position", text="Posição na captura")
        self.candidate_table.column("label", width=120, stretch=True)
        self.candidate_table.column("confidence", width=100, anchor="center")
        self.candidate_table.column("position", width=150, anchor="center")
        self.candidate_table.pack(fill="x")
        ttk.Label(simulation_box, text="Histórico local de entradas simuladas (mais recentes)").pack(anchor="w", pady=(5, 0))
        history_frame = ttk.Frame(simulation_box)
        history_frame.pack(fill="x")
        self.history_table = ttk.Treeview(
            history_frame, columns=("time", "direction", "status"), show="headings", height=4
        )
        self.history_table.heading("time", text="Horário")
        self.history_table.heading("direction", text="Direção")
        self.history_table.heading("status", text="Estado")
        self.history_table.column("time", width=90, anchor="center")
        self.history_table.column("direction", width=100, anchor="center")
        self.history_table.column("status", width=300, anchor="w")
        history_scrollbar = ttk.Scrollbar(history_frame, orient="vertical", command=self.history_table.yview)
        self.history_table.configure(yscrollcommand=history_scrollbar.set)
        self.history_table.pack(side="left", fill="x", expand=True)
        history_scrollbar.pack(side="right", fill="y")
        history_actions = ttk.Frame(simulation_box)
        history_actions.pack(fill="x", pady=(3, 0))
        ttk.Button(
            history_actions, text="Salvar todas as entradas…", command=self._export_entry_history
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            history_actions, text="Limpar log…", command=self._clear_entry_history
        ).pack(side="left")
        sim_buttons = ttk.Frame(simulation_box)
        sim_buttons.pack(fill="x", pady=(5, 0))
        ttk.Button(sim_buttons, text="Armar candidato selecionado", command=self._arm_selected_candidate).pack(
            side="left", padx=(0, 6)
        )
        self.confirm_candle_button = ttk.Button(
            sim_buttons, text="Confirmar abertura da próxima vela", command=self._confirm_next_candle,
            state="disabled",
        )
        self.confirm_candle_button.pack(side="left", padx=6)
        self.cancel_sim_button = ttk.Button(
            sim_buttons, text="Cancelar", command=self._cancel_pending_simulation, state="disabled"
        )
        self.cancel_sim_button.pack(side="left", padx=6)
        self.demo_toggle_button = ttk.Button(
            sim_buttons, text="Ativar cliques DEMO…", command=self._toggle_demo_automation
        )
        self.demo_toggle_button.pack(side="right", padx=6)
        demo_target_row = ttk.Frame(simulation_box)
        demo_target_row.pack(fill="x", pady=(4, 0))
        ttk.Button(
            demo_target_row, text="Calibrar COMPRAR", command=lambda: self._calibrate_demo_target("BUY")
        ).pack(side="left", padx=(0, 4))
        ttk.Label(demo_target_row, textvariable=self.buy_target_status).pack(side="left", padx=(0, 12))
        ttk.Button(
            demo_target_row, text="Calibrar VENDER", command=lambda: self._calibrate_demo_target("SELL")
        ).pack(side="left", padx=(0, 4))
        ttk.Label(demo_target_row, textvariable=self.sell_target_status).pack(side="left")
        demo_mouse_keepalive_target_row = ttk.Frame(simulation_box)
        demo_mouse_keepalive_target_row.pack(fill="x", pady=(4, 0))
        ttk.Button(
            demo_mouse_keepalive_target_row,
            text="Calibrar ponto neutro (sem clique)",
            command=self._calibrate_demo_mouse_keepalive_target,
        ).pack(side="left", padx=(0, 6))
        ttk.Label(demo_mouse_keepalive_target_row, textvariable=self.demo_mouse_keepalive_status).pack(
            side="left", fill="x", expand=True
        )
        demo_mouse_keepalive_options = ttk.Frame(simulation_box)
        demo_mouse_keepalive_options.pack(fill="x", pady=(3, 0))
        self.demo_mouse_keepalive_checkbutton = ttk.Checkbutton(
            demo_mouse_keepalive_options,
            text="Movimentar cursor sem clicar após inatividade (somente DEMO)",
            variable=self.demo_mouse_keepalive_var,
            command=self._on_demo_mouse_keepalive_toggle,
            state="normal" if sys.platform == "win32" else "disabled",
        )
        self.demo_mouse_keepalive_checkbutton.pack(side="left")
        ttk.Label(demo_mouse_keepalive_options, text="intervalo ocioso (s):").pack(side="left", padx=(8, 3))
        self.demo_mouse_keepalive_spinbox = ttk.Spinbox(
            demo_mouse_keepalive_options,
            from_=MIN_DEMO_MOUSE_KEEPALIVE_SECONDS,
            to=MAX_DEMO_MOUSE_KEEPALIVE_SECONDS,
            increment=30,
            textvariable=self.demo_mouse_keepalive_interval_var,
            width=5,
        )
        self.demo_mouse_keepalive_spinbox.pack(side="left")
        demo_timeout_row = ttk.Frame(simulation_box)
        demo_timeout_row.pack(fill="x", pady=(3, 0))
        ttk.Label(
            demo_timeout_row,
            text=f"Limite da ativação contínua DEMO ({MIN_DEMO_ACTIVATION_TIMEOUT_SECONDS}–"
                 f"{MAX_DEMO_ACTIVATION_TIMEOUT_SECONDS} s):",
        ).pack(side="left", padx=(0, 6))
        self.demo_timeout_spinbox = ttk.Spinbox(
            demo_timeout_row,
            from_=MIN_DEMO_ACTIVATION_TIMEOUT_SECONDS,
            to=MAX_DEMO_ACTIVATION_TIMEOUT_SECONDS,
            increment=15,
            textvariable=self.demo_activation_timeout_var,
            width=8,
            command=self._persist_config,
        )
        self.demo_timeout_spinbox.pack(side="left")
        self.demo_timeout_spinbox.bind("<FocusOut>", lambda _event: self._persist_config())
        self.demo_timeout_spinbox.bind("<Return>", lambda _event: self._persist_config())
        ttk.Label(demo_timeout_row, text="padrão: 75 s").pack(side="left", padx=(6, 0))
        demo_deadline_row = ttk.Frame(simulation_box)
        demo_deadline_row.pack(fill="x", pady=(3, 0))
        ttk.Label(
            demo_deadline_row,
            text=f"Prazo máx. do clique ({MIN_DEMO_ENTRY_DEADLINE_SECONDS}–"
                 f"{MAX_DEMO_ENTRY_DEADLINE_SECONDS} s):",
        ).pack(side="left", padx=(0, 6))
        self.demo_entry_deadline_spinbox = ttk.Spinbox(
            demo_deadline_row,
            from_=MIN_DEMO_ENTRY_DEADLINE_SECONDS,
            to=MAX_DEMO_ENTRY_DEADLINE_SECONDS,
            increment=1,
            textvariable=self.demo_entry_deadline_var,
            width=4,
            command=self._persist_config,
        )
        self.demo_entry_deadline_spinbox.pack(side="left")
        self.demo_entry_deadline_spinbox.bind("<FocusOut>", lambda _event: self._persist_config())
        self.demo_entry_deadline_spinbox.bind("<Return>", lambda _event: self._persist_config())
        ttk.Label(demo_deadline_row, text="imediata; cancela após o prazo · padrão 15 s").pack(
            side="left", padx=(6, 0)
        )
        exclusion_row = ttk.Frame(simulation_box)
        exclusion_row.pack(fill="x", pady=(3, 0))
        ttk.Button(
            exclusion_row, text="Ocultar área dos botões do OCR/capturas…",
            command=self._open_exclusion_selector,
        ).pack(side="left", padx=(0, 5))
        ttk.Button(
            exclusion_row, text="Limpar áreas ocultas", command=self._clear_excluded_regions
        ).pack(side="left", padx=(0, 8))
        ttk.Label(exclusion_row, textvariable=self.exclusion_status).pack(side="left")
        ttk.Label(simulation_box, textvariable=self.demo_status, wraplength=650).pack(anchor="w", pady=(3, 0))
        ttk.Label(simulation_box, textvariable=self.simulation_status, wraplength=650).pack(anchor="w", pady=(4, 0))

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

        footer = ttk.Label(self.full_ui, text=f"Configuração, imagens e histórico locais: {self.data_dir}", padding=(18, 0, 18, 12))
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
        ttk.Label(self.compact_frame, textvariable=self.timer_status, wraplength=640).pack(
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

        compact_selection_actions = ttk.Frame(self.compact_frame)
        compact_selection_actions.pack(fill="x", pady=(5, 2))
        ttk.Button(
            compact_selection_actions,
            text="Armar selecionado",
            command=self._arm_compact_candidate,
        ).pack(side="left", padx=(0, 5))
        self.compact_confirm_button = ttk.Button(
            compact_selection_actions,
            text="Confirmar N+1",
            command=self._confirm_next_candle,
            state="disabled",
        )
        self.compact_confirm_button.pack(side="left", padx=5)
        self.compact_cancel_button = ttk.Button(
            compact_selection_actions,
            text="Cancelar pendente",
            command=self._cancel_pending_simulation,
            state="disabled",
        )
        self.compact_cancel_button.pack(side="left", padx=5)

        self.compact_demo_mouse_keepalive_checkbutton = ttk.Checkbutton(
            self.compact_frame,
            text="Movimentar cursor sem clicar após inatividade (DEMO)",
            variable=self.demo_mouse_keepalive_var,
            command=self._on_demo_mouse_keepalive_toggle,
            state="normal" if sys.platform == "win32" else "disabled",
        )
        self.compact_demo_mouse_keepalive_checkbutton.pack(anchor="w", pady=(3, 0))
        ttk.Label(
            self.compact_frame, textvariable=self.demo_mouse_keepalive_status, wraplength=640
        ).pack(anchor="w", pady=(0, 2))

        compact_controls = ttk.Frame(self.compact_frame)
        compact_controls.pack(fill="x", pady=(2, 2))
        self.compact_demo_toggle_button = ttk.Button(
            compact_controls, text="Ativar DEMO…", command=self._toggle_demo_automation
        )
        self.compact_demo_toggle_button.pack(side="left", padx=(0, 6))
        self.compact_sequence_button = ttk.Button(
            compact_controls, text="Gravar sequência (75 s)", command=self._toggle_sequence_recording
        )
        self.compact_sequence_button.pack(side="left", padx=6)
        ttk.Button(
            compact_controls,
            text="Configurações (pausar)",
            command=self._return_to_full_ui,
        ).pack(side="right")
        ttk.Label(self.compact_frame, textvariable=self.sequence_status, wraplength=640).pack(
            anchor="w", pady=(2, 0)
        )
        ttk.Label(self.compact_frame, textvariable=self.demo_status, wraplength=640).pack(
            anchor="w", pady=(3, 0)
        )
        ttk.Label(self.compact_frame, textvariable=self.simulation_status, wraplength=640).pack(
            anchor="w", pady=(3, 0)
        )

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
        if self.demo_automation_enabled:
            self._toggle_demo_automation()
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
            self.exclusion_status.set(f"{len(self.excluded_regions)} área(s) serão ocultadas antes do OCR e da gravação")
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
        self.last_pil_image = None
        self.preview.configure(text="Áreas ocultas removidas. Inicie a visualização para atualizar o recorte.", image="")

    def _mask_excluded_regions(self, image: Image.Image) -> None:
        if self.region is not None:
            mask_screen_regions(image, self.region, self.excluded_regions)

    def _target_is_excluded_or_outside_capture(self, target: ClickTarget) -> bool:
        if not self._inside_capture_region(target):
            return True
        return point_is_masked_with_margin(target.x, target.y, self.excluded_regions)

    def _set_demo_target_label(self, direction: str, target: ClickTarget | None) -> None:
        label = self.buy_target_status if direction == "BUY" else self.sell_target_status
        label.set("não calibrado" if target is None else f"{target.x}, {target.y}")

    def _inside_capture_region(self, target: ClickTarget) -> bool:
        region = self.region
        return bool(
            region is not None
            and region.left <= target.x < region.left + region.width
            and region.top <= target.y < region.top + region.height
        )

    def _calibrate_demo_target(self, direction: str) -> None:
        if sys.platform != "win32":
            messagebox.showerror(APP_NAME, "A calibração de cliques só funciona no Windows.", parent=self)
            return
        if direction not in {"BUY", "SELL"}:
            return
        if self.demo_automation_enabled:
            messagebox.showinfo(APP_NAME, "Desative os cliques DEMO antes de calibrar os botões.", parent=self)
            return
        label = "COMPRAR" if direction == "BUY" else "VENDER"
        consent = messagebox.askyesno(
            APP_NAME,
            f"Calibrar o centro do botão {label}. Ao continuar, a janela AUTO TRADER ficará oculta por 5 segundos. "
            "Mova o cursor para o centro do botão na plataforma e não clique. O app registra a posição e a janela sob o cursor.",
            parent=self,
        )
        if not consent:
            return
        self.demo_click_targets[direction] = None
        self.demo_click_target_windows[direction] = None
        self.demo_mouse_keepalive_target = None
        self.demo_mouse_keepalive_alternate = None
        self.demo_mouse_keepalive_window = None
        self.demo_mouse_keepalive_var.set(False)
        self.demo_mouse_keepalive_status.set("Recalibre o ponto neutro após recalibrar botões.")
        self._set_demo_target_label(direction, None)
        self.demo_status.set(f"Calibração {label}: janela oculta por 5 s; posicione o cursor no centro do botão.")
        self.withdraw()
        self._calibration_after_id = self.after(5000, lambda: self._finish_demo_calibration(direction))

    def _finish_demo_calibration(self, direction: str) -> None:
        target: ClickTarget | None = None
        target_window: int | None = None
        error: Exception | None = None
        try:
            x, y = windows_mouse_position()
            target = ClickTarget(x, y)
            target_window = windows_window_at_point(x, y)
            if target_window is None:
                raise RuntimeError("Não foi possível identificar a janela da plataforma nesse ponto.")
        except Exception as exc:
            error = exc
        finally:
            try:
                self.deiconify()
            except tk.TclError:
                return
        if error is not None:
            messagebox.showerror(APP_NAME, f"Não foi possível ler a posição do mouse:\n{error}", parent=self)
            return
        assert target is not None and target_window is not None
        self.demo_click_targets[direction] = target
        self.demo_click_target_windows[direction] = target_window
        self._set_demo_target_label(direction, target)
        label = "COMPRAR" if direction == "BUY" else "VENDER"
        if self._inside_capture_region(target) and not self._target_is_excluded_or_outside_capture(target):
            self.demo_status.set(
                f"Botão {label} calibrado em {target.x}, {target.y}; marque uma área para ocultar os botões "
                "antes de ativar cliques DEMO. Nenhum clique foi enviado."
            )
        else:
            self.demo_status.set(f"Botão {label} calibrado em {target.x}, {target.y}; nenhum clique foi enviado.")

    def _demo_mouse_keepalive_geometry_is_safe(
        self,
        target: ClickTarget,
        alternate: ClickTarget,
        target_window: int,
        *,
        check_frontmost: bool = True,
    ) -> bool:
        buy_target = self.demo_click_targets["BUY"]
        sell_target = self.demo_click_targets["SELL"]
        expected_windows = {
            self.demo_click_target_windows["BUY"],
            self.demo_click_target_windows["SELL"],
        }
        if None in expected_windows or expected_windows != {target_window}:
            return False
        for point in (target, alternate):
            if not self._target_is_excluded_or_outside_capture(point):
                return False
            for button_target in (buy_target, sell_target):
                if button_target is None:
                    return False
                dx = point.x - button_target.x
                dy = point.y - button_target.y
                if dx * dx + dy * dy < DEMO_MOUSE_KEEPALIVE_CLEARANCE_PX ** 2:
                    return False
            if check_frontmost:
                try:
                    if windows_window_at_point(point.x, point.y) != target_window:
                        return False
                except Exception:
                    return False
        return True

    def _calibrate_demo_mouse_keepalive_target(self) -> None:
        if sys.platform != "win32":
            messagebox.showerror(APP_NAME, "A calibração do cursor só funciona no Windows.", parent=self)
            return
        if self.demo_automation_enabled:
            messagebox.showinfo(APP_NAME, "Desative os cliques DEMO antes de calibrar o ponto neutro.", parent=self)
            return
        if any(self.demo_click_targets[direction] is None for direction in ("BUY", "SELL")):
            messagebox.showinfo(APP_NAME, "Calibre COMPRAR e VENDER antes de calibrar o ponto neutro.", parent=self)
            return
        if self.running:
            self._stop_capture("Captura pausada para calibrar o ponto neutro do cursor.")
        consent = messagebox.askyesno(
            APP_NAME,
            "Calibrar um ponto neutro sem clique. A janela AUTO TRADER ficará oculta por 5 segundos. "
            "Mova o cursor para uma área vazia da janela da corretora, longe dos botões de ordem e etiquetas; "
            "não clique. O ponto e uma posição adjacente serão usados apenas quando DEMO estiver autorizado.",
            parent=self,
        )
        if not consent:
            return
        self.demo_mouse_keepalive_target = None
        self.demo_mouse_keepalive_alternate = None
        self.demo_mouse_keepalive_window = None
        self.demo_mouse_keepalive_status.set("Calibração: posicione no ponto neutro, sem clicar.")
        self.withdraw()
        self.after(5000, self._finish_demo_mouse_keepalive_calibration)

    def _finish_demo_mouse_keepalive_calibration(self) -> None:
        try:
            x, y = windows_mouse_position()
            target = ClickTarget(x, y)
            target_window = windows_window_at_point(x, y)
            if target_window is None:
                raise RuntimeError("Não foi possível identificar a janela sob o ponto escolhido.")
            alternates: list[ClickTarget] = []
            for delta_x in (DEMO_MOUSE_KEEPALIVE_NUDGE_PX, -DEMO_MOUSE_KEEPALIVE_NUDGE_PX):
                try:
                    alternates.append(ClickTarget(x + delta_x, y))
                except ValueError:
                    continue
            alternate = next((
                candidate for candidate in alternates
                if windows_window_at_point(candidate.x, candidate.y) == target_window
                and self._demo_mouse_keepalive_geometry_is_safe(target, candidate, target_window)
            ), None)
            if alternate is None or not self._demo_mouse_keepalive_geometry_is_safe(
                target, alternate, target_window
            ):
                raise RuntimeError(
                    "Escolha uma área neutra fora da captura ou mascarada, dentro da mesma janela da corretora "
                    "e a pelo menos 100 px dos botões calibrados."
                )
        except Exception as exc:
            self.deiconify()
            self.demo_mouse_keepalive_status.set("Ponto neutro não calibrado.")
            messagebox.showerror(APP_NAME, f"Calibração do ponto neutro recusada:\n{exc}", parent=self)
            return
        self.deiconify()
        self.demo_mouse_keepalive_target = target
        self.demo_mouse_keepalive_alternate = alternate
        self.demo_mouse_keepalive_window = target_window
        self.demo_mouse_keepalive_use_alternate = False
        self.demo_mouse_keepalive_status.set(
            f"Ponto neutro calibrado em {target.x},{target.y}; sem clique."
        )

    def _demo_mouse_keepalive_interval(self) -> int | None:
        try:
            interval = int(self.demo_mouse_keepalive_interval_var.get())
        except (TypeError, ValueError):
            return None
        if not MIN_DEMO_MOUSE_KEEPALIVE_SECONDS <= interval <= MAX_DEMO_MOUSE_KEEPALIVE_SECONDS:
            return None
        return interval

    def _on_demo_mouse_keepalive_toggle(self) -> None:
        if not self.demo_mouse_keepalive_var.get():
            self._cancel_demo_mouse_keepalive()
            self.demo_mouse_keepalive_status.set(
                "Movimento automático do cursor desligado; nenhum movimento será feito."
            )
            return
        if self.demo_mouse_keepalive_target is None or self.demo_mouse_keepalive_alternate is None:
            self.demo_mouse_keepalive_var.set(False)
            messagebox.showinfo(
                APP_NAME,
                "Calibre primeiro o ponto neutro. O movimento não envia cliques e só funciona durante DEMO ativo.",
                parent=self,
            )
            return
        if self._demo_mouse_keepalive_interval() is None:
            self.demo_mouse_keepalive_var.set(False)
            messagebox.showerror(
                APP_NAME,
                f"O intervalo ocioso deve estar entre {MIN_DEMO_MOUSE_KEEPALIVE_SECONDS} e "
                f"{MAX_DEMO_MOUSE_KEEPALIVE_SECONDS} segundos.",
                parent=self,
            )
            return
        if self.demo_automation_enabled:
            self.demo_mouse_keepalive_last_move_at = time.monotonic()
            self._schedule_demo_mouse_keepalive()
            self.demo_mouse_keepalive_status.set(
                "Movimento DEMO sem clique habilitado; aguardando inatividade do usuário."
            )
        else:
            self.demo_mouse_keepalive_status.set(
                "Ativado; só movimentará o cursor durante uma ativação DEMO autorizada."
            )

    def _schedule_demo_mouse_keepalive(self) -> None:
        if (
            self.demo_mouse_keepalive_after_id is None
            and self.running
            and self.demo_automation_enabled
            and self.demo_account_confirmed
            and self.demo_mouse_keepalive_var.get()
        ):
            self.demo_mouse_keepalive_after_id = self.after(
                DEMO_MOUSE_KEEPALIVE_POLL_MS, self._demo_mouse_keepalive_tick
            )

    def _cancel_demo_mouse_keepalive(self) -> None:
        if self.demo_mouse_keepalive_after_id is not None:
            try:
                self.after_cancel(self.demo_mouse_keepalive_after_id)
            except tk.TclError:
                pass
            self.demo_mouse_keepalive_after_id = None

    def _demo_mouse_keepalive_tick(self) -> None:
        self.demo_mouse_keepalive_after_id = None
        if (
            not self.running
            or not self.demo_automation_enabled
            or not self.demo_account_confirmed
            or not self.demo_mouse_keepalive_var.get()
        ):
            return
        interval = self._demo_mouse_keepalive_interval()
        target = (
            self.demo_mouse_keepalive_alternate
            if self.demo_mouse_keepalive_use_alternate
            else self.demo_mouse_keepalive_target
        )
        neutral_target = self.demo_mouse_keepalive_target
        alternate = self.demo_mouse_keepalive_alternate
        safe_window = self.demo_mouse_keepalive_window
        if (
            interval is None
            or target is None
            or neutral_target is None
            or alternate is None
            or safe_window is None
        ):
            self.demo_mouse_keepalive_status.set("Movimento suspenso: calibre o ponto e confira o intervalo.")
            self._schedule_demo_mouse_keepalive()
            return
        now = time.monotonic()
        try:
            idle_seconds = windows_last_input_idle_seconds()
            if (
                idle_seconds >= interval
                and now - self.demo_mouse_keepalive_last_move_at >= interval
            ):
                if not self._demo_mouse_keepalive_geometry_is_safe(
                    neutral_target, alternate, safe_window
                ):
                    self.demo_mouse_keepalive_status.set(
                        "Movimento suspenso: ponto neutro coberto ou fora da janela calibrada."
                    )
                else:
                    if windows_window_at_point(target.x, target.y) != safe_window:
                        self.demo_mouse_keepalive_status.set(
                            "Movimento suspenso: a janela calibrada da corretora não está visível no ponto neutro."
                        )
                    else:
                        cursor_x, cursor_y = windows_mouse_position()
                        if (cursor_x, cursor_y) == (target.x, target.y):
                            target = neutral_target if target == alternate else alternate
                        if windows_window_at_point(target.x, target.y) != safe_window:
                            self.demo_mouse_keepalive_status.set(
                                "Movimento suspenso: ponto neutro não está na janela calibrada."
                            )
                            self._schedule_demo_mouse_keepalive()
                            return
                        windows_mouse_move(target.x, target.y)
                        self.demo_mouse_keepalive_use_alternate = (
                            target == self.demo_mouse_keepalive_target
                        )
                        self.demo_mouse_keepalive_last_move_at = now
                        self.demo_mouse_keepalive_status.set(
                            f"Cursor movido sem clique às {time.strftime('%H:%M:%S')}; "
                            f"próxima verificação em {interval} s de inatividade."
                        )
            elif idle_seconds < interval:
                self.demo_mouse_keepalive_status.set(
                    f"Movimento DEMO sem clique aguardando {interval} s de inatividade do usuário."
                )
        except Exception as exc:
            self.demo_mouse_keepalive_status.set(f"Movimento DEMO suspenso por erro: {exc}")
        self._schedule_demo_mouse_keepalive()

    def _update_demo_toggle_text(self) -> None:
        text = "Parar cliques DEMO" if self.demo_automation_enabled else "Ativar cliques DEMO…"
        config_state = "disabled" if self.demo_automation_enabled else "normal"
        for name in ("demo_toggle_button", "compact_demo_toggle_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.configure(text=text)
        for name in ("demo_timeout_spinbox", "demo_entry_deadline_spinbox"):
            spinbox = getattr(self, name, None)
            if spinbox is not None:
                spinbox.configure(state=config_state)

    def _toggle_demo_automation(self) -> None:
        if self.demo_automation_enabled:
            self._deactivate_demo_automation()
            if self.simulation.pending is not None:
                self._cancel_pending_simulation()
            self.demo_status.set("Cliques DEMO desligados pelo usuário; nenhum sinal pendente será executado.")
            return
        if sys.platform != "win32":
            messagebox.showerror(APP_NAME, "A automação do mouse só funciona no Windows.", parent=self)
            return
        if not self.running or self.detector is None:
            messagebox.showinfo(APP_NAME, "Inicie a captura com OCR ativo antes de habilitar cliques DEMO.", parent=self)
            return
        if self.timeframe_var.get() != "M1":
            messagebox.showinfo(APP_NAME, "A automação contínua de clique DEMO está limitada ao período M1.", parent=self)
            return
        try:
            activation_timeout = int(self.demo_activation_timeout_var.get())
        except (TypeError, ValueError):
            messagebox.showerror(APP_NAME, "Informe o limite da ativação DEMO em segundos.", parent=self)
            return
        if not MIN_DEMO_ACTIVATION_TIMEOUT_SECONDS <= activation_timeout <= MAX_DEMO_ACTIVATION_TIMEOUT_SECONDS:
            messagebox.showerror(
                APP_NAME,
                f"O limite precisa estar entre {MIN_DEMO_ACTIVATION_TIMEOUT_SECONDS} e "
                f"{MAX_DEMO_ACTIVATION_TIMEOUT_SECONDS} segundos.",
                parent=self,
            )
            return
        try:
            entry_deadline = int(self.demo_entry_deadline_var.get())
        except (TypeError, ValueError):
            messagebox.showerror(APP_NAME, "Informe o prazo do clique após o sinal em segundos.", parent=self)
            return
        if not MIN_DEMO_ENTRY_DEADLINE_SECONDS <= entry_deadline <= MAX_DEMO_ENTRY_DEADLINE_SECONDS:
            messagebox.showerror(
                APP_NAME,
                f"O prazo do clique precisa estar entre {MIN_DEMO_ENTRY_DEADLINE_SECONDS} e "
                f"{MAX_DEMO_ENTRY_DEADLINE_SECONDS} segundos.",
                parent=self,
            )
            return
        if self.simulation.pending is not None:
            messagebox.showinfo(APP_NAME, "Cancele o sinal pendente antes de habilitar cliques DEMO.", parent=self)
            return
        buy_target = self.demo_click_targets["BUY"]
        sell_target = self.demo_click_targets["SELL"]
        if (
            buy_target is None
            or sell_target is None
            or self.demo_click_target_windows["BUY"] is None
            or self.demo_click_target_windows["SELL"] is None
        ):
            messagebox.showinfo(
                APP_NAME,
                "Calibre novamente os botões COMPRAR e VENDER com a janela da plataforma visível.",
                parent=self,
            )
            return
        if (
            self.region is None
            or not self._target_is_excluded_or_outside_capture(buy_target)
            or not self._target_is_excluded_or_outside_capture(sell_target)
        ):
            messagebox.showerror(
                APP_NAME,
                "Cada botão calibrado precisa ficar fora da captura ou dentro de uma área que será ocultada "
                "antes do OCR e da gravação. Marque a área dos botões e confira que HORA ATUAL permanece visível.",
                parent=self,
            )
            return
        mouse_keepalive_note = ""
        if self.demo_mouse_keepalive_var.get():
            interval = self._demo_mouse_keepalive_interval()
            target = self.demo_mouse_keepalive_target
            alternate = self.demo_mouse_keepalive_alternate
            safe_window = self.demo_mouse_keepalive_window
            if interval is None:
                messagebox.showerror(
                    APP_NAME,
                    f"O intervalo do movimento deve ficar entre {MIN_DEMO_MOUSE_KEEPALIVE_SECONDS} e "
                    f"{MAX_DEMO_MOUSE_KEEPALIVE_SECONDS} segundos.",
                    parent=self,
                )
                return
            if (
                target is None
                or alternate is None
                or safe_window is None
                or not self._demo_mouse_keepalive_geometry_is_safe(
                    target, alternate, safe_window, check_frontmost=False
                )
            ):
                messagebox.showerror(
                    APP_NAME,
                    "O movimento sem clique exige um ponto neutro calibrado na mesma janela dos botões, "
                    "longe dos alvos e fora da região capturada ou dentro de uma área mascarada.",
                    parent=self,
                )
                return
            mouse_keepalive_note = (
                f" Se não houver atividade do usuário por {interval} s, o cursor alternará entre "
                "dois pontos neutros calibrados, sem clicar; a posição mudará."
            )
        consent = messagebox.askyesno(
            APP_NAME,
            "ATENÇÃO — cliques automáticos somente em conta DEMO.\n\n"
            "Confirme que a plataforma está na conta DEMO e que valor/expiração foram conferidos. "
            "O app não consegue verificar o tipo de conta nem os valores.\n\n"
            "A ativação contínua pode enviar no máximo uma entrada por vela M1, somente até :30 do relógio "
            "do Windows convertido para UTC−3. Esse é um relógio local, não uma leitura da corretora; "
            "a sincronização do Windows pode divergir em segundos. "
            f"Cada sinal único tenta clicar imediatamente; o limite de {entry_deadline} s é medido por esse relógio "
            "entre o armamento e o clique, sem espera deliberada. "
            "Esse prazo não é uma espera antes da entrada. Não espera N+1. "
            f"Ficará ativa por {activation_timeout} s ou até você pará-la; sinais repetidos na mesma vela são bloqueados. "
            "A identidade da vela e a aceitação da ordem não são verificadas visualmente.\n\n"
            f"{mouse_keepalive_note}\n\n"
            "Se a conta não estiver em DEMO, o clique poderá enviar uma ordem real. Ativar agora?",
            parent=self,
        )
        if not consent:
            return
        self.demo_clock.reset()
        self.demo_automation_enabled = True
        self.demo_account_confirmed = True
        self.demo_activation_timeout_active = activation_timeout
        self.demo_entry_deadline_active = entry_deadline
        self.demo_entries_this_activation = 0
        self.demo_timeout_after_id = self.after(
            activation_timeout * 1000, self._expire_demo_activation
        )
        if self.demo_mouse_keepalive_var.get():
            self.demo_mouse_keepalive_last_move_at = time.monotonic()
            self.demo_mouse_keepalive_use_alternate = False
            self._schedule_demo_mouse_keepalive()
            self.demo_mouse_keepalive_status.set(
                "Keep-alive DEMO sem clique ativo; aguardando intervalo de inatividade."
            )
        self._persist_config()
        self._update_demo_toggle_text()
        self.demo_status.set(
            f"CLIQUE DEMO CONTÍNUO ATIVO por {activation_timeout} s: no máximo uma entrada por vela M1; "
            f"cada clique exige sinal único, limite de {self.demo_entry_deadline_active:.0f} s e relógio Windows UTC−3 ≤:30. "
            "A sincronização do Windows pode divergir em segundos da corretora."
        )

    def _maybe_auto_arm_demo_signal(self) -> None:
        if (
            not self.demo_automation_enabled
            or not self.running
            or self.detector is None
            or self.timeframe_var.get() != "M1"
            or self.simulation.pending is not None
        ):
            return
        now = time.monotonic()
        if self.last_ocr_at <= 0 or now - self.last_ocr_at > TIMER_MAX_AGE_SECONDS:
            self.demo_status.set(
                "DEMO aguardando sinal/quadro OCR recente; o relógio UTC−3 do Windows "
                "não substitui a validação de atualidade do sinal. Nenhum clique será feito."
            )
            return
        clock = self.demo_clock.reading()
        current_candle_id = self.demo_minute_tracker.update(clock)
        if current_candle_id is None:
            return
        candidates = list(self.candidates_by_id.values())
        if len(candidates) != 1:
            if len(candidates) > 1:
                self.demo_status.set("DEMO contínuo pausado nesta leitura: há mais de um candidato OCR.")
            return
        candidate = candidates[0]
        if self.last_demo_entry_candle_id == current_candle_id:
            self.demo_signal_guard.mark_consumed(
                candidate.direction, candidate.left, candidate.top
            )
            self.demo_status.set(
                f"DEMO ativo: já houve uma entrada na vela {clock.hour:02d}:{clock.minute:02d}; "
                "aguardando a próxima vela M1."
            )
            return
        if not m1_entry_window_open(clock, max_elapsed_seconds=30):
            self.demo_signal_guard.mark_consumed(
                candidate.direction, candidate.left, candidate.top
            )
            self.demo_status.set(
                f"DEMO ativo: relógio Windows UTC−3 {clock.hour:02d}:{clock.minute:02d}:{clock.second:02d} passou de :30; "
                "este sinal foi descartado sem clique, aguardando um próximo sinal elegível."
            )
            return
        if self.demo_signal_guard.blocks(candidate):
            self.demo_status.set(
                "DEMO ativo: este sinal já foi consumido; aguardando outro sinal. "
                "A trava por sinal evita reentradas."
            )
            return
        try:
            pending = self.simulation.arm(candidate, dedupe_scope=str(current_candle_id))
        except ValueError:
            return
        self.pending_armed_clock = clock
        self.pending_rollover_notified = False
        label = "COMPRA" if pending.direction == "BUY" else "VENDER"
        error = self._record_simulation_event(
            "sinal_armado_demo", direction=pending.direction, observed_text=pending.observed_text,
            confidence=pending.confidence, signal_x=pending.x, signal_y=pending.y,
            clock_override=clock, clock_source_override=DEMO_CLOCK_SOURCE,
            armed_clock_override=clock,
        )
        persistence_note = f" Histórico não gravado: {error}" if error else ""
        self.demo_status.set(
            f"DEMO: {label} armado automaticamente ({pending.confidence:.0f}%). Tentativa imediata; limite de "
            f"{self.demo_entry_deadline_active:.0f} s pelo relógio UTC−3 do Windows. "
            f"No máximo uma entrada nesta vela M1.{persistence_note}"
        )
        self._refresh_simulation_buttons()
        self._execute_demo_click()

    def _target_window_is_topmost(self, direction: str, target: ClickTarget) -> bool:
        calibrated_window = self.demo_click_target_windows.get(direction)
        if calibrated_window is None:
            return False
        try:
            current_window = windows_window_at_point(target.x, target.y)
        except Exception:
            return False
        return current_window == calibrated_window

    def _execute_demo_click(self) -> None:
        pending = self.simulation.pending
        if not self.demo_automation_enabled or pending is None:
            return
        now = time.monotonic()
        if self.last_ocr_at <= 0 or now - self.last_ocr_at > TIMER_MAX_AGE_SECONDS:
            self._deactivate_demo_automation()
            self._cancel_pending_simulation()
            self.demo_status.set(
                "DEMO pausado: quadro/sinal OCR desatualizado; nenhum clique foi tentado."
            )
            return
        target = self.demo_click_targets[pending.direction]
        if (
            target is None
            or not self._target_is_excluded_or_outside_capture(target)
            or not self._target_window_is_topmost(pending.direction, target)
        ):
            self._deactivate_demo_automation()
            self.demo_status.set(
                "DEMO bloqueado: o ponto do botão não está sobre a mesma janela calibrada. "
                "Traga a corretora para frente e recalibre os botões."
            )
            self._cancel_pending_simulation()
            return
        if self.last_ocr_at <= 0 or time.monotonic() - self.last_ocr_at > TIMER_MAX_AGE_SECONDS:
            self._deactivate_demo_automation()
            self._cancel_pending_simulation()
            self.demo_status.set(
                "DEMO pausado: quadro/sinal OCR ficou desatualizado antes do clique; nenhum clique foi tentado."
            )
            return
        clock = self.demo_clock.reading()
        elapsed = platform_clock_elapsed_seconds(self.pending_armed_clock, clock)
        if elapsed is None or elapsed > self.demo_entry_deadline_active:
            self.demo_signal_guard.mark_consumed(pending.direction, pending.x, pending.y)
            self._cancel_pending_simulation()
            if elapsed is None:
                reason = "o relógio UTC−3 do Windows avançou de forma inválida desde o armamento"
            else:
                reason = (
                    f"passaram {elapsed} s desde o armamento, acima do limite de "
                    f"{self.demo_entry_deadline_active:.0f} s do relógio UTC−3 do Windows"
                )
            self.demo_status.set(
                f"Sinal descartado: {reason}; nenhum clique. "
                "Modo contínuo segue aguardando outro sinal."
            )
            return
        if not m1_entry_window_open(clock, max_elapsed_seconds=30):
            self.demo_signal_guard.mark_consumed(pending.direction, pending.x, pending.y)
            self._cancel_pending_simulation()
            self.demo_status.set(
                "Sinal descartado porque o relógio UTC−3 do Windows passou de :30; nenhum clique. "
                "Modo contínuo segue ativo para um sinal novo elegível."
            )
            return
        self.demo_entries_this_activation += 1
        self.last_demo_entry_candle_id = self.demo_minute_tracker.update(clock)
        try:
            click_demo_direction(
                pending.direction,
                buy_target=self.demo_click_targets["BUY"],
                sell_target=self.demo_click_targets["SELL"],
                enabled=self.demo_automation_enabled,
                demo_confirmed=self.demo_account_confirmed,
                clicker=windows_mouse_click,
            )
            entry = self.simulation.confirm_next_candle()
        except Exception as exc:
            # A falha pode ter ocorrido depois de o sistema operacional enviar o clique;
            # nunca repetir ou seguir clicando após um resultado incerto.
            if self.simulation.pending is not None:
                try:
                    failed = self.simulation.cancel_pending()
                    self.demo_signal_guard.mark_consumed(failed.direction, failed.x, failed.y)
                    self._record_simulation_event(
                        "clique_demo_inconclusivo", direction=failed.direction,
                        observed_text=failed.observed_text, confidence=failed.confidence,
                        signal_x=failed.x, signal_y=failed.y,
                        clock_override=self.demo_clock.reading(),
                        clock_source_override=DEMO_CLOCK_SOURCE,
                    )
                except ValueError:
                    pass
            self._clear_pending_clock_observation()
            self._deactivate_demo_automation()
            self.demo_status.set(
                f"Resultado do clique DEMO incerto ({exc}); automação encerrada para evitar repetição. "
                "Verifique a plataforma antes de reativar."
            )
            self._refresh_simulation_buttons()
            return

        label = "COMPRA" if entry.direction == "BUY" else "VENDER"
        time_text = f"{clock.hour:02d}:{clock.minute:02d}:{clock.second:02d}"
        armed_clock = self.pending_armed_clock
        armed_time_text = (
            f"{armed_clock.hour:02d}:{armed_clock.minute:02d}:{armed_clock.second:02d}"
            if armed_clock is not None else "—"
        )
        log_error = self._record_simulation_event(
            "entrada_demo_clicada", direction=entry.direction, observed_text=entry.signal_text,
            confidence=entry.confidence, signal_x=entry.signal_x, signal_y=entry.signal_y,
            clock_override=clock, clock_source_override=DEMO_CLOCK_SOURCE,
            armed_clock_override=armed_clock, entry_delay_seconds=elapsed,
        )
        self.history_table.insert(
            "", 0, iid=f"demo-{entry.signal_id}",
            values=(time_text, label, f"DEMO · atraso relógio Windows UTC−3 {elapsed} s"),
        )
        self.demo_signal_guard.mark_consumed(
            entry.direction, entry.signal_x, entry.signal_y
        )
        self._clear_pending_clock_observation()
        persistence_note = f" Histórico local não gravado: {log_error}" if log_error else ""
        self.demo_status.set(
            f"Clique {label} enviado às {time_text} (relógio Windows UTC−3); "
            f"atraso medido por essa fonte: {elapsed} s "
            f"desde o armamento às {armed_time_text}. Uma entrada nesta vela M1; "
            "o mesmo sinal fica bloqueado. "
            f"Prazo restante da ativação: até {self.demo_activation_timeout_active} s.{persistence_note}"
        )
        self.simulation_status.set(
            "Tentativa DEMO registrada; identidade da vela e aceitação pela plataforma não verificadas. "
            f"Entradas nesta ativação: {self.demo_entries_this_activation}."
        )
        self._refresh_simulation_buttons()

    def _expire_demo_activation(self) -> None:
        self.demo_timeout_after_id = None
        if not self.demo_automation_enabled:
            return
        timeout = self.demo_activation_timeout_active
        entries = self.demo_entries_this_activation
        self._deactivate_demo_automation()
        if self.simulation.pending is not None:
            self._cancel_pending_simulation()
        self.demo_status.set(
            f"Ativação DEMO encerrada pelo limite de {timeout} s; {entries} entrada(s) tentada(s)."
        )

    def _deactivate_demo_automation(self) -> None:
        self._cancel_demo_mouse_keepalive()
        self.demo_automation_enabled = False
        self.demo_account_confirmed = False
        if self.demo_mouse_keepalive_var.get():
            self.demo_mouse_keepalive_status.set(
                "Keep-alive sem clique parado porque a ativação DEMO terminou."
            )
        if self.demo_timeout_after_id is not None:
            try:
                self.after_cancel(self.demo_timeout_after_id)
            except tk.TclError:
                pass
            self.demo_timeout_after_id = None
        self._update_demo_toggle_text()

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
            self.ocr_status.set("OCR desligado; nenhuma operação é executada.")
        self.last_candidates = []
        self.last_ocr_at = 0.0
        self.latest_platform_clock = None
        self.latest_clock_at = None
        self.latest_bar_count = 0
        self._update_timer_status()
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
        self._stop_sequence_recording("captura parada")
        self._set_capture_keep_awake(False)
        if self.demo_automation_enabled:
            self._toggle_demo_automation()
        self.running = False
        self.start_button.configure(text="Iniciar visualização")
        self.capture_status.set(reason)
        self.heartbeat_status.set("Sem captura")
        self._exit_compact_mode()

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
                    self._observe_pending_platform_minute()
                    bars = detect_candle_bars(image)
                    self.latest_bar_count = len(bars)
                    self.last_candidates = filter_to_recent_candle(raw_candidates, bars)
                    self.demo_signal_guard.observe(self.last_candidates)
                    self.last_ocr_at = now
                    self._update_ocr_status(self.last_candidates, len(raw_candidates), len(bars))
                    self._maybe_auto_arm_demo_signal()
                    # OCR may be slower than one frame; assess freshness after processing,
                    # not against the frame-start timestamp captured before the OCR work.
                    self._update_timer_status()
                except Exception as exc:
                    # Falha do OCR encerra também qualquer modo que poderia clicar.
                    if self.demo_automation_enabled:
                        self._toggle_demo_automation()
                    self.detector = None
                    self.latest_platform_clock = None
                    self.latest_clock_at = None
                    self.ocr_status.set(f"OCR interrompido por erro: {exc}")
                    self._update_timer_status()
                    self._stop_sequence_recording("parada por falha de OCR")
            self._update_sequence_recording(image, now)
            self._show_preview(image)
            self.capture_status.set(f"Captura ativa · {image.width}×{image.height} px · 2 quadros/s")
        except Exception as exc:
            self._stop_capture(f"Erro de captura: {exc}")
            if self.state() == "iconic":
                self.deiconify()
            messagebox.showerror(APP_NAME, f"A captura foi interrompida:\n{exc}", parent=self)
            return
        self.after(POLL_MS, self._capture_tick)

    def _set_sequence_button_text(self, recording: bool) -> None:
        text = "Parar gravação de teste" if recording else "Gravar sequência de teste (75 s)"
        for button_name in ("sequence_button", "compact_sequence_button"):
            button = getattr(self, button_name, None)
            if button is not None:
                button.configure(text=text)

    def _toggle_sequence_recording(self) -> None:
        if self.sequence_recorder.active:
            self._stop_sequence_recording("parada manual")
            return
        if not self.running:
            messagebox.showinfo(APP_NAME, "Inicie a visualização antes de gravar uma sequência.", parent=self)
            return
        if self.timeframe_var.get() != "M1":
            messagebox.showinfo(APP_NAME, "A gravação de validação desta etapa é para o período M1.", parent=self)
            return
        if self.detector is None:
            messagebox.showinfo(
                APP_NAME, "Ative o OCR e inicie a visualização para registrar também HORA ATUAL.", parent=self
            )
            return
        consent = messagebox.askyesno(
            APP_NAME,
            "Gravar por até 75 segundos as imagens da região selecionada e metadados OCR, somente neste PC?\n\n"
            "Confira que o recorte mostra o gráfico e HORA ATUAL, sem dados pessoais ou informações da conta. "
            "Os arquivos não serão enviados pela aplicação.",
            parent=self,
        )
        if not consent:
            return
        try:
            output_dir = self.sequence_recorder.start(time.monotonic())
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível iniciar a gravação:\n{exc}", parent=self)
            return
        self._set_sequence_button_text(True)
        self.sequence_status.set(f"Gravando até 75 s · arquivos locais em {output_dir}")

    def _stop_sequence_recording(self, reason: str) -> None:
        if not self.sequence_recorder.active:
            return
        frame_count = self.sequence_recorder.frames_saved
        output_dir = self.sequence_recorder.stop()
        self._set_sequence_button_text(False)
        self.sequence_status.set(
            f"Sequência encerrada ({reason}): {frame_count} imagem(ns) · {output_dir}"
        )

    def _update_sequence_recording(self, image: Image.Image, now: float) -> None:
        recorder = self.sequence_recorder
        if not recorder.active:
            return
        clock = self.latest_platform_clock
        clock_is_fresh = (
            clock is not None
            and self.latest_clock_at is not None
            and now - self.latest_clock_at <= TIMER_MAX_AGE_SECONDS
        )
        clock_text = (
            f"{clock.hour:02d}:{clock.minute:02d}:{clock.second:02d}" if clock_is_fresh else ""
        )
        clock_confidence = clock.confidence if clock_is_fresh else None
        candidate_labels = [
            f"{'COMPRA' if item.direction == 'BUY' else 'VENDER'} "
            f"{item.confidence:.0f}%@{item.left},{item.top}"
            for item in self.last_candidates
        ]
        output_dir = recorder.output_dir
        try:
            recorder.record_frame(
                image,
                now,
                platform_clock=clock_text,
                clock_confidence=clock_confidence,
                clock_ocr_excerpt=(self.detector.last_clock_ocr_text if self.detector is not None else ""),
                candle_count=self.latest_bar_count,
                candidates=candidate_labels,
            )
        except (OSError, ValueError) as exc:
            self._stop_sequence_recording("erro ao salvar")
            self.sequence_status.set(f"Gravação interrompida por erro: {exc} · {output_dir}")
            return

        if not recorder.active:
            frame_count = recorder.frames_saved
            self._set_sequence_button_text(False)
            self.sequence_status.set(
                f"Sequência concluída: {frame_count} imagem(ns) · {output_dir}"
            )
            return
        self.sequence_status.set(
            f"Gravando {recorder.frames_saved} imagem(ns); "
            f"{max(0, int(recorder.duration_seconds - recorder.elapsed_seconds))} s restantes · {output_dir}"
        )

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

    def _export_entry_history(self) -> None:
        destination = filedialog.asksaveasfilename(
            parent=self,
            title="Salvar todas as entradas",
            defaultextension=".csv",
            initialfile="auto_trader_iq_entries.csv",
            filetypes=(("CSV", "*.csv"), ("Todos os arquivos", "*.*")),
        )
        if not destination:
            return
        try:
            count = self.simulation_history.export_entries_csv(Path(destination))
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível exportar as entradas:\n{exc}", parent=self)
            return
        messagebox.showinfo(
            APP_NAME,
            f"{count} entrada(s) exportada(s) para:\n{destination}",
            parent=self,
        )

    def _clear_entry_history(self) -> None:
        if self.demo_automation_enabled:
            messagebox.showinfo(
                APP_NAME, "Pare os cliques DEMO antes de limpar o log.", parent=self
            )
            return
        if not messagebox.askyesno(
            APP_NAME,
            "Isso apagará permanentemente o CSV local com entradas e eventos. "
            "Use ‘Salvar todas as entradas’ antes, se quiser manter uma cópia. Continuar?",
            parent=self,
        ):
            return
        try:
            self.simulation_history.clear()
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Não foi possível apagar o log:\n{exc}", parent=self)
            return
        for item_id in self.history_table.get_children():
            self.history_table.delete(item_id)
        self.simulation_status.set(
            "Log local apagado. As travas de segurança contra sinal repetido continuam ativas."
        )

    def _load_persisted_simulation_history(self) -> None:
        try:
            rows = self.simulation_history.load_recent_entries(limit=20)
        except (OSError, UnicodeError, csv.Error, ValueError) as exc:
            self.simulation_status.set(
                f"Histórico local indisponível; simulação continua sem persistência: {exc}"
            )
            return
        for index, row in enumerate(rows):
            direction = "COMPRA" if row.get("direction") == "BUY" else "VENDER"
            elapsed = row.get("elapsed_seconds_m1", "")
            elapsed_text = f" · M1 +{elapsed}s" if elapsed else ""
            if row.get("event") == "entrada_demo_clicada":
                delay = row.get("entry_delay_seconds", "") or row.get(
                    "entry_delay_platform_seconds", ""
                )
                armed_clock = row.get("armed_clock", "") or row.get(
                    "armed_platform_clock", ""
                )
                if delay:
                    arm_note = f" desde {armed_clock}" if armed_clock else " desde armamento"
                    source = (
                        "relógio Windows UTC−3"
                        if row.get("clock_source") == DEMO_CLOCK_SOURCE
                        else "HORA ATUAL OCR"
                    )
                    row_status = f"DEMO · atraso {source} {delay}s{arm_note}"
                else:
                    row_status = "DEMO · clique enviado; atraso não registrado"
            else:
                row_status = f"SIMULADA · N+1{elapsed_text}"
            self.history_table.insert(
                "", 0, iid=f"persisted-{index}",
                values=(row.get("platform_clock") or "—", direction, row_status),
            )
        if rows:
            self.simulation_status.set(
                f"Histórico local carregado: {len(rows)} entrada(s) simulada(s) recente(s). "
                "Nenhuma ordem real é enviada."
            )

    def _record_simulation_event(
        self,
        event: str,
        *,
        direction: str,
        observed_text: str,
        confidence: float,
        signal_x: int,
        signal_y: int,
        elapsed_seconds_m1: int | None = None,
        armed_platform_clock: PlatformClockReading | None = None,
        entry_delay_platform_seconds: int | None = None,
        clock_override: PlatformClockReading | None = None,
        clock_source_override: str | None = None,
        armed_clock_override: PlatformClockReading | None = None,
        entry_delay_seconds: int | None = None,
    ) -> str | None:
        now = time.monotonic()
        clock_is_fresh = (
            self.latest_platform_clock is not None
            and self.latest_clock_at is not None
            and now - self.latest_clock_at <= TIMER_MAX_AGE_SECONDS
        )
        clock = clock_override or (self.latest_platform_clock if clock_is_fresh else None)
        clock_source = (
            clock_source_override
            if clock_override is not None
            else ("platform_ocr" if clock is not None else "")
        )
        # Persistência é best-effort: nunca deve bloquear confirmação assistida.
        return append_event_best_effort(
            self.simulation_history,
            platform_clock=(
                f"{clock.hour:02d}:{clock.minute:02d}:{clock.second:02d}" if clock else ""
            ),
            event=event,
            timeframe=self.timeframe_var.get(),
            direction=direction,
            observed_text=observed_text,
            ocr_confidence=confidence,
            signal_x=signal_x,
            signal_y=signal_y,
            elapsed_seconds_m1=elapsed_seconds_m1,
            clock_confidence=(
                clock.confidence
                if clock is not None and clock_source != DEMO_CLOCK_SOURCE else None
            ),
            armed_platform_clock=(
                f"{armed_platform_clock.hour:02d}:{armed_platform_clock.minute:02d}:"
                f"{armed_platform_clock.second:02d}"
                if armed_platform_clock is not None else ""
            ),
            entry_delay_platform_seconds=entry_delay_platform_seconds,
            clock_source=clock_source,
            armed_clock=(
                f"{armed_clock_override.hour:02d}:{armed_clock_override.minute:02d}:"
                f"{armed_clock_override.second:02d}"
                if armed_clock_override is not None else ""
            ),
            entry_delay_seconds=entry_delay_seconds,
        )

    def _arm_selected_candidate(self) -> None:
        selection = self.candidate_table.selection()
        if not selection:
            self.simulation_status.set("Selecione um candidato OCR e confira a caixa sobre a etiqueta no gráfico.")
            return
        self._arm_candidate_id(selection[0])

    def _arm_compact_candidate(self) -> None:
        selection = self.compact_candidate_table.selection()
        if not selection:
            self.simulation_status.set("Selecione uma etiqueta visível no gráfico.")
            return
        self._arm_candidate_id(selection[0])

    def _arm_candidate_id(self, item_id: str) -> None:
        if self.demo_automation_enabled:
            self.simulation_status.set("No modo DEMO, os candidatos são armados automaticamente; use Cancelar para abortar.")
            return
        candidate = self.candidates_by_id.get(item_id)
        if candidate is None:
            self.simulation_status.set("O candidato não está mais no quadro atual; aguarde a próxima leitura.")
            return
        if self.timeframe_var.get() == "M1" and (
            self.latest_platform_clock is None
            or self.latest_clock_at is None
            or time.monotonic() - self.latest_clock_at > TIMER_MAX_AGE_SECONDS
        ):
            self.simulation_status.set("Não foi possível armar: HORA ATUAL da plataforma está ausente ou desatualizada.")
            return
        try:
            pending = self.simulation.arm(candidate)
        except ValueError as exc:
            self.simulation_status.set(str(exc))
            return
        self.pending_armed_clock = (
            self.latest_platform_clock
            if self.latest_clock_at is not None
            and time.monotonic() - self.latest_clock_at <= TIMER_MAX_AGE_SECONDS
            else None
        )
        self.pending_rollover_notified = False
        label = "COMPRA" if pending.direction == "BUY" else "VENDER"
        log_error = self._record_simulation_event(
            "sinal_armado", direction=pending.direction, observed_text=pending.observed_text,
            confidence=pending.confidence, signal_x=pending.x, signal_y=pending.y,
        )
        persistence_note = f" Histórico local não gravado: {log_error}" if log_error else ""
        self.simulation_status.set(
            f"Pendente: {label} ({pending.confidence:.0f}%). Aguarde a próxima vela nascer; "
            "confirme manualmente apenas quando isso estiver visível. Nenhuma ordem será enviada."
            f"{persistence_note}"
        )
        self._refresh_simulation_buttons()

    def _observe_pending_platform_minute(self) -> None:
        if (
            self.timeframe_var.get() != "M1"
            or self.demo_automation_enabled
            or self.simulation.pending is None
            or self.pending_rollover_notified
            or not platform_minute_advanced(self.pending_armed_clock, self.latest_platform_clock)
        ):
            return
        self.pending_rollover_notified = True
        clock = self.latest_platform_clock
        assert clock is not None
        pending = self.simulation.pending
        label = "COMPRA" if pending.direction == "BUY" else "VENDER"
        log_error = self._record_simulation_event(
            "virada_minuto_observada", direction=pending.direction,
            observed_text=pending.observed_text, confidence=pending.confidence,
            signal_x=pending.x, signal_y=pending.y,
        )
        persistence_note = f" Histórico local não gravado: {log_error}" if log_error else ""
        rollover_note = "Confira visualmente se N+1 nasceu; a confirmação manual continua necessária."
        self.simulation_status.set(
            f"HORA ATUAL avançou para {clock.hour:02d}:{clock.minute:02d} após armar {label}. "
            f"{rollover_note}{persistence_note}"
        )

    def _clear_pending_clock_observation(self) -> None:
        self.pending_armed_clock = None
        self.pending_rollover_notified = False

    def _confirm_next_candle(self) -> None:
        elapsed_seconds = None
        if self.timeframe_var.get() == "M1":
            if not self._m1_window_valid():
                self.simulation_status.set(
                    "Entrada M1 bloqueada: aguarde HORA ATUAL avançar exatamente um minuto e confirme até +30 s."
                )
                self._refresh_simulation_buttons()
                return
            assert self.latest_platform_clock is not None
            elapsed_seconds = self.latest_platform_clock.elapsed_seconds_in_m1
        try:
            entry = self.simulation.confirm_next_candle(elapsed_seconds_after_open=elapsed_seconds)
        except ValueError as exc:
            self.simulation_status.set(str(exc))
            return
        self._clear_pending_clock_observation()
        label = "COMPRA" if entry.direction == "BUY" else "VENDER"
        clock_is_fresh = (
            self.latest_platform_clock is not None
            and self.latest_clock_at is not None
            and time.monotonic() - self.latest_clock_at <= TIMER_MAX_AGE_SECONDS
        )
        if clock_is_fresh:
            clock = self.latest_platform_clock
            assert clock is not None
            confirmed = f"{clock.hour:02d}:{clock.minute:02d}:{clock.second:02d}"
            clock_source = "HORA ATUAL"
        else:
            confirmed = entry.next_candle_confirmed_at.astimezone().strftime("%H:%M:%S")
            clock_source = "relógio do PC"
        elapsed_text = (
            f" · M1 +{entry.elapsed_seconds_after_open}s"
            if entry.elapsed_seconds_after_open is not None else ""
        )
        log_error = self._record_simulation_event(
            "entrada_simulada", direction=entry.direction, observed_text=entry.signal_text,
            confidence=entry.confidence, signal_x=entry.signal_x, signal_y=entry.signal_y,
            elapsed_seconds_m1=entry.elapsed_seconds_after_open,
        )
        persistence_note = (
            f" A entrada continua simulada, mas não foi salva no histórico local: {log_error}"
            if log_error else ""
        )
        self.history_table.insert(
            "", 0, iid=entry.signal_id,
            values=(confirmed, label, f"SIMULADA · N+1{elapsed_text}"),
        )
        self.simulation_status.set(
            f"ENTRADA SIMULADA: {label} às {confirmed} ({clock_source}); "
            f"N+1 confirmada manualmente{elapsed_text}. "
            f"Histórico desta sessão: {len(self.simulation.entries)} entrada(s).{persistence_note}"
        )
        for button in (self.confirm_candle_button, self.compact_confirm_button):
            button.configure(state="disabled")
        for button in (self.cancel_sim_button, self.compact_cancel_button):
            button.configure(state="disabled")

    def _cancel_pending_simulation(self) -> None:
        try:
            pending = self.simulation.cancel_pending()
        except ValueError as exc:
            self.simulation_status.set(str(exc))
            return
        self._clear_pending_clock_observation()
        log_error = self._record_simulation_event(
            "simulacao_cancelada", direction=pending.direction,
            observed_text=pending.observed_text, confidence=pending.confidence,
            signal_x=pending.x, signal_y=pending.y,
        )
        persistence_note = f" Histórico local não gravado: {log_error}" if log_error else ""
        self.simulation_status.set(
            f"Simulação pendente cancelada ({pending.observed_text}); o mesmo rótulo não será rearmado nesta sessão."
            f"{persistence_note}"
        )
        for button in (self.confirm_candle_button, self.compact_confirm_button):
            button.configure(state="disabled")
        for button in (self.cancel_sim_button, self.compact_cancel_button):
            button.configure(state="disabled")

    def _m1_window_valid(self) -> bool:
        if (
            self.latest_platform_clock is None
            or self.latest_clock_at is None
            or self.pending_armed_clock is None
        ):
            return False
        if time.monotonic() - self.latest_clock_at > TIMER_MAX_AGE_SECONDS:
            return False
        return m1_next_candle_entry_window_open(
            self.pending_armed_clock, self.latest_platform_clock, max_elapsed_seconds=30
        )

    def _refresh_simulation_buttons(self) -> None:
        pending = self.simulation.pending is not None
        confirm_allowed = pending and not self.demo_automation_enabled and (
            self.timeframe_var.get() != "M1" or self._m1_window_valid()
        )
        for button in (self.confirm_candle_button, self.compact_confirm_button):
            button.configure(state="normal" if confirm_allowed else "disabled")
        for button in (self.cancel_sim_button, self.compact_cancel_button):
            button.configure(state="normal" if pending else "disabled")

    def _update_timer_status(self, now: float | None = None) -> None:
        if self.timeframe_var.get() != "M1":
            self.timer_status.set(
                f"{self.timeframe_var.get()}: limite temporal de entrada ainda não configurado; "
                "confirmação manual."
            )
            self._refresh_simulation_buttons()
            return
        observed_at = time.monotonic() if now is None else now
        if self.demo_automation_enabled:
            frame_fresh = (
                self.last_ocr_at > 0
                and observed_at - self.last_ocr_at <= TIMER_MAX_AGE_SECONDS
            )
            if not frame_fresh:
                self.timer_status.set(
                    "M1 DEMO: quadro/sinal OCR ausente ou desatualizado; clique bloqueado."
                )
            else:
                demo_clock = self.demo_clock.reading()
                pending = self.simulation.pending
                prefix = "M1 DEMO · relógio do Windows em UTC−3 (segundos podem divergir da corretora)"
                if pending is not None:
                    elapsed = platform_clock_elapsed_seconds(self.pending_armed_clock, demo_clock)
                    self.timer_status.set(
                        f"{prefix}: {demo_clock.hour:02d}:{demo_clock.minute:02d}:"
                        f"{demo_clock.second:02d}; armamento +{elapsed if elapsed is not None else '—'} s; "
                        "janela até :30."
                    )
                else:
                    self.timer_status.set(
                        f"{prefix}: {demo_clock.hour:02d}:{demo_clock.minute:02d}:"
                        f"{demo_clock.second:02d}; no máximo uma entrada por vela, até :30."
                    )
            self._refresh_simulation_buttons()
            return

        platform_clock = self.latest_platform_clock
        fresh = (
            self.latest_clock_at is not None
            and observed_at - self.latest_clock_at <= TIMER_MAX_AGE_SECONDS
        )
        if platform_clock is None or not fresh:
            self.timer_status.set("M1: HORA ATUAL ausente/desatualizada; confirmação e clique bloqueados.")
            self._refresh_simulation_buttons()
            return

        elapsed = platform_clock.elapsed_seconds_in_m1
        pending = self.simulation.pending
        offset = (
            platform_minute_offset(self.pending_armed_clock, platform_clock)
            if pending is not None else None
        )
        expire_reason: str | None = None
        if pending is not None and offset is None:
            self.timer_status.set("M1: pendente sem relógio de armamento; não será confirmado.")
            expire_reason = "relógio do sinal ausente"
        elif pending is not None and offset == 0:
            self.timer_status.set(
                f"M1: sinal armado em {platform_clock.hour:02d}:{platform_clock.minute:02d}; "
                "aguardando a próxima virada. A janela ainda não começou."
            )
        elif pending is not None and offset == 1 and 0 <= elapsed <= 30:
            self.timer_status.set(
                f"M1: HORA ATUAL {platform_clock.hour:02d}:{platform_clock.minute:02d}:"
                f"{platform_clock.second:02d}; N+1 observada pelo relógio, janela M1 aberta."
            )
        elif pending is not None:
            expire_reason = (
                "mais de 30 s em N+1" if offset == 1
                else "a leitura avançou mais de um minuto ou voltou no tempo"
            )
            self.timer_status.set(f"M1: entrada bloqueada — {expire_reason}.")
        elif self.demo_automation_enabled:
            self.timer_status.set(
                f"M1: HORA ATUAL {platform_clock.hour:02d}:{platform_clock.minute:02d}:"
                f"{platform_clock.second:02d}; contínuo: no máximo uma entrada nesta vela, só até :30."
            )
        elif 0 <= elapsed <= 30:
            self.timer_status.set(
                f"M1: HORA ATUAL {platform_clock.hour:02d}:{platform_clock.minute:02d}:"
                f"{platform_clock.second:02d}; {elapsed}s da vela, janela manual aberta."
            )
        else:
            self.timer_status.set(f"M1: {elapsed}s decorridos; janela de 30s expirada.")

        if pending is not None and expire_reason is not None:
            expired = self.simulation.cancel_pending()
            self._clear_pending_clock_observation()
            label = "COMPRA" if expired.direction == "BUY" else "VENDER"
            log_error = self._record_simulation_event(
                "sinal_expirado", direction=expired.direction,
                observed_text=expired.observed_text, confidence=expired.confidence,
                signal_x=expired.x, signal_y=expired.y,
            )
            if self.demo_automation_enabled:
                self._deactivate_demo_automation()
                self.demo_status.set("Teste DEMO encerrado sem clique: janela M1/N+1 não foi válida.")
            persistence_note = f" Histórico local não gravado: {log_error}" if log_error else ""
            self.simulation_status.set(
                f"Sinal {label} descartado: {expire_reason}; nenhuma entrada enviada."
                f"{persistence_note}"
            )
        self._refresh_simulation_buttons()

    def _on_timeframe_change(self, _event: tk.Event | None = None) -> None:
        if self.demo_automation_enabled and self.timeframe_var.get() != "M1":
            self._toggle_demo_automation()
        self._persist_config()
        self._update_timer_status()

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

    def _persist_config(self) -> None:
        payload: dict[str, object] = {
            "timeframe": self.timeframe_var.get(),
            "confidence": self.confidence_var.get(),
            "ocr_enabled": self.ocr_enabled_var.get(),
            "compact_during_capture": self.compact_during_capture_var.get(),
            "tesseract_executable": self.tesseract_path_var.get().strip().strip('"'),
            "demo_entry_deadline_seconds": self.demo_entry_deadline_var.get(),
        }
        try:
            timeout_seconds = int(self.demo_activation_timeout_var.get())
            if MIN_DEMO_ACTIVATION_TIMEOUT_SECONDS <= timeout_seconds <= MAX_DEMO_ACTIVATION_TIMEOUT_SECONDS:
                payload["demo_activation_timeout_seconds"] = timeout_seconds
        except (AttributeError, TypeError, ValueError):
            pass
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
            timeframe = config.get("timeframe")
            if timeframe in {"M1", "M5", "M15", "M30"}:
                self.timeframe_var.set(timeframe)
            timeout_seconds = int(config.get(
                "demo_activation_timeout_seconds", DEFAULT_DEMO_ACTIVATION_TIMEOUT_SECONDS
            ))
            if MIN_DEMO_ACTIVATION_TIMEOUT_SECONDS <= timeout_seconds <= MAX_DEMO_ACTIVATION_TIMEOUT_SECONDS:
                self.demo_activation_timeout_var.set(str(timeout_seconds))
            entry_deadline = int(config.get(
                "demo_entry_deadline_seconds", DEFAULT_DEMO_ENTRY_DEADLINE_SECONDS
            ))
            if MIN_DEMO_ENTRY_DEADLINE_SECONDS <= entry_deadline <= MAX_DEMO_ENTRY_DEADLINE_SECONDS:
                self.demo_entry_deadline_var.set(str(entry_deadline))
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
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.capture_status.set(f"Configuração anterior ignorada ({exc}).")

    def _on_close(self) -> None:
        self._stop_sequence_recording("aplicativo fechado")
        self._set_capture_keep_awake(False)
        if self.demo_automation_enabled:
            self._toggle_demo_automation()
        self._persist_config()
        self.running = False
        self.destroy()


def main() -> None:
    app = AutoTraderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
