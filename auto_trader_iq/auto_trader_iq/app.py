"""Interface da etapa 3: OCR e simulação assistida sem ordens reais."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

from .capture import ScreenCapture, ScreenRegion
from .candle_monitor import detect_candle_bars, filter_to_recent_candle
from .candle_timer import PlatformClockReading, m1_entry_window_open
from .region_selector import RegionSelector
from .sequence_recorder import SequenceRecorder
from .signal_detector import SignalCandidate, TesseractSignalDetector
from .simulation import SimulationWorkflow


APP_NAME = "AUTO TRADER IQ"
POLL_MS = 500
OCR_INTERVAL_SECONDS = 1.0
TIMER_MAX_AGE_SECONDS = 1.5


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
        self.title(f"{APP_NAME} — Simulação assistida (Etapa 3)")
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
        self.detector: TesseractSignalDetector | None = None
        self.last_candidates: list[SignalCandidate] = []
        self.last_ocr_at = 0.0
        self.latest_platform_clock: PlatformClockReading | None = None
        self.latest_clock_at: float | None = None
        self.latest_bar_count = 0
        self.sequence_recorder = SequenceRecorder(self.data_dir / "sequences")
        self.sequence_status = tk.StringVar(value="Gravação de teste inativa; nenhuma imagem está sendo salva.")
        self.simulation = SimulationWorkflow()
        self.candidates_by_id: dict[str, SignalCandidate] = {}
        self.simulation_status = tk.StringVar(value="Simulação parada; nenhuma entrada foi registrada.")
        self.compact_mode = False

        self.monitor_var = tk.StringVar()
        self.timeframe_var = tk.StringVar(value="M1")
        self.timer_status = tk.StringVar(value="M1: aguardando leitura de HORA ATUAL da plataforma.")
        self.compact_during_capture_var = tk.BooleanVar(value=True)
        self.ocr_enabled_var = tk.BooleanVar(value=False)
        self.confidence_var = tk.StringVar(value="70")
        self.ocr_status = tk.StringVar(value="OCR desligado; nenhuma operação é executada.")
        self.region_vars = {key: tk.StringVar() for key in ("left", "top", "width", "height")}
        self.capture_status = tk.StringVar(value="Captura parada")
        self.heartbeat_status = tk.StringVar(value="Sem captura")
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
        ttk.Label(header, text="Etapa 3 · OCR e simulação assistida de COMPRA/VENDER",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(3, 0))

        warning = ttk.Label(
            self.full_ui,
            text="SIMULAÇÃO ASSISTIDA — escolha o rótulo, aguarde N+1 nascer e confirme manualmente. Não controla mouse/teclado nem envia ordens.",
            foreground="#8a4b08", background="#fff3cd", padding=9,
        )
        warning.pack(fill="x", padx=18, pady=(0, 10))

        body = ttk.Frame(self.full_ui, padding=(18, 0, 18, 18))
        body.pack(fill="both", expand=True)
        controls = ttk.LabelFrame(body, text="Região monitorada", padding=12)
        controls.pack(side="left", fill="y", padx=(0, 14))
        ttk.Label(controls, text="Monitor").grid(row=0, column=0, sticky="w")
        self.monitor_combo = ttk.Combobox(controls, textvariable=self.monitor_var,
                                          state="readonly", width=27)
        self.monitor_combo.grid(row=1, column=0, sticky="ew", pady=(4, 10))

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
            controls, text="Ativar OCR experimental COMPRA/VENDER", variable=self.ocr_enabled_var
        ).grid(row=17, column=0, sticky="w", pady=(8, 2))
        ttk.Label(controls, text="Confiança OCR mínima (0–100)").grid(row=18, column=0, sticky="w")
        ttk.Spinbox(controls, from_=0, to=100, textvariable=self.confidence_var, width=8).grid(
            row=19, column=0, sticky="w", pady=(2, 0)
        )

        ttk.Checkbutton(
            controls, text="Modo compacto ao monitorar (recomendado)",
            variable=self.compact_during_capture_var,
        ).grid(row=20, column=0, sticky="w", pady=(6, 0))

        ttk.Label(controls, text="Período do gráfico").grid(row=21, column=0, sticky="w", pady=(6, 0))
        self.timeframe_combo = ttk.Combobox(
            controls, textvariable=self.timeframe_var, values=("M1", "M5", "M15", "M30"),
            state="readonly", width=10,
        )
        self.timeframe_combo.grid(row=22, column=0, sticky="w", pady=(2, 0))
        self.timeframe_combo.bind("<<ComboboxSelected>>", self._on_timeframe_change)

        info = ttk.LabelFrame(controls, text="Estado", padding=10)
        info.grid(row=23, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(info, textvariable=self.capture_status, wraplength=250).pack(anchor="w")
        ttk.Label(info, textvariable=self.heartbeat_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        ttk.Label(info, textvariable=self.ocr_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        ttk.Label(info, textvariable=self.timer_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        controls.columnconfigure(0, weight=1)

        preview_box = ttk.LabelFrame(body, text="Pré-visualização da região", padding=8)
        preview_box.pack(side="left", fill="both", expand=True)
        self.preview = ttk.Label(preview_box, text="Selecione uma região e inicie a visualização.",
                                 anchor="center")
        self.preview.pack(fill="both", expand=True)

        simulation_box = ttk.LabelFrame(preview_box, text="Simulação assistida da próxima vela (sem ordens)", padding=6)
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
        ttk.Label(simulation_box, text="Entradas simuladas nesta sessão").pack(anchor="w", pady=(5, 0))
        self.history_table = ttk.Treeview(
            simulation_box, columns=("time", "direction", "status"), show="headings", height=2
        )
        self.history_table.heading("time", text="Horário")
        self.history_table.heading("direction", text="Direção")
        self.history_table.heading("status", text="Estado")
        self.history_table.column("time", width=90, anchor="center")
        self.history_table.column("direction", width=100, anchor="center")
        self.history_table.column("status", width=200, anchor="w")
        self.history_table.pack(fill="x")
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
        ttk.Label(simulation_box, textvariable=self.simulation_status, wraplength=650).pack(anchor="w", pady=(4, 0))

        footer = ttk.Label(self.full_ui, text=f"Configuração e imagens locais: {self.data_dir}", padding=(18, 0, 18, 12))
        footer.pack(fill="x")

        self.compact_frame = ttk.Frame(self, padding=10)
        ttk.Label(self.compact_frame, text="AUTO TRADER IQ · captura ativa",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(
            self.compact_frame,
            text="Mantenha este painel fora da região monitorada. A captura continua enquanto você arma/confirma.",
            wraplength=520,
        ).pack(anchor="w", pady=(2, 4))
        ttk.Label(self.compact_frame, textvariable=self.ocr_status, wraplength=520).pack(anchor="w", pady=(0, 2))
        ttk.Label(self.compact_frame, textvariable=self.timer_status, wraplength=520).pack(anchor="w", pady=(0, 4))
        self.compact_candidate_table = ttk.Treeview(
            self.compact_frame, columns=("label", "confidence", "position"),
            show="headings", height=4, selectmode="browse",
        )
        self.compact_candidate_table.heading("label", text="Candidato OCR")
        self.compact_candidate_table.heading("confidence", text="Confiança")
        self.compact_candidate_table.heading("position", text="Posição")
        self.compact_candidate_table.column("label", width=160, stretch=True)
        self.compact_candidate_table.column("confidence", width=90, anchor="center")
        self.compact_candidate_table.column("position", width=120, anchor="center")
        self.compact_candidate_table.pack(fill="x", expand=True)
        compact_buttons = ttk.Frame(self.compact_frame)
        compact_buttons.pack(fill="x", pady=(6, 2))
        ttk.Button(compact_buttons, text="Armar selecionado", command=self._arm_compact_candidate).pack(
            side="left", padx=(0, 5)
        )
        self.compact_confirm_button = ttk.Button(
            compact_buttons, text="Confirmar N+1", command=self._confirm_next_candle, state="disabled"
        )
        self.compact_confirm_button.pack(side="left", padx=5)
        self.compact_cancel_button = ttk.Button(
            compact_buttons, text="Cancelar pendente", command=self._cancel_pending_simulation,
            state="disabled",
        )
        self.compact_cancel_button.pack(side="left", padx=5)
        ttk.Button(
            compact_buttons, text="Configurações (pausar)", command=self._return_to_full_ui
        ).pack(side="right")
        recorder_row = ttk.Frame(self.compact_frame)
        recorder_row.pack(fill="x", pady=(4, 0))
        self.compact_sequence_button = ttk.Button(
            recorder_row, text="Gravar sequência de teste (75 s)", command=self._toggle_sequence_recording
        )
        self.compact_sequence_button.pack(side="left")
        ttk.Label(recorder_row, textvariable=self.sequence_status, wraplength=350).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(self.compact_frame, textvariable=self.simulation_status, wraplength=520).pack(
            anchor="w", pady=(4, 0)
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

    def _apply_coordinates(self) -> None:
        try:
            region = ScreenRegion(**{key: int(var.get().strip()) for key, var in self.region_vars.items()})
        except (ValueError, TypeError) as exc:
            messagebox.showerror(APP_NAME, f"Coordenadas inválidas. Informe inteiros; largura e altura > 0.\n{exc}", parent=self)
            return
        self._set_region(region)
        self._persist_config()

    def _toggle_capture(self) -> None:
        if self.running:
            self._stop_capture("Captura parada pelo usuário.")
            return
        if self.region is None:
            self._apply_coordinates()
            if self.region is None:
                return
        self.detector = None
        if self.ocr_enabled_var.get():
            try:
                confidence = float(self.confidence_var.get())
                executable = os.environ.get("TESSERACT_CMD")
                detector = TesseractSignalDetector(confidence, executable)
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
        self.minsize(420, 330)
        self.geometry("560x365+0+0")
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
                    self.latest_bar_count = len(bars)
                    self.last_candidates = filter_to_recent_candle(raw_candidates, bars)
                    self.last_ocr_at = now
                    self._update_ocr_status(self.last_candidates, len(raw_candidates), len(bars))
                    self._update_timer_status(now)
                except Exception as exc:
                    # Falha do OCR não encerra a captura visual, mas interrompe novas leituras.
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
        candidate = self.candidates_by_id.get(item_id)
        if candidate is None:
            self.simulation_status.set("O candidato não está mais no quadro atual; aguarde a próxima leitura.")
            return
        try:
            pending = self.simulation.arm(candidate)
        except ValueError as exc:
            self.simulation_status.set(str(exc))
            return
        label = "COMPRA" if pending.direction == "BUY" else "VENDER"
        self.simulation_status.set(
            f"Pendente: {label} ({pending.confidence:.0f}%). Aguarde a próxima vela nascer; "
            "confirme manualmente apenas quando isso estiver visível. Nenhuma ordem será enviada."
        )
        self._refresh_simulation_buttons()

    def _confirm_next_candle(self) -> None:
        elapsed_seconds = None
        if self.timeframe_var.get() == "M1":
            if not self._m1_window_valid():
                self.simulation_status.set(
                    "Entrada M1 bloqueada: HORA ATUAL da plataforma não foi lida ou já passou de 30 s."
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
        label = "COMPRA" if entry.direction == "BUY" else "VENDER"
        confirmed = entry.next_candle_confirmed_at.astimezone().strftime("%H:%M:%S")
        elapsed_text = (
            f" · M1 +{entry.elapsed_seconds_after_open}s"
            if entry.elapsed_seconds_after_open is not None else ""
        )
        self.history_table.insert(
            "", "end", iid=entry.signal_id,
            values=(confirmed, label, f"SIMULADA · N+1{elapsed_text}"),
        )
        self.simulation_status.set(
            f"ENTRADA SIMULADA: {label} às {confirmed}; N+1 confirmada manualmente{elapsed_text}. "
            f"Histórico desta sessão: {len(self.simulation.entries)} entrada(s)."
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
        self.simulation_status.set(
            f"Simulação pendente cancelada ({pending.observed_text}); o mesmo rótulo não será rearmado nesta sessão."
        )
        for button in (self.confirm_candle_button, self.compact_confirm_button):
            button.configure(state="disabled")
        for button in (self.cancel_sim_button, self.compact_cancel_button):
            button.configure(state="disabled")

    def _m1_window_valid(self) -> bool:
        if self.latest_platform_clock is None or self.latest_clock_at is None:
            return False
        if time.monotonic() - self.latest_clock_at > TIMER_MAX_AGE_SECONDS:
            return False
        return m1_entry_window_open(self.latest_platform_clock, max_elapsed_seconds=30)

    def _refresh_simulation_buttons(self) -> None:
        pending = self.simulation.pending is not None
        confirm_allowed = pending and (
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
        platform_clock = self.latest_platform_clock
        fresh = self.latest_clock_at is not None and (now or time.monotonic()) - self.latest_clock_at <= TIMER_MAX_AGE_SECONDS
        if platform_clock is None or not fresh:
            self.timer_status.set("M1: relógio HORA ATUAL não legível/atual; confirmação bloqueada.")
            self._refresh_simulation_buttons()
            return
        elapsed = platform_clock.elapsed_seconds_in_m1
        if 0 <= elapsed <= 30:
            self.timer_status.set(
                f"M1: HORA ATUAL {platform_clock.hour:02d}:{platform_clock.minute:02d}:"
                f"{platform_clock.second:02d}; {elapsed}s da vela, janela aberta."
            )
        else:
            self.timer_status.set(f"M1: {elapsed}s decorridos; janela de 30s expirada.")
            if self.simulation.pending is not None:
                expired = self.simulation.cancel_pending()
                label = "COMPRA" if expired.direction == "BUY" else "VENDER"
                self.simulation_status.set(
                    f"Sinal {label} expirado: ultrapassou 30s de M1; descartado sem entrada."
                )
        self._refresh_simulation_buttons()

    def _on_timeframe_change(self, _event: tk.Event | None = None) -> None:
        self._persist_config()
        self._update_timer_status()

    def _show_preview(self, image: Image.Image) -> None:
        max_width = max(200, self.preview.winfo_width() - 20)
        max_height = max(150, self.preview.winfo_height() - 20)
        preview_image = image.copy()
        if self.last_candidates:
            draw = ImageDraw.Draw(preview_image)
            for item in self.last_candidates:
                color = "#19a05b" if item.direction == "BUY" else "#e34141"
                box = (item.left, item.top, item.left + item.width, item.top + item.height)
                draw.rectangle(box, outline=color, width=3)
                label = "COMPRA" if item.direction == "BUY" else "VENDER"
                draw.text((item.left, max(0, item.top - 16)),
                          f"{label} {item.confidence:.0f}%", fill=color)
        preview_image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(preview_image)
        self.preview.configure(image=self.preview_photo, text="")

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
        if self.region is None:
            return
        payload = {
            "region": self.region.as_mss_dict(),
            "monitor_index": self._selected_monitor_index(),
            "timeframe": self.timeframe_var.get(),
        }
        try:
            self.config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            self.capture_status.set(f"Região aplicada, mas não foi possível salvar a configuração: {exc}")

    def _load_config(self) -> None:
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            self._set_region(ScreenRegion.from_dict(config["region"]))
            index = config.get("monitor_index")
            if isinstance(index, int) and 0 <= index < len(self.monitors):
                self.monitor_combo.current(index)
            timeframe = config.get("timeframe")
            if timeframe in {"M1", "M5", "M15", "M30"}:
                self.timeframe_var.set(timeframe)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.capture_status.set(f"Configuração anterior ignorada ({exc}).")

    def _on_close(self) -> None:
        self._stop_sequence_recording("aplicativo fechado")
        self.running = False
        self.destroy()


def main() -> None:
    app = AutoTraderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
