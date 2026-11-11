"""Interface de OCR e automação assistida de cliques em COMPRA/VENDER."""

from __future__ import annotations

import csv
import hashlib
import json
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from uuid import uuid4

from PIL import Image, ImageDraw, ImageTk

from .capture import ScreenCapture, ScreenRegion
from .geometry_diagnostics import save_snapshot as _save_geometry_snapshot
from .geometry_diagnostics import summarize as summarize_geometry
from .capture_quality import (
    FrameFreshness,
    FrameFreshnessMonitor,
    FrameQuality,
    assess_frame,
    classify_frame_rejection,
)
from .operation_modes import ModeDecision, OperationMode, actual_order_execution_allowed, mode_decision
from .opportunity_store import OpportunityStore
from .signal_lifecycle import SignalLifecycle, SignalLifecycleTracker
from .demo_clock import WindowsUtcMinusThreeClock, demo_entry_second_action
from .demo_click import (
    ClickTarget,
    click_demo_direction,
    windows_last_input_idle_seconds,
    windows_mouse_click,
    windows_mouse_move,
    windows_mouse_position,
    windows_window_at_point,
    windows_window_signature_at_point,
)
from .candle_monitor import (
    classify_market_context,
    count_signal_labels_by_candle,
    _market_candles_from_bars,
    detect_candle_bars,
    detect_candle_bars_detailed,
    filter_to_recent_candle,
    label_age_bars,
)
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
from .eligibility import (
    BALANCED_CRITERIA,
    EligibilityCriteria,
    evaluate_eligibility,
    validate_criteria,
)
from .ocr_diagnostics import classify_association_outcome, summarize_ocr_yield
from .opportunity_grade import (
    DEFAULT_CRITERIA as DEFAULT_GRADE_CRITERIA,
    GRADE_CRITERIA_VERSION,
    GRADE_METHOD,
    GradeCriteria,
    migrate_criteria,
    build_features,
    grade_opportunity,
    validate_grade_criteria,
)
from .signal_detector import SignalCandidate, TesseractSignalDetector
from .simulation_history import SimulationHistoryStore, append_event_best_effort
from .simulation import PendingSignal, SimulationWorkflow
from .windows_power import set_windows_keep_awake


APP_NAME = "AUTO TRADER IQ"
DEMO_CLOCK_SOURCE = "windows_utc_minus_3"
POLL_MS = 250
OCR_INTERVAL_SECONDS = 0.5
CONTEXT_INTERVAL_SECONDS = 1.0
# A faixa do relógio é a etapa mais cara do OCR. Ela roda em executor próprio,
# encadeada sem intervalo: assim que uma leitura termina, a próxima começa. Isso
# mantém a leitura mais recente possível sem somar segundos ao caminho crítico dos
# rótulos. O limite de idade do relógio não muda.
CLOCK_INTERVAL_SECONDS = 0.0
TIMER_MAX_AGE_SECONDS = 1.5
DEFAULT_DEMO_ACTIVATION_TIMEOUT_SECONDS = 75
MIN_DEMO_ACTIVATION_TIMEOUT_SECONDS = 15
MAX_DEMO_ACTIVATION_TIMEOUT_SECONDS = 28_800
DEFAULT_DEMO_ENTRY_SECOND = 5
MIN_DEMO_ENTRY_SECOND = 0
MAX_DEMO_ENTRY_SECOND = 30
DEFAULT_DEMO_MOUSE_KEEPALIVE_SECONDS = 60
MIN_DEMO_MOUSE_KEEPALIVE_SECONDS = 30
MAX_DEMO_MOUSE_KEEPALIVE_SECONDS = 600
DEMO_MOUSE_KEEPALIVE_POLL_MS = 5000
DEMO_MOUSE_KEEPALIVE_CLEARANCE_PX = 100
DEMO_MOUSE_KEEPALIVE_NUDGE_PX = 4
CANDLE_PALETTE_MAPS: dict[str, dict[str, str]] = {
    "Não calibrada": {},
    "Verde = alta / branca = baixa": {"green": "BUY", "white": "SELL"},
    "Verde = baixa / branca = alta": {"green": "SELL", "white": "BUY"},
}


def _label_geometry(raw_candidates, bars) -> dict[str, object] | None:
    """Onde o rótulo mais à direita caiu em relação às velas detectadas.

    Delega para o diagnóstico, que também mede a regularidade da grade: uma
    detecção fora da grade (eixo, linha, elemento de outro painel) não deve
    envelhecer o rótulo.
    """
    return summarize_geometry(bars, raw_candidates)


def _analyze_ocr_frame(
    detector: TesseractSignalDetector,
    image: Image.Image,
    color_direction_map: dict[str, str] | None = None,
    read_clock: bool = True,
    snapshot_dir: Path | None = None,
    age_reference: str = "detected",
):
    """OCR labels and match them against candles detected in this exact frame."""
    color_map = dict(color_direction_map or {})
    palette_colors = set(color_map) or None
    candle_started_at = time.monotonic()
    bars, candle_stats = detect_candle_bars_detailed(
        image, palette_colors=palette_colors
    )
    candle_seconds = round(time.monotonic() - candle_started_at, 3)
    raw_candidates, clock = detector.detect_frame(image, read_clock=read_clock)
    candidates = filter_to_recent_candle(raw_candidates, bars, reference=age_reference)
    label_geometry = _label_geometry(raw_candidates, bars)
    if snapshot_dir is not None and label_geometry:
        # Uma imagem a cada minuto, no máximo, e só quando o rótulo está longe da
        # última vela detectada: é o caso que o relatório sinalizou.
        _save_geometry_snapshot(image, bars, raw_candidates, snapshot_dir)
    label_ages = [
        label_age_bars(candidate, bars, reference=age_reference) for candidate in candidates
    ]
    # Geometria de corpo/pavio só é extraída quando existe candidato e a paleta está
    # calibrada: sem semântica de cor não há direção, e a extração custa caro.
    body_started_at = time.monotonic()
    market_candles = (
        _market_candles_from_bars(image, bars, color_direction_map=color_map)
        if candidates and color_map else []
    )
    body_seconds = round(time.monotonic() - body_started_at, 3)
    label_counts = count_signal_labels_by_candle(raw_candidates, bars, lookback=12)
    timings = dict(detector.last_ocr_timings)
    timings["candle_detection_seconds"] = candle_seconds
    timings["candle_detection"] = candle_stats
    timings["candle_body_seconds"] = body_seconds
    return (
        candidates,
        clock,
        detector.last_candidate_count,
        detector.last_color_rejected_count,
        len(bars),
        detector.last_clock_ocr_text,
        label_counts,
        raw_candidates,
        timings,
        label_ages,
        market_candles,
        label_geometry,
    )


def _analyze_market_context_frame(
    image: Image.Image,
    color_direction_map: dict[str, str] | None = None,
):
    """Classify using only candle colors explicitly calibrated for this profile."""
    palette_colors = set(color_direction_map) if color_direction_map else None
    bars = detect_candle_bars(image, palette_colors=palette_colors)
    return bars, classify_market_context(
        image, bars, color_direction_map=color_direction_map
    )


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
        self.title(f"{APP_NAME} — Automação assistida")
        self.geometry("1050x760")
        self.minsize(800, 580)

        self.data_dir = _data_dir()
        self.config_path = self.data_dir / "config.json"
        self.simulation_history = SimulationHistoryStore(self.data_dir / "simulation_history.csv")
        self.opportunity_store = OpportunityStore(self.data_dir / "opportunities.sqlite3")
        try:
            self.journal_recovery_snapshot = self.opportunity_store.recovery_snapshot()
            self.journal_integrity_healthy = bool(
                self.journal_recovery_snapshot["integrity"]["healthy"]
            )
        except Exception as exc:
            self.journal_recovery_snapshot = {
                "integrity": {"error": str(exc)},
                "unresolved_executions": [],
                "open_capture_sessions": [],
            }
            self.journal_integrity_healthy = False
        self.monitors: list[dict[str, int]] = []
        self.region: ScreenRegion | None = None
        self.running = False
        self.last_frame_hash: str | None = None
        self.last_change_at = time.monotonic()
        self.frame_freshness_monitor = FrameFreshnessMonitor()
        self.latest_frame_freshness: FrameFreshness | None = None
        self.latest_capture_block_reason = ""
        self.last_ocr_change_sequence: int | None = None
        self.last_context_change_sequence: int | None = None
        self.latest_frame_quality: FrameQuality | None = None
        self.latest_capture_quality_at: float | None = None
        self.latest_capture_quality_valid = False
        self.latest_candidates_at: float | None = None
        self.last_pil_image: Image.Image | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.compact_preview_photo: ImageTk.PhotoImage | None = None
        self.detector: TesseractSignalDetector | None = None
        self._ocr_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="auto-trader-ocr")
        self._context_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="auto-trader-context")
        self._clock_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="auto-trader-clock")
        self._ocr_future: Future | None = None
        self._ocr_frame_captured_at: float | None = None
        self._ocr_frame_captured_utc: str | None = None
        self._ocr_frame_id: str | None = None
        self._ocr_frame_quality: dict[str, object] | None = None
        self._ocr_future_generation = 0
        self._context_future: Future | None = None
        self._context_frame_captured_at: float | None = None
        self._context_future_generation = 0
        self._clock_future: Future | None = None
        self._clock_frame_captured_at: float | None = None
        self._clock_future_generation = 0
        self.last_clock_submit_at = 0.0
        self.last_clock_reading_seconds: float | None = None
        self._capture_generation = 0
        self._closing = False
        self.last_candidates: list[SignalCandidate] = []
        self.last_ocr_at = 0.0
        self.latest_platform_clock: PlatformClockReading | None = None
        self.latest_clock_ocr_text = ""
        self.latest_clock_at: float | None = None
        # Aviso exibido quando a sonda confirma que o relógio não está na seleção.
        self.clock_probe_hint: str | None = None
        self.association_code = "NO_LABELS"
        self.association_text = ""
        self.eligibility_code = "CRITERIA_UNDEFINED"
        self.eligibility_text = ""
        self.eligibility_hash: str | None = None
        self.grade_criteria = DEFAULT_GRADE_CRITERIA
        self.label_age_reference = "detected"
        self.grade_code = "CRITERIA_UNDEFINED"
        self.grade_text = ""
        self.grade_reasons: tuple[str, ...] = ()
        self.grade_features: dict[str, object] | None = None
        # Perfil inicial recomendado; cada campo continua explícito e auditável.
        self.eligibility_criteria = BALANCED_CRITERIA
        self.eligibility_problems: list[str] = []
        self.pending_armed_clock: PlatformClockReading | None = None
        self.pending_rollover_notified = False
        self.latest_bar_count = 0
        self.latest_candle_bars = []
        self.last_context_at = 0.0
        self.sequence_recorder = SequenceRecorder(self.data_dir / "sequences")
        self.sequence_status = tk.StringVar(value="Gravação de teste inativa; nenhuma imagem está sendo salva.")
        self.simulation = SimulationWorkflow()
        self.demo_clock = WindowsUtcMinusThreeClock()
        self.demo_signal_guard = DemoSignalRepeatGuard()
        self.candidates_by_id: dict[str, SignalCandidate] = {}
        self.signal_lifecycle = SignalLifecycleTracker()
        self.candidate_lifecycle_by_id: dict[str, SignalLifecycle] = {}
        self.candidate_fingerprint_by_id: dict[str, str] = {}
        self.candidate_related_by_id: dict[str, str | None] = {}
        self.candidate_duplicate_count_by_id: dict[str, int] = {}
        self.active_signal_profile_id: str | None = None
        self.active_screen_layout: list[dict[str, int]] | None = None
        self.last_layout_check_at = 0.0
        self.signal_tracking_persistence_healthy = self.journal_integrity_healthy
        self.capture_session_id: str | None = None
        self.simulation_status = tk.StringVar(value="Simulação parada; nenhuma entrada foi registrada.")
        self.operation_mode_var = tk.StringVar(value=OperationMode.OBSERVATION.value)
        self.operation_mode = OperationMode.OBSERVATION
        self.operation_mode_status = tk.StringVar(
            value="OBSERVAÇÃO: análise e registro; ordens automáticas bloqueadas."
        )
        self.research_status = tk.StringVar(
            value=f"Journal local: {self.data_dir / 'opportunities.sqlite3'} · esquema v3"
        )
        if not self.journal_integrity_healthy:
            self.research_status.set(
                "Integridade do journal indisponível; simulação permanece bloqueada."
            )
        elif self.journal_recovery_snapshot.get("unresolved_executions"):
            self.research_status.set(
                f"Recuperação: {len(self.journal_recovery_snapshot['unresolved_executions'])} "
                "tentativa(s) sem estado final verificável. Não haverá repetição automática."
            )
        elif self.journal_recovery_snapshot.get("open_capture_sessions"):
            self.research_status.set(
                f"Recuperação: {len(self.journal_recovery_snapshot['open_capture_sessions'])} "
                "sessão(ões) de captura sem encerramento explícito. Não foram fechadas automaticamente."
            )
        self.demo_status = tk.StringVar(
            value="Cliques automáticos bloqueados: não há verificação confiável da conta."
        )
        self.demo_automation_enabled = False
        self.demo_account_confirmed = False
        self.demo_timeout_after_id: str | None = None
        self.demo_activation_timeout_var = tk.StringVar(
            value=str(DEFAULT_DEMO_ACTIVATION_TIMEOUT_SECONDS)
        )
        self.demo_entry_second_var = tk.StringVar(value=f"{DEFAULT_DEMO_ENTRY_SECOND:02d}")
        self.demo_activation_timeout_active = DEFAULT_DEMO_ACTIVATION_TIMEOUT_SECONDS
        self.demo_entry_second_active = DEFAULT_DEMO_ENTRY_SECOND
        self.demo_entry_after_id: str | None = None
        self.demo_entries_this_activation = 0
        self.demo_minute_tracker = PlatformMinuteTracker()
        self.pending_demo_candle_id: int | None = None
        self.last_demo_entry_candle_id: int | None = None
        self.demo_click_targets: dict[str, ClickTarget | None] = {"BUY": None, "SELL": None}
        self.demo_click_target_windows: dict[str, int | None] = {"BUY": None, "SELL": None}
        self.demo_click_target_signatures: dict[str, dict[str, object] | None] = {
            "BUY": None, "SELL": None
        }
        self.demo_mouse_keepalive_target: ClickTarget | None = None
        self.demo_mouse_keepalive_alternate: ClickTarget | None = None
        self.demo_mouse_keepalive_window: int | None = None
        self.demo_mouse_keepalive_signature: dict[str, object] | None = None
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
        self.market_context_status = tk.StringVar(value="Contexto visual: aguardando captura.")
        self.candle_palette_var = tk.StringVar(value="Não calibrada")
        self.candle_palette_profile_id: str | None = None
        self.market_context_display_text = "Contexto visual: aguardando captura."
        self.signal_label_counts = {"BUY": 0, "SELL": 0}
        self.signal_label_context_at: float | None = None
        self.market_context_regime = "unknown"
        self.market_context_direction: str | None = None
        self.market_context_at: float | None = None
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
        self._update_demo_toggle_text()
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
        ttk.Label(header, text="OCR COMPRA/VENDER · simulação manual · cliques automáticos",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(3, 0))

        warning = ttk.Label(
            self.full_ui,
            text="Cliques automáticos ficam desligados por padrão. Há no máximo uma tentativa por vela M1, no segundo configurado. O app não verifica a conta, os parâmetros da ordem nem sua aceitação; um clique pode enviar uma ordem real.",
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

        context_box = ttk.LabelFrame(right_content, text="Contexto do gráfico · heurística visual", padding=6)
        context_box.pack(fill="x", pady=(6, 0))
        ttk.Label(context_box, textvariable=self.market_context_status, wraplength=650).pack(anchor="w")
        palette_row = ttk.Frame(context_box)
        palette_row.pack(fill="x", pady=(4, 0))
        ttk.Label(palette_row, text="Calibração desta captura:").pack(side="left", padx=(0, 5))
        self.candle_palette_combo = ttk.Combobox(
            palette_row,
            textvariable=self.candle_palette_var,
            values=tuple(CANDLE_PALETTE_MAPS),
            state="readonly",
            width=34,
        )
        self.candle_palette_combo.pack(side="left", fill="x", expand=True)
        self.candle_palette_combo.bind("<<ComboboxSelected>>", self._on_candle_palette_change)

        simulation_box = ttk.LabelFrame(
            right_content,
            text="Simulação manual · cliques automáticos opcionais",
            padding=6,
        )
        simulation_box.pack(fill="x", pady=(8, 0))
        mode_row = ttk.Frame(simulation_box)
        mode_row.pack(fill="x", pady=(0, 5))
        ttk.Label(mode_row, text="Modo:").pack(side="left", padx=(0, 5))
        self.operation_mode_combo = ttk.Combobox(
            mode_row,
            textvariable=self.operation_mode_var,
            values=tuple(mode.value for mode in OperationMode),
            state="readonly",
            width=18,
        )
        self.operation_mode_combo.pack(side="left")
        self.operation_mode_combo.bind("<<ComboboxSelected>>", self._on_operation_mode_change)
        ttk.Label(simulation_box, textvariable=self.operation_mode_status, wraplength=650).pack(
            anchor="w", pady=(0, 3)
        )
        ttk.Label(simulation_box, textvariable=self.research_status, wraplength=650).pack(
            anchor="w", pady=(0, 5)
        )
        self.candidate_table = ttk.Treeview(
            simulation_box, columns=("label", "confidence", "position"), show="headings", height=3,
            selectmode="browse",
        )
        self.candidate_table.heading("label", text="Etiqueta OCR")
        self.candidate_table.heading("confidence", text="Confiança")
        self.candidate_table.heading("position", text="Posição na captura")
        self.candidate_table.column("label", width=340, stretch=True)
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
            sim_buttons,
            text="Cliques bloqueados · sem verificação de conta",
            command=self._toggle_demo_automation,
            state="disabled",
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
            text="Movimentar cursor sem clicar após inatividade (opcional)",
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
        self.demo_mouse_keepalive_spinbox.bind("<FocusOut>", lambda _event: self._persist_config())
        self.demo_mouse_keepalive_spinbox.bind("<Return>", lambda _event: self._persist_config())
        demo_timeout_row = ttk.Frame(simulation_box)
        demo_timeout_row.pack(fill="x", pady=(3, 0))
        ttk.Label(
            demo_timeout_row,
            text=f"Limite da automação contínua ({MIN_DEMO_ACTIVATION_TIMEOUT_SECONDS}–"
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
        demo_entry_second_row = ttk.Frame(simulation_box)
        demo_entry_second_row.pack(fill="x", pady=(3, 0))
        ttk.Label(demo_entry_second_row, text="Segundo fixo do clique automático (:SS):").pack(
            side="left", padx=(0, 6)
        )
        self.demo_entry_second_spinbox = ttk.Spinbox(
            demo_entry_second_row,
            from_=MIN_DEMO_ENTRY_SECOND,
            to=MAX_DEMO_ENTRY_SECOND,
            increment=1,
            textvariable=self.demo_entry_second_var,
            width=4,
            command=self._persist_config,
        )
        self.demo_entry_second_spinbox.pack(side="left")
        self.demo_entry_second_spinbox.bind("<FocusOut>", lambda _event: self._persist_config())
        self.demo_entry_second_spinbox.bind("<Return>", lambda _event: self._persist_config())
        ttk.Label(
            demo_entry_second_row,
            text=f"tenta em :SS; sinal tardio descartado · padrão :{DEFAULT_DEMO_ENTRY_SECOND:02d}",
        ).pack(side="left", padx=(6, 0))
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
        ttk.Label(self.compact_frame, textvariable=self.operation_mode_status, wraplength=640).pack(
            anchor="w", pady=(0, 2)
        )
        ttk.Label(self.compact_frame, textvariable=self.ocr_status, wraplength=640).pack(
            anchor="w", pady=(0, 2)
        )
        ttk.Label(self.compact_frame, textvariable=self.market_context_status, wraplength=640).pack(
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
        self.compact_candidate_table.column("label", width=300, stretch=True)
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
            text="Movimentar cursor sem clicar após inatividade (opcional)",
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
            compact_controls,
            text="Cliques bloqueados · sem verificação de conta",
            command=self._toggle_demo_automation,
            state="disabled",
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
        if self.running and self.region != region:
            self._stop_capture("Captura parada: a região mudou e exige nova linha de base visual.")
        self.region = region
        if self.candle_palette_profile_id is not None:
            try:
                profile_matches = self.candle_palette_profile_id == self._capture_profile_id()
            except Exception:
                profile_matches = False
            if not profile_matches:
                self.candle_palette_var.set("Não calibrada")
                self.candle_palette_profile_id = None
        for key, value in (("left", region.left), ("top", region.top),
                           ("width", region.width), ("height", region.height)):
            self.region_vars[key].set(str(value))
        self.capture_status.set(f"Região definida: {region.width}×{region.height} px")

    def _capture_profile_id(self) -> str:
        region = self.region
        if region is None:
            raise RuntimeError("Defina a região antes de identificar o perfil de captura.")
        payload = {
            "region": asdict(region),
            "screen_layout": self._screen_layout_signature(),
            "detector_version": "ocr-labels-v1",
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _begin_signal_tracking_session(self) -> None:
        profile_id = self._capture_profile_id()
        timeframe = self.timeframe_var.get()
        tracker = SignalLifecycleTracker(
            identity_namespace=f"{profile_id}:{timeframe}",
            detector_version="ocr-labels-v1",
        )
        try:
            recovery = self.opportunity_store.recovery_snapshot()
            if not recovery["integrity"]["healthy"]:
                raise RuntimeError("integrity_check ou foreign_key_check do journal falhou")
            if recovery["unresolved_executions"]:
                raise RuntimeError(
                    f"{len(recovery['unresolved_executions'])} tentativa(s) anteriores "
                    "exigem reconciliação manual; nenhuma será repetida automaticamente"
                )
            tracker.restore(self.opportunity_store.load_signal_tracks(
                profile_id=profile_id, timeframe=timeframe
            ))
            self.signal_tracking_persistence_healthy = True
        except Exception as exc:
            # A tracker without its persistent baseline must fail closed for arming.
            self.signal_tracking_persistence_healthy = False
            self.research_status.set(
                f"Rastreamento persistente indisponível; simulação bloqueada: {exc}"
            )
        self.signal_lifecycle = tracker
        self.active_signal_profile_id = profile_id
        self.active_screen_layout = self._screen_layout_signature()
        self.last_layout_check_at = 0.0

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
            messagebox.showinfo(APP_NAME, "Desative os cliques automáticos antes de calibrar os botões.", parent=self)
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
        self.demo_click_target_signatures[direction] = None
        self.demo_mouse_keepalive_target = None
        self.demo_mouse_keepalive_alternate = None
        self.demo_mouse_keepalive_window = None
        self.demo_mouse_keepalive_signature = None
        self.demo_mouse_keepalive_var.set(False)
        self.demo_mouse_keepalive_status.set("Recalibre o ponto neutro após recalibrar botões.")
        self._set_demo_target_label(direction, None)
        self._persist_config()
        self.demo_status.set(f"Calibração {label}: janela oculta por 5 s; posicione o cursor no centro do botão.")
        self.withdraw()
        self._calibration_after_id = self.after(5000, lambda: self._finish_demo_calibration(direction))

    def _finish_demo_calibration(self, direction: str) -> None:
        target: ClickTarget | None = None
        target_window: int | None = None
        target_signature: dict[str, object] | None = None
        error: Exception | None = None
        try:
            x, y = windows_mouse_position()
            target = ClickTarget(x, y)
            target_window = windows_window_at_point(x, y)
            target_signature = windows_window_signature_at_point(x, y)
            if target_window is None or not self._valid_window_signature(target_signature):
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
        assert target is not None and target_window is not None and target_signature is not None
        self.demo_click_targets[direction] = target
        self.demo_click_target_windows[direction] = target_window
        self.demo_click_target_signatures[direction] = target_signature
        self._set_demo_target_label(direction, target)
        self._persist_config()
        label = "COMPRAR" if direction == "BUY" else "VENDER"
        if self._inside_capture_region(target) and not self._target_is_excluded_or_outside_capture(target):
            self.demo_status.set(
                f"Botão {label} calibrado em {target.x}, {target.y}; marque uma área para ocultar os botões "
                "antes de ativar cliques automáticos. Nenhum clique foi enviado."
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
        buy_signature = self.demo_click_target_signatures["BUY"]
        sell_signature = self.demo_click_target_signatures["SELL"]
        if (
            None in expected_windows
            or expected_windows != {target_window}
            or buy_signature is None
            or sell_signature is None
            or buy_signature != sell_signature
            or self.demo_mouse_keepalive_signature != buy_signature
        ):
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
                    if (
                        windows_window_at_point(point.x, point.y) != target_window
                        or windows_window_signature_at_point(point.x, point.y)
                        != self.demo_mouse_keepalive_signature
                    ):
                        return False
                except Exception:
                    return False
        return True

    def _calibrate_demo_mouse_keepalive_target(self) -> None:
        if sys.platform != "win32":
            messagebox.showerror(APP_NAME, "A calibração do cursor só funciona no Windows.", parent=self)
            return
        if self.demo_automation_enabled:
            messagebox.showinfo(APP_NAME, "Desative os cliques automáticos antes de calibrar o ponto neutro.", parent=self)
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
            "não clique. O ponto e uma posição adjacente serão usados apenas durante uma ativação explícita da automação.",
            parent=self,
        )
        if not consent:
            return
        self.demo_mouse_keepalive_target = None
        self.demo_mouse_keepalive_alternate = None
        self.demo_mouse_keepalive_window = None
        self.demo_mouse_keepalive_signature = None
        self.demo_mouse_keepalive_status.set("Calibração: posicione no ponto neutro, sem clicar.")
        self._persist_config()
        self.withdraw()
        self.after(5000, self._finish_demo_mouse_keepalive_calibration)

    def _finish_demo_mouse_keepalive_calibration(self) -> None:
        try:
            x, y = windows_mouse_position()
            target = ClickTarget(x, y)
            target_window = windows_window_at_point(x, y)
            target_signature = windows_window_signature_at_point(x, y)
            if target_window is None or not self._valid_window_signature(target_signature):
                raise RuntimeError("Não foi possível identificar a janela sob o ponto escolhido.")
            if (
                target_signature != self.demo_click_target_signatures["BUY"]
                or target_signature != self.demo_click_target_signatures["SELL"]
            ):
                raise RuntimeError("O ponto neutro precisa estar na mesma janela já calibrada para COMPRAR/VENDER.")
            self.demo_mouse_keepalive_signature = target_signature
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
            self.demo_mouse_keepalive_target = None
            self.demo_mouse_keepalive_alternate = None
            self.demo_mouse_keepalive_window = None
            self.demo_mouse_keepalive_signature = None
            self._persist_config()
            self.demo_mouse_keepalive_status.set("Ponto neutro não calibrado.")
            messagebox.showerror(APP_NAME, f"Calibração do ponto neutro recusada:\n{exc}", parent=self)
            return
        self.deiconify()
        self.demo_mouse_keepalive_target = target
        self.demo_mouse_keepalive_alternate = alternate
        self.demo_mouse_keepalive_window = target_window
        self.demo_mouse_keepalive_signature = target_signature
        self.demo_mouse_keepalive_use_alternate = False
        self.demo_mouse_keepalive_status.set(
            f"Ponto neutro calibrado em {target.x},{target.y}; sem clique."
        )
        self._persist_config()

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
            self._persist_config()
            return
        if self.demo_mouse_keepalive_target is None or self.demo_mouse_keepalive_alternate is None:
            self.demo_mouse_keepalive_var.set(False)
            self._persist_config()
            messagebox.showinfo(
                APP_NAME,
                "Calibre primeiro o ponto neutro. O movimento não envia cliques e só funciona durante a automação ativa.",
                parent=self,
            )
            return
        if self._demo_mouse_keepalive_interval() is None:
            self.demo_mouse_keepalive_var.set(False)
            self._persist_config()
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
                "Movimento sem clique habilitado; aguardando inatividade do usuário."
            )
        else:
            self.demo_mouse_keepalive_status.set(
                "Ativado; só movimentará o cursor durante a automação ativa."
            )
        self._persist_config()

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
                    f"Movimento sem clique aguardando {interval} s de inatividade do usuário."
                )
        except Exception as exc:
            self.demo_mouse_keepalive_status.set(f"Movimento sem clique suspenso por erro: {exc}")
        self._schedule_demo_mouse_keepalive()

    def _update_demo_toggle_text(self) -> None:
        text = "Cliques bloqueados · sem verificação de conta"
        for name in ("demo_toggle_button", "compact_demo_toggle_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.configure(text=text, state="disabled")
        for name in ("demo_timeout_spinbox", "demo_entry_second_spinbox"):
            spinbox = getattr(self, name, None)
            if spinbox is not None:
                spinbox.configure(state="disabled")

    def _active_candle_color_direction_map(self) -> dict[str, str]:
        if self.region is None or self.candle_palette_profile_id is None:
            return {}
        try:
            current_profile_id = self._capture_profile_id()
        except Exception:
            return {}
        if current_profile_id != self.candle_palette_profile_id:
            return {}
        return dict(CANDLE_PALETTE_MAPS.get(self.candle_palette_var.get(), {}))

    def _on_candle_palette_change(self, _event: tk.Event | None = None) -> None:
        palette_name = self.candle_palette_var.get()
        if palette_name not in CANDLE_PALETTE_MAPS:
            self.candle_palette_var.set("Não calibrada")
            return
        if palette_name == "Não calibrada":
            self.candle_palette_profile_id = None
        else:
            if self.region is None:
                self.candle_palette_var.set("Não calibrada")
                messagebox.showwarning(
                    APP_NAME,
                    "Defina a região do gráfico antes de calibrar as cores das velas.",
                    parent=self,
                )
                return
            try:
                self.candle_palette_profile_id = self._capture_profile_id()
            except Exception as exc:
                self.candle_palette_var.set("Não calibrada")
                self.candle_palette_profile_id = None
                messagebox.showwarning(APP_NAME, f"Calibração não salva: {exc}", parent=self)
                return
        if self.running:
            if self.simulation.pending is not None:
                self._cancel_pending_simulation()
            self._stop_capture(
                "Captura parada: paleta alterada; reinicie para estabelecer nova linha de base."
            )
        self.market_context_regime = "unknown"
        self.market_context_direction = None
        self.market_context_at = None
        self.market_context_display_text = (
            "Contexto visual: aguardando nova captura com a paleta calibrada."
        )
        self._refresh_market_context_status()
        self._persist_config()

    def _on_operation_mode_change(self, _event: tk.Event | None = None) -> None:
        try:
            requested = OperationMode(self.operation_mode_var.get())
        except ValueError:
            requested = OperationMode.OBSERVATION
        decision = mode_decision(requested)
        if decision not in {ModeDecision.OBSERVE_ONLY, ModeDecision.SIMULATION_ONLY}:
            self.operation_mode = OperationMode.OBSERVATION
            self.operation_mode_var.set(self.operation_mode.value)
            self.operation_mode_status.set(
                "DEMO/REAL bloqueados: sem integração confiável para verificar conta, ordem ou saldo."
            )
            messagebox.showwarning(
                APP_NAME,
                "Este build permite OBSERVAÇÃO e SIMULAÇÃO. DEMO exige confirmação verificável de conta; "
                "REAL permanece bloqueado. Nenhum clique será enviado.",
                parent=self,
            )
            return
        self.operation_mode = requested
        if requested is OperationMode.OBSERVATION:
            if self.simulation.pending is not None:
                self._cancel_pending_simulation()
            self.operation_mode_status.set(
                "OBSERVAÇÃO: captura e registro; não arma entradas nem envia cliques."
            )
        else:
            self.operation_mode_status.set(
                "SIMULAÇÃO: entradas são hipotéticas; resultados financeiros não são inferidos."
            )
        self._persist_config()

    def _toggle_demo_automation(self) -> None:
        if self.demo_automation_enabled:
            self._deactivate_demo_automation()
            if self.simulation.pending is not None:
                self._cancel_pending_simulation()
            self.demo_status.set("Cliques automáticos desligados; nenhum sinal pendente será executado.")
            return
        self.demo_status.set(
            "Cliques automáticos bloqueados: não há adaptador confiável para verificar conta DEMO, "
            "saldo, ordem executada ou resultado."
        )
        self.operation_mode_status.set(
            "DEMO/REAL indisponíveis; permaneça em OBSERVAÇÃO ou SIMULAÇÃO. Nenhum clique foi enviado."
        )

    def _capture_quality_is_fresh(self) -> bool:
        if not self.latest_capture_quality_valid or self.latest_capture_quality_at is None:
            return False
        age = time.monotonic() - self.latest_capture_quality_at
        return 0 <= age <= TIMER_MAX_AGE_SECONDS

    def _fresh_visual_flow_direction(self) -> str | None:
        if not self._capture_quality_is_fresh():
            return None
        if self.market_context_regime != "flow" or self.market_context_at is None:
            return None
        age = time.monotonic() - self.market_context_at
        return self.market_context_direction if 0 <= age <= TIMER_MAX_AGE_SECONDS else None

    def _fresh_label_flow_direction(self) -> str | None:
        if not self._capture_quality_is_fresh() or self.signal_label_context_at is None:
            return None
        age = time.monotonic() - self.signal_label_context_at
        if not 0 <= age <= TIMER_MAX_AGE_SECONDS:
            return None
        buy_count = self.signal_label_counts["BUY"]
        sell_count = self.signal_label_counts["SELL"]
        if buy_count >= 2 and sell_count < 2:
            return "BUY"
        if sell_count >= 2 and buy_count < 2:
            return "SELL"
        return None

    def _market_context_allows_direction(self, direction: str) -> bool:
        if (
            self.signal_label_context_at is not None
            and 0 <= time.monotonic() - self.signal_label_context_at <= TIMER_MAX_AGE_SECONDS
            and self.signal_label_counts["BUY"] >= 2
            and self.signal_label_counts["SELL"] >= 2
        ):
            return False
        visual_direction = self._fresh_visual_flow_direction()
        label_direction = self._fresh_label_flow_direction()
        if (
            visual_direction is not None
            and label_direction is not None
            and visual_direction != label_direction
        ):
            return False
        return direction in {visual_direction, label_direction}

    def _refresh_market_context_status(self) -> None:
        base = self.market_context_display_text
        buy_count = self.signal_label_counts["BUY"]
        sell_count = self.signal_label_counts["SELL"]
        label_direction = self._fresh_label_flow_direction()
        visual_direction = self._fresh_visual_flow_direction()
        if buy_count >= 2 and sell_count >= 2:
            text = f"Fluxo incerto: {buy_count} velas COMPRA e {sell_count} velas VENDER; cliques bloqueados."
        elif label_direction is not None and visual_direction not in {None, label_direction}:
            label = "COMPRADOR" if label_direction == "BUY" else "VENDEDOR"
            visual = "comprador" if visual_direction == "BUY" else "vendedor"
            text = f"CONFLITO: {label} por etiquetas, mas fluxo visual {visual}; cliques bloqueados."
        elif label_direction is not None:
            label = "COMPRA" if label_direction == "BUY" else "VENDER"
            count = self.signal_label_counts[label_direction]
            text = f"FLUXO {('COMPRADOR' if label_direction == 'BUY' else 'VENDEDOR')} · {count} velas com etiqueta {label}. {base}"
        else:
            text = base
        self.market_context_status.set(text)

    def _cancel_auto_pending_for_context(self) -> None:
        pending = self.simulation.pending
        if (
            not self.demo_automation_enabled
            or pending is None
            or self._market_context_allows_direction(pending.direction)
        ):
            return
        self.demo_signal_guard.mark_consumed(pending.direction, pending.x, pending.y)
        self._cancel_pending_simulation()
        label = "COMPRA" if pending.direction == "BUY" else "VENDER"
        self.demo_status.set(
            f"Sinal {label} cancelado: a automação só opera em fluxo compatível e recente."
        )

    def _maybe_auto_arm_demo_signal(self) -> None:
        if (
            not self.demo_automation_enabled
            or not self.signal_tracking_persistence_healthy
            or not self.running
            or self.detector is None
            or self.timeframe_var.get() != "M1"
            or self.simulation.pending is not None
        ):
            return
        # O relógio Windows UTC−3 é a única referência temporal do DEMO.
        # A atualização do OCR não impõe um timeout adicional ao clique.
        clock = self.demo_clock.reading()
        current_candle_id = self.demo_minute_tracker.update(clock)
        if current_candle_id is None:
            return
        self.demo_signal_guard.advance_candle(current_candle_id)
        if (
            self.latest_candidates_at is None
            or not 0 <= time.monotonic() - self.latest_candidates_at <= TIMER_MAX_AGE_SECONDS
        ):
            return
        candidates = list(self.candidates_by_id.values())
        if len(candidates) != 1:
            if len(candidates) > 1:
                self.demo_status.set("Automação contínua pausada nesta leitura: há mais de um candidato OCR.")
            else:
                self.demo_status.set(
                    "Automação ativa: nenhum sinal COMPRA/VENDER recente e legível; "
                    "aguardando nova leitura OCR. O minuto de referência é o Windows UTC−3."
                )
            return
        candidate = candidates[0]
        if self.candidate_lifecycle_by_id.get(self._candidate_row_id(candidate)) is not SignalLifecycle.CONFIRMED_NEW:
            self.demo_status.set(
                "Automação aguardando etiqueta nova confirmada em leituras consecutivas; "
                "rótulos já visíveis ao iniciar não são elegíveis."
            )
            return
        if not self._market_context_allows_direction(candidate.direction):
            label = "COMPRA" if candidate.direction == "BUY" else "VENDER"
            required_flow = "comprador" if candidate.direction == "BUY" else "vendedor"
            self.demo_status.set(
                f"Automação ativa: clique {label} bloqueado até haver fluxo "
                f"{required_flow} visual, válido e recente."
            )
            return
        if self.last_demo_entry_candle_id == current_candle_id:
            self.demo_signal_guard.mark_consumed(
                candidate.direction, candidate.left, candidate.top
            )
            self.demo_status.set(
                f"Automação ativa: já houve uma tentativa na vela M1 "
                f"{clock.hour:02d}:{clock.minute:02d} do relógio Windows UTC−3; "
                "aguardando a próxima virada do minuto do Windows."
            )
            return
        if not m1_entry_window_open(clock, max_elapsed_seconds=30):
            self.demo_signal_guard.mark_consumed(
                candidate.direction, candidate.left, candidate.top
            )
            self.demo_status.set(
                f"Automação ativa: relógio Windows UTC−3 {clock.hour:02d}:{clock.minute:02d}:{clock.second:02d} passou de :30; "
                "este sinal foi descartado sem clique, aguardando um próximo sinal elegível."
            )
            return
        if self.demo_signal_guard.blocks(candidate):
            self.demo_status.set(
                f"Automação ativa: este sinal já foi consumido na vela M1 "
                f"{clock.hour:02d}:{clock.minute:02d} do relógio Windows UTC−3; "
                "aguardando a próxima virada do minuto do Windows."
            )
            return
        try:
            pending = self.simulation.arm(candidate, dedupe_scope=str(current_candle_id))
        except ValueError:
            return
        self.pending_demo_candle_id = current_candle_id
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
            f"Sinal {label} armado para clique automático ({pending.confidence:.0f}%). "
            f"Entrada programada para :{self.demo_entry_second_active:02d}; "
            f"uma tentativa nesta vela M1 do relógio Windows UTC−3.{persistence_note}"
        )
        self._refresh_simulation_buttons()
        self._execute_demo_click()

    def _target_window_is_topmost(self, direction: str, target: ClickTarget) -> bool:
        calibrated_window = self.demo_click_target_windows.get(direction)
        if calibrated_window is None:
            return False
        try:
            current_window = windows_window_at_point(target.x, target.y)
            current_signature = windows_window_signature_at_point(target.x, target.y)
        except Exception:
            return False
        return (
            current_window == calibrated_window
            and current_signature == self.demo_click_target_signatures.get(direction)
        )

    def _pending_demo_candidate_is_current(self, pending: PendingSignal) -> bool:
        if (
            self.latest_candidates_at is None
            or not 0 <= time.monotonic() - self.latest_candidates_at <= TIMER_MAX_AGE_SECONDS
        ):
            return False
        candidates = list(self.candidates_by_id.values())
        if len(candidates) != 1:
            return False
        candidate = candidates[0]
        return (
            self.candidate_lifecycle_by_id.get(self._candidate_row_id(candidate))
            is SignalLifecycle.CONFIRMED_NEW
            and candidate.direction == pending.direction
            and abs(candidate.left - pending.x) <= self.demo_signal_guard.tolerance_x
            and abs(candidate.top - pending.y) <= self.demo_signal_guard.tolerance_y
        )

    def _cancel_scheduled_demo_entry(self) -> None:
        if self.demo_entry_after_id is not None:
            try:
                self.after_cancel(self.demo_entry_after_id)
            except tk.TclError:
                pass
            self.demo_entry_after_id = None

    def _execute_demo_click(self) -> None:
        self.demo_entry_after_id = None
        pending = self.simulation.pending
        if not self.demo_automation_enabled or pending is None:
            return
        if not actual_order_execution_allowed(self.operation_mode):
            self._deactivate_demo_automation()
            self.demo_signal_guard.mark_consumed(pending.direction, pending.x, pending.y)
            self._cancel_pending_simulation()
            self.demo_status.set("Clique bloqueado pelo modo de segurança; nenhuma ordem foi enviada.")
            return
        if not self._market_context_allows_direction(pending.direction):
            self.demo_signal_guard.mark_consumed(pending.direction, pending.x, pending.y)
            self._cancel_pending_simulation()
            label = "COMPRA" if pending.direction == "BUY" else "VENDER"
            self.demo_status.set(
                f"Clique {label} cancelado: o fluxo compatível deixou de estar válido ou recente."
            )
            return
        clock = self.demo_clock.reading()
        current_candle_id = self.demo_minute_tracker.update(clock)
        self.demo_signal_guard.advance_candle(current_candle_id)
        if current_candle_id is None or current_candle_id != self.pending_demo_candle_id:
            self._cancel_pending_simulation()
            self.demo_status.set(
                f"Sinal expirou: o relógio Windows UTC−3 avançou para "
                f"{clock.hour:02d}:{clock.minute:02d} antes da tentativa; "
                "sinal antigo cancelado sem clique."
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
                "Clique automático bloqueado: o ponto do botão não está sobre a mesma janela calibrada. "
                "Traga a corretora para frente e recalibre os botões."
            )
            self._cancel_pending_simulation()
            return
        if not self._pending_demo_candidate_is_current(pending):
            self.demo_signal_guard.mark_consumed(pending.direction, pending.x, pending.y)
            self._cancel_pending_simulation()
            self.demo_status.set(
                "Sinal descartado: a etiqueta não está mais presente na leitura OCR recente."
            )
            return
        elapsed = platform_clock_elapsed_seconds(self.pending_armed_clock, clock)
        if elapsed is None:
            self.demo_signal_guard.mark_consumed(pending.direction, pending.x, pending.y)
            self._cancel_pending_simulation()
            self.demo_status.set(
                "Sinal descartado: o relógio Windows UTC−3 avançou de forma inválida; nenhum clique."
            )
            return
        action = demo_entry_second_action(clock.second, self.demo_entry_second_active)
        remaining_to_target = self.demo_entry_second_active - clock.second
        if action == "wait":
            self.demo_entry_after_id = self.after(
                remaining_to_target * 1000, self._execute_demo_click
            )
            self.demo_status.set(
                f"Sinal armado; aguardando :{self.demo_entry_second_active:02d} "
                "para padronizar o segundo da entrada."
            )
            return
        if action == "late":
            self.demo_signal_guard.mark_consumed(pending.direction, pending.x, pending.y)
            self._cancel_pending_simulation()
            self.demo_status.set(
                f"Sinal descartado: foi reconhecido depois de :{self.demo_entry_second_active:02d}; "
                "aguardando novo sinal na próxima vela."
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
        self.last_demo_entry_candle_id = self.pending_demo_candle_id
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
                f"Resultado do clique automático incerto ({exc}); automação encerrada para evitar repetição. "
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
            values=(time_text, label, f"Automática · atraso relógio Windows UTC−3 {elapsed} s"),
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
            "Tentativa de clique registrada; identidade da vela e aceitação pela plataforma não verificadas. "
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
            f"Automação encerrada pelo limite de {timeout} s; {entries} entrada(s) tentada(s)."
        )

    def _deactivate_demo_automation(self) -> None:
        self._cancel_scheduled_demo_entry()
        self._cancel_demo_mouse_keepalive()
        self.demo_automation_enabled = False
        self.demo_account_confirmed = False
        if self.demo_mouse_keepalive_var.get():
            self.demo_mouse_keepalive_status.set(
                "Keep-alive sem clique parado porque a automação terminou."
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
        problems = validate_criteria(self.eligibility_criteria, ocr_floor=self._ocr_floor())
        self.eligibility_problems = problems
        if problems:
            # Configuração incoerente com o piso atual do OCR: nada fica elegível.
            self.eligibility_criteria = EligibilityCriteria()
            self.research_status.set(
                "Elegibilidade bloqueada por configuração inválida: " + "; ".join(problems)
            )
        self._capture_generation += 1
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
        self.candidate_lifecycle_by_id.clear()
        self.candidate_fingerprint_by_id.clear()
        self.candidate_related_by_id.clear()
        self.candidate_duplicate_count_by_id.clear()
        self._begin_signal_tracking_session()
        self.capture_session_id = uuid4().hex
        try:
            self.opportunity_store.record_journal_event(
                "CAPTURE_SESSION_STARTED",
                source="CAPTURE_ENGINE",
                session_id=self.capture_session_id,
                payload={
                    "profile_id": self.active_signal_profile_id,
                    "timeframe": self.timeframe_var.get(),
                    "operation_mode": self.operation_mode.value,
                    "ocr_enabled": bool(self.ocr_enabled_var.get()),
                    "region": self.region.as_mss_dict() if self.region is not None else None,
                    "ocr_floor_confidence": self._ocr_floor(),
                    "eligibility_criteria": self.eligibility_criteria.as_dict(),
                    "eligibility_criteria_hash": self.eligibility_criteria.criteria_hash(),
                    "eligibility_problems": list(self.eligibility_problems),
                },
            )
        except Exception as exc:
            self.signal_tracking_persistence_healthy = False
            self.research_status.set(
                f"Journal não iniciou a sessão de captura; simulação bloqueada: {exc}"
            )
        self.latest_candidates_at = None
        self.last_ocr_at = 0.0
        self.latest_platform_clock = None
        self.latest_clock_at = None
        self.latest_clock_ocr_text = ""
        self.latest_bar_count = 0
        self.latest_candle_bars = []
        self.frame_freshness_monitor.reset()
        self.latest_frame_freshness = None
        self.latest_capture_block_reason = ""
        self.last_ocr_change_sequence = None
        self.last_context_change_sequence = None
        self.latest_frame_quality = None
        self.latest_capture_quality_at = None
        self.latest_capture_quality_valid = False
        self.latest_candidates_at = None
        self.last_context_at = 0.0
        self.signal_label_counts = {"BUY": 0, "SELL": 0}
        self.signal_label_context_at = None
        self.market_context_regime = "unknown"
        self.market_context_direction = None
        self.market_context_at = None
        self.market_context_display_text = "Contexto visual: analisando as velas recentes…"
        self._refresh_market_context_status()
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
        if self.capture_session_id is not None:
            session_id = self.capture_session_id
            self._record_capture_journal_event(
                "CAPTURE_SESSION_STOPPED",
                {"reason": reason},
                idempotency_key=f"{session_id}:stop",
                source="CAPTURE_ENGINE",
            )
            self.capture_session_id = None
        self._stop_sequence_recording("captura parada")
        self._set_capture_keep_awake(False)
        if self.demo_automation_enabled:
            self._toggle_demo_automation()
        self._capture_generation += 1
        self.running = False
        self.start_button.configure(text="Iniciar visualização")
        self.capture_status.set(reason)
        self.heartbeat_status.set("Sem captura")
        self._exit_compact_mode()

    def _record_capture_journal_event(
        self,
        event_type: str,
        payload: dict[str, object],
        *,
        idempotency_key: str,
        occurred_at_utc: str | None = None,
        source: str = "CAPTURE_ENGINE",
    ) -> bool:
        session_id = self.capture_session_id
        if session_id is None:
            self.signal_tracking_persistence_healthy = False
            return False
        try:
            self.opportunity_store.record_journal_event(
                event_type,
                source=source,
                session_id=session_id,
                occurred_at_utc=occurred_at_utc,
                idempotency_key=idempotency_key,
                payload=payload,
            )
            return True
        except Exception as exc:
            self.signal_tracking_persistence_healthy = False
            self.research_status.set(f"Journal de captura falhou; simulação bloqueada: {exc}")
            return False

    def _capture_tick(self) -> None:
        if not self.running or self.region is None:
            return
        now = time.monotonic()
        if now - self.last_layout_check_at >= 2.0:
            try:
                current_monitors = ScreenCapture.list_monitors()
                normalized_layout = sorted(
                    ({key: int(monitor[key]) for key in ("left", "top", "width", "height")}
                     for monitor in current_monitors),
                    key=lambda item: (item["left"], item["top"], item["width"], item["height"]),
                )
                if normalized_layout != self.active_screen_layout:
                    self.monitors = current_monitors
                    self.candle_palette_var.set("Não calibrada")
                    self.candle_palette_profile_id = None
                    self._persist_config()
                    self._stop_capture(
                        "Captura parada: resolução ou disposição de monitores mudou; "
                        "selecione a região e estabeleça nova linha de base."
                    )
                    return
                self.last_layout_check_at = now
            except Exception as exc:
                self._stop_capture(f"Captura parada: não foi possível validar o layout de monitores: {exc}")
                return
        try:
            image = ScreenCapture.capture(self.region)
            if image.size != (self.region.width, self.region.height):
                self._stop_capture(
                    "Captura parada: dimensões reais do quadro diferem da região calibrada."
                )
                return
            self._mask_excluded_regions(image)
            captured_at = time.monotonic()
            self.last_pil_image = image
            self.latest_frame_quality = assess_frame(image)
            self.latest_capture_quality_at = captured_at
            self.latest_frame_freshness = self.frame_freshness_monitor.observe(
                image, observed_at=captured_at
            )
            freshness = self.latest_frame_freshness
            digest = freshness.frame_id
            now = time.monotonic()
            if freshness.independent:
                self.last_frame_hash = digest
                self.last_change_at = now
                self.heartbeat_status.set("Mudança visual relevante; quadro novo disponível para análise")
            elif digest != self.last_frame_hash:
                self.last_frame_hash = digest
                self.heartbeat_status.set(
                    "Variação visual abaixo do limite; não conta como nova leitura OCR"
                )
            else:
                unchanged = int(freshness.unchanged_seconds)
                self.heartbeat_status.set(
                    f"Quadro repetido: sem mudança visual há {unchanged}s; novos sinais bloqueados"
                    if freshness.frozen else "Quadro repetido; não conta como nova leitura OCR"
                )
            self.latest_capture_quality_valid = (
                self.latest_frame_quality.usable and not freshness.frozen
            )
            self.latest_capture_block_reason = (
                "; ".join(self.latest_frame_quality.reasons)
                if not self.latest_frame_quality.usable
                else f"captura sem mudança relevante há {freshness.unchanged_seconds:.1f} s"
                if freshness.frozen else ""
            )
            if freshness.independent:
                accepted_frame = self.latest_capture_quality_valid
                self._record_capture_journal_event(
                    "CAPTURE_FRAME_ACCEPTED" if accepted_frame else "CAPTURE_FRAME_REJECTED",
                    {
                        "frame_id": freshness.frame_id,
                        "change_sequence": freshness.change_sequence,
                        "changed_fraction": freshness.changed_fraction,
                        "width": image.width,
                        "height": image.height,
                        "usable": self.latest_frame_quality.usable,
                        "reasons": list(self.latest_frame_quality.reasons),
                        "capture_profile_id": self.active_signal_profile_id,
                        "timeframe": self.timeframe_var.get(),
                    },
                    idempotency_key=(
                        f"{self.capture_session_id}:frame:{freshness.frame_id}"
                    ),
                    occurred_at_utc=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                )
            elif freshness.frozen:
                self._record_capture_journal_event(
                    "CAPTURE_FRAME_REJECTED",
                    {
                        "frame_id": freshness.frame_id,
                        "change_sequence": freshness.change_sequence,
                        "reason": "FRAME_FROZEN",
                        "freeze_after_seconds": self.frame_freshness_monitor.freeze_after_seconds,
                        "capture_profile_id": self.active_signal_profile_id,
                        "timeframe": self.timeframe_var.get(),
                    },
                    idempotency_key=(
                        f"{self.capture_session_id}:frozen:{freshness.frame_id}"
                    ),
                    occurred_at_utc=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                )
            if not self.latest_capture_quality_valid:
                reasons = self.latest_capture_block_reason or "qualidade da captura insuficiente"
                self.last_candidates = []
                self.candidate_lifecycle_by_id.clear()
                self.candidate_fingerprint_by_id.clear()
                self.candidate_related_by_id.clear()
                self.candidate_duplicate_count_by_id.clear()
                self.latest_candidates_at = None
                self.signal_label_counts = {"BUY": 0, "SELL": 0}
                self.signal_label_context_at = None
                self.market_context_regime = "unknown"
                self.market_context_direction = None
                self.market_context_at = None
                self.latest_candle_bars = []
                self._update_candidate_table([])
                self._cancel_auto_pending_for_context()
                self.market_context_display_text = f"Captura não analisada: {reasons}"
                self._refresh_market_context_status()
                self.ocr_status.set(f"OCR bloqueado por qualidade da captura: {reasons}")
            else:
                freshness = self.latest_frame_freshness
                if (
                    freshness is not None
                    and freshness.independent
                    and freshness.change_sequence != self.last_context_change_sequence
                    and self._context_future is None
                    and now - self.last_context_at >= CONTEXT_INTERVAL_SECONDS
                ):
                    self._submit_context_frame(image, captured_at)
                if (
                    self.detector is not None
                    and freshness is not None
                    and not freshness.frozen
                    and freshness.change_sequence != self.last_ocr_change_sequence
                    and self._ocr_future is None
                    and now - self.last_ocr_at >= OCR_INTERVAL_SECONDS
                ):
                    self._submit_ocr_frame(image, captured_at)
                if (
                    self.detector is not None
                    and freshness is not None
                    and not freshness.frozen
                    and self._clock_future is None
                    and now - self.last_clock_submit_at >= CLOCK_INTERVAL_SECONDS
                ):
                    self._submit_clock_frame(image, captured_at)
            self._update_timer_status(now)
            self._update_sequence_recording(image, now)
            self._show_preview(image)
            self.capture_status.set(f"Captura ativa · {image.width}×{image.height} px · até 4 quadros/s")
        except Exception as exc:
            self._stop_capture(f"Erro de captura: {exc}")
            if self.state() == "iconic":
                self.deiconify()
            messagebox.showerror(APP_NAME, f"A captura foi interrompida:\n{exc}", parent=self)
            return
        self.after(POLL_MS, self._capture_tick)

    def _submit_ocr_frame(self, image: Image.Image, captured_at: float) -> None:
        detector = self.detector
        if detector is None or self._ocr_future is not None:
            return
        self.last_ocr_at = captured_at
        self._ocr_frame_captured_at = captured_at
        self._ocr_frame_captured_utc = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        self._ocr_frame_id = (
            self.latest_frame_freshness.frame_id
            if self.latest_frame_freshness is not None else None
        )
        self._ocr_frame_quality = (
            asdict(self.latest_frame_quality) if self.latest_frame_quality is not None else None
        )
        if self.latest_frame_freshness is not None:
            if self._ocr_frame_quality is None:
                self._ocr_frame_quality = {}
            self._ocr_frame_quality["freshness"] = asdict(self.latest_frame_freshness)
            self.last_ocr_change_sequence = self.latest_frame_freshness.change_sequence
        self._ocr_future_generation = self._capture_generation
        color_map = self._active_candle_color_direction_map()
        self._ocr_future = self._ocr_executor.submit(
            _analyze_ocr_frame,
            detector,
            image.copy(),
            dict(color_map) if color_map else None,
            False,
            self.data_dir / "screenshots",
            self.label_age_reference,
        )
        self.after(50, self._poll_ocr_result)

    def _submit_clock_frame(self, image: Image.Image, captured_at: float) -> None:
        """Lê a faixa do relógio em paralelo, fora do caminho crítico dos rótulos."""
        detector = self.detector
        if detector is None or self._clock_future is not None:
            return
        self.last_clock_submit_at = captured_at
        self._clock_frame_captured_at = captured_at
        self._clock_future_generation = self._capture_generation
        self._clock_future = self._clock_executor.submit(
            detector.detect_clock, image.copy()
        )
        self.after(50, self._poll_clock_result)

    def _poll_clock_result(self) -> None:
        if self._closing:
            return
        future = self._clock_future
        if future is None:
            return
        if not future.done():
            self.after(50, self._poll_clock_result)
            return

        captured_at = self._clock_frame_captured_at
        generation = self._clock_future_generation
        self._clock_future = None
        self._clock_frame_captured_at = None
        if future.cancelled():
            return
        if not self.running or generation != self._capture_generation or captured_at is None:
            return
        try:
            clock = future.result()
        except Exception as exc:
            self.latest_clock_ocr_text = f"clock:{type(exc).__name__}"
            return

        now = time.monotonic()
        reading_age = now - captured_at
        self.last_clock_reading_seconds = reading_age
        if clock is None:
            # Sem leitura válida, o relógio existente envelhece naturalmente e o
            # portão de 1,5 s passa a bloquear sinais. Nada é inventado aqui.
            detector = self.detector
            self.latest_clock_ocr_text = detector.last_clock_ocr_text if detector else ""
            probe = getattr(detector, "last_clock_probe", None)
            if probe:
                detector.last_clock_probe = None
                if not probe.get("time_tokens") and not probe.get("clock_words"):
                    self.clock_probe_hint = (
                        "HORA ATUAL não encontrada na área capturada; selecione a região "
                        "incluindo a barra do relógio da plataforma."
                    )
                else:
                    self.clock_probe_hint = None
                self._record_capture_journal_event(
                    "CLOCK_PROBE",
                    probe,
                    idempotency_key=(
                        f"{self.capture_session_id}:clock-probe:"
                        f"{detector.clock_probe_serial}"
                    ),
                    occurred_at_utc=datetime.now(timezone.utc).isoformat(
                        timespec="milliseconds"
                    ),
                    source="CLOCK_PROBE",
                )
            self._update_timer_status(now)
            return
        if reading_age > TIMER_MAX_AGE_SECONDS:
            self._update_timer_status(now)
            return

        self.latest_platform_clock = clock
        self.latest_clock_at = captured_at
        self.latest_clock_ocr_text = (
            self.detector.last_clock_ocr_text if self.detector else ""
        )
        self._observe_pending_platform_minute()
        self._update_timer_status(now)

    def _submit_context_frame(self, image: Image.Image, captured_at: float) -> None:
        if self._context_future is not None:
            return
        self.last_context_at = captured_at
        self._context_frame_captured_at = captured_at
        if self.latest_frame_freshness is not None:
            self.last_context_change_sequence = self.latest_frame_freshness.change_sequence
        self._context_future_generation = self._capture_generation
        color_map = self._active_candle_color_direction_map()
        self._context_future = self._context_executor.submit(
            _analyze_market_context_frame,
            image.copy(),
            color_map if color_map else None,
        )
        self.after(50, self._poll_context_result)

    def _poll_context_result(self) -> None:
        if self._closing:
            return
        future = self._context_future
        if future is None:
            return
        if not future.done():
            self.after(50, self._poll_context_result)
            return

        captured_at = self._context_frame_captured_at
        generation = self._context_future_generation
        self._context_future = None
        self._context_frame_captured_at = None
        if future.cancelled():
            return
        if not self.running or generation != self._capture_generation or captured_at is None:
            return
        frame_age = time.monotonic() - captured_at
        if classify_frame_rejection(
            frame_age,
            max_age_seconds=TIMER_MAX_AGE_SECONDS,
            quality_fresh=self._capture_quality_is_fresh(),
        ) is not None:
            self.last_context_change_sequence = None
            self.latest_candle_bars = []
            self.market_context_regime = "unknown"
            self.market_context_direction = None
            self.market_context_at = None
            self._cancel_auto_pending_for_context()
            self.market_context_display_text = (
                f"Contexto visual: análise atrasada ({frame_age:.1f} s); aguardando quadro recente."
            )
            self._refresh_market_context_status()
            return
        try:
            bars, market_context = future.result()
        except Exception as exc:
            self.latest_candle_bars = []
            self.market_context_regime = "unknown"
            self.market_context_direction = None
            self.market_context_at = None
            self._cancel_auto_pending_for_context()
            self.market_context_display_text = f"Contexto visual indisponível: {exc}"
            self._refresh_market_context_status()
            return

        self.latest_candle_bars = bars
        self.latest_bar_count = len(bars)
        self.market_context_regime = market_context.regime
        self.market_context_direction = market_context.direction
        self.market_context_at = captured_at
        self.market_context_display_text = market_context.display_text
        self._refresh_market_context_status()
        self._cancel_auto_pending_for_context()

    def _poll_ocr_result(self) -> None:
        if self._closing:
            return
        future = self._ocr_future
        if future is None:
            return
        if not future.done():
            self.after(50, self._poll_ocr_result)
            return

        captured_at = self._ocr_frame_captured_at
        captured_utc = self._ocr_frame_captured_utc
        frame_id = self._ocr_frame_id
        frame_quality = self._ocr_frame_quality
        generation = self._ocr_future_generation
        self._ocr_future = None
        self._ocr_frame_captured_at = None
        self._ocr_frame_captured_utc = None
        self._ocr_frame_id = None
        self._ocr_frame_quality = None
        if future.cancelled():
            return
        try:
            result = future.result()
        except Exception as exc:
            if self.running and generation == self._capture_generation:
                if frame_id is not None:
                    self._record_capture_journal_event(
                        "OCR_FAILED",
                        {"frame_id": frame_id, "error_type": type(exc).__name__},
                        idempotency_key=f"{self.capture_session_id}:ocr-failed:{frame_id}",
                        occurred_at_utc=captured_utc,
                        source="OCR_ENGINE",
                    )
                self._handle_ocr_failure(exc)
            return
        if not self.running or generation != self._capture_generation or captured_at is None:
            return

        now = time.monotonic()
        frame_age = now - captured_at
        rejection = classify_frame_rejection(
            frame_age,
            max_age_seconds=TIMER_MAX_AGE_SECONDS,
            quality_fresh=self._capture_quality_is_fresh(),
        )
        if rejection is not None:
            if frame_id is not None:
                self._record_capture_journal_event(
                    "OCR_FAILED",
                    {
                        "frame_id": frame_id,
                        "reason": rejection.reason,
                        "stale": rejection.stale,
                        "quality_invalid": rejection.quality_invalid,
                        "processing_age_seconds": frame_age,
                        "max_age_seconds": TIMER_MAX_AGE_SECONDS,
                        "ocr_timings": result[-1] if isinstance(result, tuple) else None,
                        "ocr_yield": summarize_ocr_yield(result),
                        "clock_ocr_text": self.latest_clock_ocr_text[:200],
                        "clock_age_seconds": (
                            now - self.latest_clock_at
                            if self.latest_clock_at is not None else None
                        ),
                    },
                    idempotency_key=f"{self.capture_session_id}:ocr-stale:{frame_id}",
                    occurred_at_utc=captured_utc,
                    source="OCR_ENGINE",
                )
            self.last_ocr_change_sequence = None
            # O relógio pertence ao leitor dedicado; descartar este quadro não
            # invalida a última leitura, que expira pelo próprio limite de idade.
            self.last_candidates = []
            self.candidate_lifecycle_by_id.clear()
            self.candidate_fingerprint_by_id.clear()
            self.candidate_related_by_id.clear()
            self.candidate_duplicate_count_by_id.clear()
            self.latest_candidates_at = None
            self.signal_label_counts = {"BUY": 0, "SELL": 0}
            self.signal_label_context_at = None
            self._refresh_market_context_status()
            self.demo_signal_guard.observe([])
            self._update_candidate_table([])
            pending = self.simulation.pending
            if self.demo_automation_enabled and pending is not None:
                self.demo_signal_guard.mark_consumed(pending.direction, pending.x, pending.y)
                self._cancel_pending_simulation()
                self.demo_status.set(
                    "Sinal automático cancelado: a leitura OCR ficou desatualizada; nenhum clique foi enviado."
                )
            self.ocr_status.set(
                f"OCR atrasado ({frame_age:.1f} s); quadro descartado para evitar sinais defasados."
            )
            self._cancel_auto_pending_for_context()
            self._update_timer_status(now)
            return

        (
            self.last_candidates,
            frame_clock,
            raw_candidate_count,
            color_rejected_count,
            self.latest_bar_count,
            frame_clock_ocr_text,
            self.signal_label_counts,
            raw_candidates,
            ocr_timings,
            candidate_label_ages,
            candidate_market_candles,
            label_geometry,
        ) = result
        self.latest_candidates_at = captured_at
        # Passa todas as caixas OCR ao reconciliador central; a deduplicação e a
        # contagem de caixas concorrentes são responsabilidade de uma única camada.
        if not captured_utc or not frame_id:
            self._record_capture_journal_event(
                "OCR_FAILED",
                {"reason": "MISSING_FRAME_ID_OR_CAPTURE_TIMESTAMP"},
                idempotency_key=f"{self.capture_session_id}:ocr-metadata-missing:{captured_at}",
                occurred_at_utc=captured_utc,
                source="OCR_ENGINE",
            )
            self.signal_tracking_persistence_healthy = False
            self.last_candidates = []
            self.candidate_lifecycle_by_id.clear()
            self.candidate_fingerprint_by_id.clear()
            self.candidate_related_by_id.clear()
            self.candidate_duplicate_count_by_id.clear()
            self.latest_candidates_at = None
            self._update_candidate_table([])
            self.research_status.set(
                "Leitura descartada: timestamp UTC ou identidade do quadro ausente; simulação bloqueada."
            )
            return
        observed_at_utc = captured_utc
        tracked_signals = self.signal_lifecycle.observe(
            list(raw_candidates),
            observed_at=captured_at,
            frame_id=frame_id,
            observed_at_utc=observed_at_utc,
        )
        self.candidate_lifecycle_by_id = {
            self._candidate_row_id(item.candidate): item.lifecycle
            for item in tracked_signals
        }
        self.candidate_fingerprint_by_id = {
            self._candidate_row_id(item.candidate): item.tracking_id
            for item in tracked_signals
        }
        self.candidate_related_by_id = {
            self._candidate_row_id(item.candidate): item.related_tracking_id
            for item in tracked_signals
        }
        self.candidate_duplicate_count_by_id = {
            self._candidate_row_id(item.candidate): item.duplicate_count
            for item in tracked_signals
        }
        tracked_candidates = [item.candidate for item in tracked_signals]
        self.signal_label_context_at = captured_at
        # O relógio tem leitor próprio. Um quadro de rótulos só atualiza o relógio
        # quando a passada geral o leu de fato; caso contrário preserva a última
        # leitura válida, cuja idade continua checada pelo limite de 1,5 s.
        if frame_clock is not None:
            self.latest_platform_clock = frame_clock
            self.latest_clock_at = captured_at
            self.latest_clock_ocr_text = frame_clock_ocr_text
        # Caso contrário, preserva o diagnóstico do leitor dedicado do relógio, que
        # é o único que descreve o que a faixa do rodapé realmente continha.
        self._refresh_market_context_status()
        self._cancel_auto_pending_for_context()
        self._observe_pending_platform_minute()
        self.demo_signal_guard.observe(self.last_candidates)
        self._update_ocr_status(
            self.last_candidates,
            raw_candidate_count,
            self.latest_bar_count,
            color_rejected_count,
            candidate_label_ages,
            candidate_market_candles,
        )
        self._record_ocr_opportunities(
            tracked_candidates,
            self.last_candidates,
            captured_at=captured_at,
            captured_utc=captured_utc,
            frame_quality=frame_quality,
            processing_age=frame_age,
        )
        if self.capture_session_id is not None:
            self._record_capture_journal_event(
                "OCR_COMPLETED",
                {
                    "frame_id": frame_id,
                    "processing_age_seconds": frame_age,
                    "raw_candidate_count": raw_candidate_count,
                    "recent_candidate_count": len(self.last_candidates),
                    "tracked_candidate_count": len(tracked_candidates),
                    "color_rejected_count": color_rejected_count,
                    "clock_readable": self.latest_platform_clock is not None,
                    "capture_profile_id": self.active_signal_profile_id,
                    "grade": {
                        "code": self.grade_code,
                        "method": GRADE_METHOD,
                        "criteria_hash": self.grade_criteria_hash(),
                        "reasons": list(self.grade_reasons),
                        "features": self.grade_features,
                        "context_regime": self.market_context_regime,
                        "context_direction": self.market_context_direction,
                    },
                    "eligibility": {
                        "code": self.eligibility_code,
                        "criteria_hash": self.eligibility_hash,
                        "text": self.eligibility_text[:200],
                    },
                    "association": {
                        "code": self.association_code,
                        "raw_count": raw_candidate_count,
                        "recent_count": len(self.last_candidates),
                        "bar_count": self.latest_bar_count,
                        "palette_calibrated": bool(self._active_candle_color_direction_map()),
                        "age_reference": self.label_age_reference,
                        "label_age_bars": (
                            candidate_label_ages[-1]
                            if candidate_label_ages else None
                        ),
                        "label_geometry": label_geometry,
                    },
                    "ocr_timings": ocr_timings,
                    "clock_ocr_text": self.latest_clock_ocr_text[:200],
                    "clock_age_seconds": (
                        now - self.latest_clock_at
                        if self.latest_clock_at is not None else None
                    ),
                },
                idempotency_key=f"{self.capture_session_id}:ocr-completed:{frame_id}",
                occurred_at_utc=captured_utc,
                source="OCR_ENGINE",
            )
        self._maybe_auto_arm_demo_signal()
        self._update_timer_status(now)

    def _record_ocr_opportunities(
        self,
        raw_candidates: list[SignalCandidate],
        recent_candidates: list[SignalCandidate],
        *,
        captured_at: float,
        captured_utc: str | None,
        frame_quality: dict[str, object] | None,
        processing_age: float,
    ) -> None:
        accepted = {
            (item.direction, item.left, item.top, item.observed_text)
            for item in recent_candidates
        }
        context_age = (
            captured_at - self.market_context_at
            if self.market_context_at is not None else None
        )
        synchronized_context = (
            context_age is not None and 0 <= context_age <= TIMER_MAX_AGE_SECONDS
        )
        freshness = frame_quality.get("freshness") if isinstance(frame_quality, dict) else None
        frame_id = freshness.get("frame_id") if isinstance(freshness, dict) else None
        market_features: dict[str, object] = {
            "visual_regime": self.market_context_regime if synchronized_context else None,
            "visual_direction": self.market_context_direction if synchronized_context else None,
            "visual_context_age_seconds": context_age,
            "signal_label_counts": dict(self.signal_label_counts),
            "detected_candles": self.latest_bar_count,
            "ocr_processing_age_seconds": processing_age,
            "platform_clock_text": self.latest_platform_clock.text if self.latest_platform_clock else None,
            "platform_clock_confidence": self.latest_platform_clock.confidence if self.latest_platform_clock else None,
            "platform_clock_source": "OCR_SCREEN_LABEL" if self.latest_platform_clock else None,
            "platform_clock_capture_at_utc": (
                captured_utc if self.latest_platform_clock is not None else None
            ),
            "capture_profile_id": self.active_signal_profile_id,
            "frame_id": frame_id,
            "detector_version": "ocr-labels-v1",
        }
        observed_at = captured_utc or datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        tracks_by_id = {
            str(track["tracking_id"]): track
            for track in self.signal_lifecycle.export_state()
        }
        for candidate in raw_candidates:
            is_recent = (
                candidate.direction,
                candidate.left,
                candidate.top,
                candidate.observed_text,
            ) in accepted
            candidate_id = self._candidate_row_id(candidate)
            tracking_id = self.candidate_fingerprint_by_id.get(candidate_id)
            lifecycle = self.candidate_lifecycle_by_id.get(candidate_id)
            track = tracks_by_id.get(tracking_id or "")
            fingerprint = tracking_id or hashlib.sha256(
                f"indeterminate:{self.active_signal_profile_id}:{self.timeframe_var.get()}:"
                f"{observed_at}:{candidate.direction}:{candidate.left}:{candidate.top}:"
                f"{candidate.observed_text}".encode("utf-8")
            ).hexdigest()
            features = dict(market_features)
            features.update({
                "recent_candle_association": is_recent,
                "signal_lifecycle": lifecycle.value if lifecycle is not None else "INDETERMINATE",
                "tracking_id": tracking_id,
                "related_tracking_id": self.candidate_related_by_id.get(candidate_id),
                "first_seen_at_utc": track.get("first_seen_at_utc") if track else observed_at,
                "consecutive_observations": track.get("consecutive_observations") if track else 0,
                "missing_observations": track.get("missing_observations") if track else 0,
                "duplicate_count": self.candidate_duplicate_count_by_id.get(candidate_id, 0),
                "candidate_box": {
                    "left": candidate.left, "top": candidate.top,
                    "width": candidate.width, "height": candidate.height,
                },
                "asset": None,
            })
            try:
                opportunity_id, is_new = self.opportunity_store.record_signal(
                    fingerprint=fingerprint,
                    opportunity_id=tracking_id,
                    mode=self.operation_mode.value,
                    direction=candidate.direction,
                    ocr_text=candidate.observed_text,
                    ocr_confidence=candidate.confidence,
                    signal_at_utc=observed_at,
                    timeframe=self.timeframe_var.get(),
                    frame_quality=frame_quality,
                    market_features=features,
                )
                if is_new:
                    rejection_reasons: list[str] = []
                    if not is_recent:
                        rejection_reasons.append("SINAL_NAO_ASSOCIADO_A_UMA_DAS_DUAS_VELAS_RECENTES")
                    if lifecycle is SignalLifecycle.PREEXISTING:
                        rejection_reasons.append("ROTULO_JA_PRESENTE_NA_LINHA_DE_BASE")
                    elif lifecycle in {
                        SignalLifecycle.INDETERMINATE,
                        SignalLifecycle.REPINTED,
                        SignalLifecycle.ALTERED,
                        SignalLifecycle.DIRECTION_CHANGED,
                        SignalLifecycle.EXPIRED,
                        SignalLifecycle.DUPLICATE,
                    } or lifecycle is None:
                        rejection_reasons.append("IDENTIDADE_OU_ESTADO_DO_SINAL_INDETERMINADO")
                    if self.candidate_duplicate_count_by_id.get(candidate_id, 0):
                        rejection_reasons.append("MULTIPLAS_CAIXAS_OCR_COMPATIVEIS_NO_MESMO_QUADRO")
                    if rejection_reasons:
                        self.opportunity_store.record_decision(
                            opportunity_id,
                            approved=False,
                            source="PERCEPTION_GATES",
                            reasons=rejection_reasons,
                            filters={
                                "recent_candle_association": is_recent,
                                "signal_lifecycle": lifecycle.value if lifecycle is not None else "INDETERMINATE",
                                "frame_id": frame_id,
                            },
                            market_features=features,
                        )
            except Exception as exc:
                self.signal_tracking_persistence_healthy = False
                self.research_status.set(
                    f"Falha no journal de oportunidades; simulação bloqueada: {exc}"
                )
                return

        if self.active_signal_profile_id is None:
            self.signal_tracking_persistence_healthy = False
            self.research_status.set(
                "Perfil de captura ausente; identidade persistente e simulação bloqueadas."
            )
            return
        try:
            self.opportunity_store.save_signal_tracks(
                profile_id=self.active_signal_profile_id,
                timeframe=self.timeframe_var.get(),
                tracks=self.signal_lifecycle.export_state(),
            )
        except Exception as exc:
            self.signal_tracking_persistence_healthy = False
            self.research_status.set(
                f"Falha ao persistir o ciclo de vida; simulação bloqueada: {exc}"
            )
            return

        # A confirmação OCR por si só não é elegibilidade. A promoção abaixo é
        # apenas para hipótese manual de SIMULAÇÃO e exige associação geométrica
        # recente, quadro fresco e ausência de duplicatas no mesmo frame.
        promoted = False
        for candidate in recent_candidates:
            candidate_id = self._candidate_row_id(candidate)
            tracking_id = self.candidate_fingerprint_by_id.get(candidate_id)
            if (
                self.operation_mode is OperationMode.SIMULATION
                and tracking_id is not None
                and self.candidate_lifecycle_by_id.get(candidate_id) is SignalLifecycle.CONFIRMED
                and self.candidate_duplicate_count_by_id.get(candidate_id, 0) == 0
                and self._capture_quality_is_fresh()
                and self.signal_lifecycle.mark_eligible(tracking_id)
            ):
                promoted = True
                self.candidate_lifecycle_by_id[candidate_id] = SignalLifecycle.ELIGIBLE
                if self.operation_mode is OperationMode.SIMULATION:
                    try:
                        opportunity_id, _ = self.opportunity_store.record_signal(
                            fingerprint=tracking_id,
                            opportunity_id=tracking_id,
                            mode=self.operation_mode.value,
                            direction=candidate.direction,
                            ocr_text=candidate.observed_text,
                            ocr_confidence=candidate.confidence,
                            signal_at_utc=observed_at,
                            timeframe=self.timeframe_var.get(),
                            frame_quality=frame_quality,
                            market_features={
                                "tracking_id": tracking_id,
                                "signal_lifecycle": SignalLifecycle.ELIGIBLE.value,
                                "recent_candle_association": True,
                                "frame_id": frame_id,
                                "asset": None,
                            },
                        )
                        self.opportunity_store.record_decision(
                            opportunity_id,
                            approved=False,
                            source="SIMULATION_SAFETY_GATE",
                            reasons=["SETUP_ESTRATEGICO_E_DADOS_DE_RISCO_NAO_IMPLEMENTADOS"],
                            filters={
                                "signal_lifecycle": SignalLifecycle.ELIGIBLE.value,
                                "recent_candle_association": True,
                                "frame_id": frame_id,
                            },
                        )
                    except Exception as exc:
                        self.signal_tracking_persistence_healthy = False
                        self.research_status.set(
                            f"Falha ao registrar gate de simulação; armamento bloqueado: {exc}"
                        )
                        return
        if promoted:
            try:
                self.opportunity_store.save_signal_tracks(
                    profile_id=self.active_signal_profile_id,
                    timeframe=self.timeframe_var.get(),
                    tracks=self.signal_lifecycle.export_state(),
                )
            except Exception as exc:
                self.signal_tracking_persistence_healthy = False
                self.research_status.set(
                    f"Falha ao persistir elegibilidade; simulação bloqueada: {exc}"
                )
                return
            self._update_candidate_table(self.last_candidates)
        if raw_candidates:
            self.research_status.set(
                f"Journal: {len(raw_candidates)} rótulo(s) reconciliado(s); "
                f"{len(recent_candidates)} associado(s) às velas mais recentes. "
                "Ativo e dados financeiros não disponíveis. "
                f"Elegibilidade: {self._eligibility_status_text()}."
            )

    def _eligibility_status_text(self) -> str:
        """Mostra o estado real da elegibilidade sem sugerir que já existe regra."""
        decision = evaluate_eligibility(
            self.eligibility_criteria,
            {
                "confidence": None,
                "direction": None,
                "palette_calibrated": bool(self._active_candle_color_direction_map()),
                "bar_count": self.latest_bar_count,
                "label_age_bars": None,
                "context_direction": self.market_context_direction,
            },
        )
        if decision.code == "CRITERIA_UNDEFINED":
            return "critérios não definidos (falha fechada)"
        return decision.code

    def _handle_ocr_failure(self, exc: Exception) -> None:
        if self.demo_automation_enabled:
            self._toggle_demo_automation()
        self.detector = None
        self.latest_platform_clock = None
        self.latest_clock_at = None
        self.latest_clock_ocr_text = ""
        self.last_candidates = []
        self.candidate_lifecycle_by_id.clear()
        self.candidate_fingerprint_by_id.clear()
        self.candidate_related_by_id.clear()
        self.candidate_duplicate_count_by_id.clear()
        self.latest_candidates_at = None
        self.signal_label_counts = {"BUY": 0, "SELL": 0}
        self.signal_label_context_at = None
        self._refresh_market_context_status()
        self.demo_signal_guard.observe([])
        self._update_candidate_table([])
        self.ocr_status.set(f"OCR interrompido por erro: {exc}")
        self._update_timer_status()
        self._stop_sequence_recording("parada por falha de OCR")

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
                clock_ocr_excerpt=self.latest_clock_ocr_text,
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
        self,
        candidates: list[SignalCandidate],
        raw_count: int = 0,
        candle_count: int = 0,
        color_rejected_count: int = 0,
        label_ages: list[int | None] | None = None,
        market_candles: list | None = None,
    ) -> None:
        self._update_candidate_table(candidates)
        self.association_code, self.association_text = classify_association_outcome(
            raw_count=raw_count,
            recent_count=len(candidates),
            color_rejected_count=color_rejected_count,
            bar_count=candle_count,
            palette_calibrated=bool(self._active_candle_color_direction_map()),
        )
        self._evaluate_candidates(candidates, label_ages)
        self._grade_candidates(candidates, label_ages, market_candles, raw_count)
        if not candidates:
            self.ocr_status.set(
                f"OCR viu {raw_count} etiqueta(s); {self.association_text}"
            )
            return
        summary = " | ".join(
            f"{'COMPRA' if item.direction == 'BUY' else 'VENDER'} {item.confidence:.0f}% "
            f"(OCR: {item.observed_text}) em ({item.left},{item.top})"
            for item in candidates[:4]
        )
        if len(candidates) > 4:
            summary += f" | +{len(candidates) - 4}"
        if color_rejected_count:
            summary += f" · {color_rejected_count} rótulo(s) bloqueado(s) por conflito de cor"
        eligibility_note = ""
        if self.eligibility_code != "ASSOCIATED":
            eligibility_note = f" · elegibilidade: {self.eligibility_text}"
        grade_note = f" · {self.grade_text}" if self.grade_text else ""
        self.ocr_status.set(
            f"Candidato(s) nas velas mais recentes — revise: {summary} "
            f"(OCR bruto: {raw_count}; barras detectadas: {candle_count})"
            f"{grade_note}{eligibility_note}"
        )

    def grade_criteria_hash(self) -> str:
        payload = json.dumps(self.grade_criteria.as_dict(), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def _grade_candidates(
        self,
        candidates: list[SignalCandidate],
        label_ages: list[int | None] | None,
        market_candles: list | None,
        raw_candidate_count: int | None = None,
    ) -> None:
        """Classifica o momento usando só o que a tela permite medir.

        RSI, histograma MACD e distância à EMA20 não são legíveis por pixel; a
        classificação registra isso explicitamente em vez de assumir valores.
        """
        if not candidates:
            # Distinguir "não havia rótulo" de "havia rótulo, mas fora da janela
            # recente" evita tratar filtro estrito como se fosse falta de sinal.
            if raw_candidate_count:
                self.grade_code = "LABEL_OUTSIDE_WINDOW"
                self.grade_text = (
                    f"rótulo lido, mas fora das duas últimas velas "
                    f"({raw_candidate_count} no quadro)"
                )
            else:
                self.grade_code = "NO_LABEL"
                self.grade_text = "nenhum rótulo no quadro"
            self.grade_reasons = ()
            self.grade_features = None
            return
        ages = list(label_ages or [])
        latest = candidates[-1]
        age = ages[-1] if ages else None
        features = build_features(
            latest,
            self.latest_candle_bars,
            list(market_candles or []),
            direction=latest.direction,
            age_bars=age,
            context_regime=self.market_context_regime,
            context_direction=self.market_context_direction,
        )
        grade = grade_opportunity(features, self.grade_criteria)
        self.grade_code = grade.code
        self.grade_text = grade.display_text
        self.grade_reasons = grade.reasons
        self.grade_features = features.as_dict() if features is not None else None

    def _evaluate_candidates(
        self, candidates: list[SignalCandidate], label_ages: list[int | None] | None
    ) -> None:
        """Avalia elegibilidade sem liberar nada: o resultado é sempre para revisão.

        Guarda o código do candidato mais recente para o status e para o journal; um
        bloqueio em qualquer candidato não é mascarado por outro mais permissivo.
        """
        if not candidates:
            self.eligibility_code = "NO_CANDIDATE"
            self.eligibility_text = "sem candidato associado a vela recente"
            self.eligibility_hash = self.eligibility_criteria.criteria_hash()
            return
        ages = list(label_ages or [])
        decisions = []
        for index, candidate in enumerate(candidates):
            age = ages[index] if index < len(ages) else None
            decisions.append(
                evaluate_eligibility(
                    self.eligibility_criteria,
                    self._eligibility_observation(candidate, age),
                )
            )
        best = decisions[-1]
        self.eligibility_code = best.code
        self.eligibility_text = (
            best.display_text if not best.eligible else best.display_text
        )
        self.eligibility_hash = best.criteria_hash

    @staticmethod
    def _candidate_row_id(candidate: SignalCandidate) -> str:
        center_x = candidate.left + candidate.width // 2
        center_y = candidate.top + candidate.height // 2
        text_key = hashlib.sha256(
            "".join(char for char in candidate.observed_text.upper() if char.isalnum())
            .encode("utf-8")
        ).hexdigest()[:10]
        # Fine-grained bins avoid merging distinct same-direction labels; the
        # lifecycle reconciler separately tolerates coordinate jitter.
        return f"{candidate.direction}-{text_key}-{center_x // 6}-{center_y // 6}"

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
            lifecycle = self.candidate_lifecycle_by_id.get(item_id)
            lifecycle_label = {
                SignalLifecycle.PREEXISTING: "PREEXISTENTE · visível na linha de base",
                SignalLifecycle.NEWLY_DETECTED: "NOVO NA SESSÃO · 1/3 quadros distintos",
                SignalLifecycle.PENDING_CONFIRMATION: "EM CONFIRMAÇÃO · 2/3 quadros distintos",
                SignalLifecycle.CONFIRMED: "CONFIRMADO VISUALMENTE · vela não comprovada",
                SignalLifecycle.ELIGIBLE: "ELEGÍVEL PARA ANÁLISE · não é autorização de ordem",
                SignalLifecycle.EXPIRED: "EXPIRADO",
                SignalLifecycle.CANCELLED: "CANCELADO",
                SignalLifecycle.DUPLICATE: "DUPLICADO",
                SignalLifecycle.ALTERED: "ALTERADO · identidade incerta",
                SignalLifecycle.REPINTED: "REPINTADO · bloqueado",
                SignalLifecycle.DIRECTION_CHANGED: "DIREÇÃO ALTERADA · bloqueado",
                SignalLifecycle.INDETERMINATE: "INDETERMINADO · bloqueado",
            }.get(lifecycle, "IDADE INCERTA")
            duplicate_count = self.candidate_duplicate_count_by_id.get(item_id, 0)
            if duplicate_count:
                lifecycle_label += f" · {duplicate_count} duplicata(s) OCR neste quadro"
            values = (f"{label} ({candidate.observed_text}) · {lifecycle_label}", f"{candidate.confidence:.0f}%",
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
                APP_NAME, "Pare os cliques automáticos antes de limpar o log.", parent=self
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
                    row_status = f"Automática · atraso {source} {delay}s{arm_note}"
                else:
                    row_status = "Automática · clique enviado; atraso não registrado"
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
        platform_clock = (
            f"{clock.hour:02d}:{clock.minute:02d}:{clock.second:02d}" if clock else ""
        )
        armed_clock_text = (
            f"{armed_clock_override.hour:02d}:{armed_clock_override.minute:02d}:"
            f"{armed_clock_override.second:02d}"
            if armed_clock_override is not None else ""
        )
        event_type = {
            "sinal_armado": "SIMULATION_ARMED",
            "simulacao_cancelada": "SIMULATION_CANCELLED",
            "sinal_expirado": "SIMULATION_EXPIRED",
            "virada_minuto_observada": "SIMULATION_CANDLE_ROLLOVER",
            "entrada_simulada": "SIMULATION_CONFIRMED",
        }.get(event)
        journal_error: str | None = None
        if event_type is not None:
            try:
                self.opportunity_store.record_journal_event(
                    event_type,
                    source="SIMULATION_WORKFLOW",
                    session_id=self.capture_session_id,
                    payload={
                        "event": event,
                        "timeframe": self.timeframe_var.get(),
                        "direction": direction,
                        "observed_text": observed_text,
                        "ocr_confidence": confidence,
                        "signal_x": signal_x,
                        "signal_y": signal_y,
                        "platform_clock": platform_clock,
                        "clock_source": clock_source,
                        "elapsed_seconds_m1": elapsed_seconds_m1,
                        "armed_clock": armed_clock_text,
                        "entry_delay_seconds": entry_delay_seconds,
                        "entry_delay_platform_seconds": entry_delay_platform_seconds,
                    },
                )
            except Exception as exc:
                self.signal_tracking_persistence_healthy = False
                journal_error = f"Journal SQLite: {exc}"
        history_error = append_event_best_effort(
            self.simulation_history,
            platform_clock=platform_clock,
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
            armed_clock=armed_clock_text,
            entry_delay_seconds=entry_delay_seconds,
        )
        errors = [item for item in (journal_error, history_error) if item]
        return "; ".join(errors) if errors else None

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
        if self.operation_mode is not OperationMode.SIMULATION:
            self.simulation_status.set(
                "Modo OBSERVAÇÃO: nenhum sinal será armado. Selecione SIMULATION para armar uma hipótese manual."
            )
            return
        if not self.signal_tracking_persistence_healthy:
            self.simulation_status.set(
                "Simulação bloqueada: identidade persistente do sinal/journal indisponível."
            )
            return
        if self.demo_automation_enabled:
            self.simulation_status.set("Com cliques automáticos ativos, os candidatos são armados automaticamente; use Cancelar para abortar.")
            return
        candidate = self.candidates_by_id.get(item_id)
        if (
            candidate is None
            or self.latest_candidates_at is None
            or time.monotonic() - self.latest_candidates_at > TIMER_MAX_AGE_SECONDS
            or not self._capture_quality_is_fresh()
            or self.latest_frame_freshness is None
            or self.latest_frame_freshness.frozen
        ):
            self.simulation_status.set(
                "Candidato bloqueado: leitura ausente, desatualizada ou quadro congelado."
            )
            return
        lifecycle = self.candidate_lifecycle_by_id.get(item_id)
        if lifecycle is not SignalLifecycle.ELIGIBLE:
            self.simulation_status.set(
                "Simulação bloqueada: exige confirmação em três quadros independentes, "
                "associação às velas recentes, qualidade válida e persistência do rastro."
            )
            return
        if self.candidate_duplicate_count_by_id.get(item_id, 0):
            self.simulation_status.set(
                "Simulação bloqueada: múltiplas caixas OCR compatíveis no mesmo quadro."
            )
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
        self.pending_demo_candle_id = None

    def _confirm_next_candle(self) -> None:
        if self.operation_mode is not OperationMode.SIMULATION:
            self.simulation_status.set("Confirmação bloqueada fora do modo SIMULATION.")
            return
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
        self._cancel_scheduled_demo_entry()
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
            demo_clock = self.demo_clock.reading()
            pending = self.simulation.pending
            prefix = "M1 automático · referência temporal somente Windows UTC−3"
            if pending is not None:
                elapsed = platform_clock_elapsed_seconds(self.pending_armed_clock, demo_clock)
                self.timer_status.set(
                    f"{prefix}: {demo_clock.hour:02d}:{demo_clock.minute:02d}:"
                    f"{demo_clock.second:02d}; armamento +{elapsed if elapsed is not None else '—'} s; "
                    f"entrada no segundo :{self.demo_entry_second_active:02d} (até :30)."
                )
            else:
                self.timer_status.set(
                    f"{prefix}: {demo_clock.hour:02d}:{demo_clock.minute:02d}:"
                    f"{demo_clock.second:02d}; clique automático no segundo :{self.demo_entry_second_active:02d}, "
                    "máximo uma tentativa por minuto do Windows, até :30."
                )
            self._refresh_simulation_buttons()
            return

        platform_clock = self.latest_platform_clock
        fresh = (
            self.latest_clock_at is not None
            and observed_at - self.latest_clock_at <= TIMER_MAX_AGE_SECONDS
        )
        if platform_clock is None or not fresh:
            hint = f" {self.clock_probe_hint}" if self.clock_probe_hint else ""
            self.timer_status.set(
                "M1: HORA ATUAL ausente/desatualizada; confirmação e clique bloqueados." + hint
            )
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
                self.demo_status.set("Automação encerrada sem clique: janela M1/N+1 não foi válida.")
            persistence_note = f" Histórico local não gravado: {log_error}" if log_error else ""
            self.simulation_status.set(
                f"Sinal {label} descartado: {expire_reason}; nenhuma entrada enviada."
                f"{persistence_note}"
            )
        self._refresh_simulation_buttons()

    def _on_timeframe_change(self, _event: tk.Event | None = None) -> None:
        if self.demo_automation_enabled and self.timeframe_var.get() != "M1":
            self._toggle_demo_automation()
        if self.running and self.region is not None:
            if self.simulation.pending is not None:
                self._cancel_pending_simulation()
            self.last_candidates = []
            self.candidate_lifecycle_by_id.clear()
            self.candidate_fingerprint_by_id.clear()
            self.candidate_related_by_id.clear()
            self.candidate_duplicate_count_by_id.clear()
            self.latest_candidates_at = None
            self._update_candidate_table([])
            try:
                self._begin_signal_tracking_session()
            except Exception as exc:
                self.signal_tracking_persistence_healthy = False
                self.research_status.set(f"Perfil temporal não reconciliado; simulação bloqueada: {exc}")
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
            preview_width = max(200, self.preview.winfo_width() - 20)
            preview_height = max(150, self.preview.winfo_height() - 20)
            annotated.thumbnail((preview_width, preview_height), Image.Resampling.LANCZOS)
            self.preview_photo = ImageTk.PhotoImage(annotated)
            self.preview.configure(image=self.preview_photo, text="")
        elif self.compact_frame.winfo_viewable():
            compact_width = self.compact_preview_label.winfo_width()
            if compact_width <= 1:
                compact_width = 640
            annotated.thumbnail((min(640, max(240, compact_width - 12)), 220), Image.Resampling.LANCZOS)
            self.compact_preview_photo = ImageTk.PhotoImage(annotated)
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

    def _screen_layout_signature(self) -> list[dict[str, int]]:
        layout = [
            {key: int(monitor[key]) for key in ("left", "top", "width", "height")}
            for monitor in self.monitors
        ]
        return sorted(
            layout,
            key=lambda item: (item["left"], item["top"], item["width"], item["height"]),
        )

    @staticmethod
    def _valid_window_signature(value: object) -> bool:
        if not isinstance(value, dict):
            return False
        process_id = value.get("process_id")
        class_name = value.get("class_name")
        rect = value.get("rect")
        return (
            isinstance(process_id, int) and not isinstance(process_id, bool) and process_id > 0
            and isinstance(class_name, str) and bool(class_name)
            and isinstance(rect, list) and len(rect) == 4
            and all(isinstance(item, int) and not isinstance(item, bool) for item in rect)
            and rect[2] > rect[0] and rect[3] > rect[1]
        )

    def _load_persisted_calibrations(self, config: dict[str, object]) -> None:
        has_saved_calibration = any(
            bool(config.get(key))
            for key in ("excluded_regions", "demo_click_targets", "demo_mouse_keepalive")
        )
        if not has_saved_calibration:
            return
        if config.get("screen_layout") != self._screen_layout_signature():
            self.demo_status.set(
                "Calibrações antigas não restauradas: a disposição dos monitores mudou; "
                "selecione novamente as áreas e calibre os pontos."
            )
            return

        raw_regions = config.get("excluded_regions", [])
        if isinstance(raw_regions, list):
            for value in raw_regions:
                try:
                    region = ScreenRegion.from_dict(value)
                except (TypeError, ValueError, KeyError):
                    continue
                if self.region is not None and self._regions_intersect(region, self.region):
                    self.excluded_regions.append(region)
        self.exclusion_status.set(
            f"{len(self.excluded_regions)} área(s) ocultada(s) restaurada(s)"
            if self.excluded_regions else "nenhuma área ocultada"
        )

        raw_targets = config.get("demo_click_targets", {})
        if isinstance(raw_targets, dict):
            for direction in ("BUY", "SELL"):
                item = raw_targets.get(direction)
                if not isinstance(item, dict):
                    continue
                point = item.get("target")
                signature = item.get("window_signature")
                if not isinstance(point, dict) or not self._valid_window_signature(signature):
                    continue
                try:
                    target = ClickTarget(point.get("x"), point.get("y"))
                except (TypeError, ValueError):
                    continue
                left, top, right, bottom = signature["rect"]
                if not (left <= target.x < right and top <= target.y < bottom):
                    continue
                self.demo_click_targets[direction] = target
                self.demo_click_target_signatures[direction] = signature
                self._set_demo_target_label(direction, target)

        raw_keepalive = config.get("demo_mouse_keepalive")
        if isinstance(raw_keepalive, dict):
            signature = raw_keepalive.get("window_signature")
            if self._valid_window_signature(signature):
                try:
                    point_data = raw_keepalive.get("target")
                    alternate_data = raw_keepalive.get("alternate")
                    if not isinstance(point_data, dict) or not isinstance(alternate_data, dict):
                        raise ValueError("coordenadas ausentes")
                    self.demo_mouse_keepalive_target = ClickTarget(
                        point_data.get("x"), point_data.get("y")
                    )
                    self.demo_mouse_keepalive_alternate = ClickTarget(
                        alternate_data.get("x"), alternate_data.get("y")
                    )
                    left, top, right, bottom = signature["rect"]
                    for saved_point in (
                        self.demo_mouse_keepalive_target,
                        self.demo_mouse_keepalive_alternate,
                    ):
                        if not (left <= saved_point.x < right and top <= saved_point.y < bottom):
                            raise ValueError("ponto neutro fora da janela calibrada")
                    self.demo_mouse_keepalive_signature = signature
                    self.demo_mouse_keepalive_status.set(
                        f"Ponto neutro salvo em {self.demo_mouse_keepalive_target.x},"
                        f"{self.demo_mouse_keepalive_target.y}; será revalidado antes do uso."
                    )
                except (TypeError, ValueError):
                    self.demo_mouse_keepalive_target = None
                    self.demo_mouse_keepalive_alternate = None
                    self.demo_mouse_keepalive_signature = None

        if any(self.demo_click_targets.values()) or self.excluded_regions:
            self.demo_status.set(
                "Calibrações locais restauradas; janela e posição serão revalidadas antes de qualquer movimento/clique."
            )

    def _bind_persisted_demo_windows(self) -> bool:
        """Rebind stored screen points only if the exact calibrated window is still there."""
        rebound: dict[str, int] = {}
        for direction in ("BUY", "SELL"):
            target = self.demo_click_targets[direction]
            expected_signature = self.demo_click_target_signatures[direction]
            if target is None or not self._valid_window_signature(expected_signature):
                return False
            try:
                current_window = windows_window_at_point(target.x, target.y)
                current_signature = windows_window_signature_at_point(target.x, target.y)
            except Exception:
                return False
            if current_window is None or current_signature != expected_signature:
                return False
            rebound[direction] = current_window

        if rebound["BUY"] != rebound["SELL"]:
            return False
        self.demo_click_target_windows.update(rebound)

        neutral = self.demo_mouse_keepalive_target
        neutral_signature = self.demo_mouse_keepalive_signature
        if neutral is not None and self._valid_window_signature(neutral_signature):
            try:
                neutral_window = windows_window_at_point(neutral.x, neutral.y)
                current_signature = windows_window_signature_at_point(neutral.x, neutral.y)
            except Exception:
                neutral_window = None
                current_signature = None
            if (
                neutral_window == rebound["BUY"]
                and current_signature == neutral_signature
                and neutral_signature == self.demo_click_target_signatures["BUY"]
            ):
                self.demo_mouse_keepalive_window = neutral_window
        return True

    def _ocr_floor(self) -> float:
        """Confiança mínima que o detector já aplica antes de qualquer decisão."""
        try:
            return float(self.confidence_var.get())
        except (AttributeError, TypeError, ValueError):
            return 70.0

    def _load_eligibility_criteria(self, payload: object) -> None:
        """Carrega critérios validados; configuração inválida falha fechada.

        Um JSON corrompido ou contraditório não deve virar "sem filtro": nesse caso
        os critérios ficam vazios e nenhum candidato é elegível até correção.
        """
        if payload is None:
            self.eligibility_criteria = BALANCED_CRITERIA
        elif isinstance(payload, dict):
            try:
                criteria = EligibilityCriteria.from_dict(payload)
            except (TypeError, ValueError) as exc:
                self.eligibility_criteria = EligibilityCriteria()
                self.eligibility_problems = [f"critérios inválidos: {exc}"]
                return
            self.eligibility_criteria = criteria
        else:
            self.eligibility_criteria = EligibilityCriteria()
            self.eligibility_problems = ["critérios em formato inesperado"]
            return

        problems = validate_criteria(self.eligibility_criteria, ocr_floor=self._ocr_floor())
        self.eligibility_problems = problems
        if problems:
            # Mantém a decisão bloqueada, mas preserva os valores para exibição.
            self.eligibility_criteria = EligibilityCriteria()

    def _eligibility_observation(self, candidate: SignalCandidate, label_age: int | None) -> dict[str, object]:
        return {
            "confidence": candidate.confidence,
            "direction": candidate.direction,
            "palette_calibrated": bool(self._active_candle_color_direction_map()),
            "bar_count": self.latest_bar_count,
            "label_age_bars": label_age,
            "context_direction": self.market_context_direction,
        }

    def _load_grade_criteria(self, payload: object, version: object = None) -> None:
        """Carrega limiares de classificação; inválido volta ao padrão declarado."""
        if payload is None:
            self.grade_criteria = DEFAULT_GRADE_CRITERIA
            return
        try:
            if not isinstance(payload, dict):
                raise ValueError("limiares em formato inesperado")
            criteria = GradeCriteria.from_dict(payload)
            problems = validate_grade_criteria(criteria)
            if problems:
                raise ValueError("; ".join(problems))
        except (TypeError, ValueError) as exc:
            self.grade_criteria = DEFAULT_GRADE_CRITERIA
            self.capture_status.set(f"Limiares de classificação ignorados ({exc}).")
            return
        criteria, migrated = migrate_criteria(
            criteria, version if isinstance(version, int) else None
        )
        self.grade_criteria = criteria
        if migrated:
            self.capture_status.set(
                "Limiar de rótulo fresco atualizado de 0 para 1 vela: a vela em "
                "formação fica à direita da seta, então idade 0 nunca ocorre."
            )

    def _load_label_age_reference(self, payload: object) -> None:
        """Como a idade do rótulo é contada: contra toda detecção ou só a grade."""
        if payload is None:
            self.label_age_reference = "detected"
            return
        if payload not in ("detected", "grid"):
            self.label_age_reference = "detected"
            self.capture_status.set(
                f"Referência de idade desconhecida ({payload!r}); usando detecção bruta."
            )
            return
        self.label_age_reference = str(payload)

    def _persist_config(self) -> None:
        payload: dict[str, object] = {
            "operation_mode": self.operation_mode.value,
            "timeframe": self.timeframe_var.get(),
            "confidence": self.confidence_var.get(),
            "ocr_enabled": self.ocr_enabled_var.get(),
            "compact_during_capture": self.compact_during_capture_var.get(),
            "tesseract_executable": self.tesseract_path_var.get().strip().strip('"'),
            "candle_palette": self.candle_palette_var.get(),
            "candle_palette_profile_id": self.candle_palette_profile_id,
            "demo_entry_second": self.demo_entry_second_var.get(),
            "demo_mouse_keepalive_enabled": bool(self.demo_mouse_keepalive_var.get()),
            "demo_mouse_keepalive_interval_seconds": self.demo_mouse_keepalive_interval_var.get(),
            "eligibility": self.eligibility_criteria.as_dict(),
            "label_age_reference": self.label_age_reference,
            "grading": self.grade_criteria.as_dict(),
            "grading_version": GRADE_CRITERIA_VERSION,
        }
        try:
            timeout_seconds = int(self.demo_activation_timeout_var.get())
            if MIN_DEMO_ACTIVATION_TIMEOUT_SECONDS <= timeout_seconds <= MAX_DEMO_ACTIVATION_TIMEOUT_SECONDS:
                payload["demo_activation_timeout_seconds"] = timeout_seconds
        except (AttributeError, TypeError, ValueError):
            pass
        if self.region is not None:
            payload["region"] = self.region.as_mss_dict()
        payload["screen_layout"] = self._screen_layout_signature()
        payload["excluded_regions"] = [region.as_mss_dict() for region in self.excluded_regions]
        payload["demo_click_targets"] = {
            direction: {
                "target": {"x": target.x, "y": target.y},
                "window_signature": self.demo_click_target_signatures[direction],
            }
            for direction, target in self.demo_click_targets.items()
            if target is not None
            and self._valid_window_signature(self.demo_click_target_signatures[direction])
        }
        if (
            self.demo_mouse_keepalive_target is not None
            and self.demo_mouse_keepalive_alternate is not None
            and self._valid_window_signature(self.demo_mouse_keepalive_signature)
        ):
            payload["demo_mouse_keepalive"] = {
                "target": {
                    "x": self.demo_mouse_keepalive_target.x,
                    "y": self.demo_mouse_keepalive_target.y,
                },
                "alternate": {
                    "x": self.demo_mouse_keepalive_alternate.x,
                    "y": self.demo_mouse_keepalive_alternate.y,
                },
                "window_signature": self.demo_mouse_keepalive_signature,
            }
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
            saved_palette = config.get("candle_palette")
            saved_palette_profile = config.get("candle_palette_profile_id")
            try:
                current_palette_profile = self._capture_profile_id()
            except Exception:
                current_palette_profile = None
            if (
                saved_palette in CANDLE_PALETTE_MAPS
                and saved_palette != "Não calibrada"
                and saved_palette_profile == current_palette_profile
                and isinstance(saved_palette_profile, str)
            ):
                self.candle_palette_var.set(saved_palette)
                self.candle_palette_profile_id = saved_palette_profile
            else:
                self.candle_palette_var.set("Não calibrada")
                self.candle_palette_profile_id = None
            saved_mode = config.get("operation_mode")
            try:
                requested_mode = OperationMode(saved_mode)
            except (TypeError, ValueError):
                requested_mode = OperationMode.OBSERVATION
            self.operation_mode = (
                requested_mode
                if mode_decision(requested_mode)
                in {ModeDecision.OBSERVE_ONLY, ModeDecision.SIMULATION_ONLY}
                else OperationMode.OBSERVATION
            )
            self.operation_mode_var.set(self.operation_mode.value)
            if self.operation_mode is OperationMode.SIMULATION:
                self.operation_mode_status.set(
                    "SIMULAÇÃO: entradas são hipotéticas; resultados financeiros não são inferidos."
                )
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
            try:
                entry_second = int(config.get("demo_entry_second", DEFAULT_DEMO_ENTRY_SECOND))
            except (TypeError, ValueError):
                entry_second = DEFAULT_DEMO_ENTRY_SECOND
            if MIN_DEMO_ENTRY_SECOND <= entry_second <= MAX_DEMO_ENTRY_SECOND:
                self.demo_entry_second_var.set(f"{entry_second:02d}")
            confidence = config.get("confidence")
            if confidence is not None:
                self.confidence_var.set(str(confidence))
            self._load_eligibility_criteria(config.get("eligibility"))
            self._load_grade_criteria(
                config.get("grading"), config.get("grading_version")
            )
            self._load_label_age_reference(config.get("label_age_reference"))
            if isinstance(config.get("ocr_enabled"), bool):
                self.ocr_enabled_var.set(config["ocr_enabled"])
            if isinstance(config.get("compact_during_capture"), bool):
                self.compact_during_capture_var.set(config["compact_during_capture"])
            if isinstance(config.get("demo_mouse_keepalive_enabled"), bool):
                self.demo_mouse_keepalive_var.set(config["demo_mouse_keepalive_enabled"])
            try:
                keepalive_interval = int(config.get(
                    "demo_mouse_keepalive_interval_seconds", DEFAULT_DEMO_MOUSE_KEEPALIVE_SECONDS
                ))
            except (TypeError, ValueError):
                keepalive_interval = DEFAULT_DEMO_MOUSE_KEEPALIVE_SECONDS
            if MIN_DEMO_MOUSE_KEEPALIVE_SECONDS <= keepalive_interval <= MAX_DEMO_MOUSE_KEEPALIVE_SECONDS:
                self.demo_mouse_keepalive_interval_var.set(str(keepalive_interval))
            tesseract_executable = config.get("tesseract_executable")
            if isinstance(tesseract_executable, str) and tesseract_executable.strip():
                self.tesseract_path_var.set(tesseract_executable.strip().strip('"'))
            self._load_persisted_calibrations(config)
            if self.demo_mouse_keepalive_var.get():
                if self.demo_mouse_keepalive_target is None:
                    self.demo_mouse_keepalive_status.set(
                        "Opção salva marcada; calibre o ponto neutro. Só moverá durante a automação ativa."
                    )
                else:
                    self.demo_mouse_keepalive_status.set(
                        "Ponto neutro salvo e revalidado antes do uso; movimento só durante a automação ativa."
                    )
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.capture_status.set(f"Configuração anterior ignorada ({exc}).")

    def _on_close(self) -> None:
        if self.capture_session_id is not None:
            session_id = self.capture_session_id
            self._record_capture_journal_event(
                "CAPTURE_SESSION_STOPPED",
                {"reason": "APPLICATION_CLOSED"},
                idempotency_key=f"{session_id}:stop",
            )
            self.capture_session_id = None
        self._stop_sequence_recording("aplicativo fechado")
        self._set_capture_keep_awake(False)
        if self.demo_automation_enabled:
            self._toggle_demo_automation()
        self._persist_config()
        self.running = False
        self._closing = True
        self._capture_generation += 1
        self._ocr_executor.shutdown(wait=False, cancel_futures=True)
        self._context_executor.shutdown(wait=False, cancel_futures=True)
        self._clock_executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main() -> None:
    app = AutoTraderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
