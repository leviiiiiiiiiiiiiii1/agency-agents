"""Interface da etapa 1: seleção e visualização contínua da tela."""

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
from .region_selector import RegionSelector
from .signal_detector import SignalCandidate, TesseractSignalDetector


APP_NAME = "AUTO TRADER IQ"
POLL_MS = 500
OCR_INTERVAL_SECONDS = 1.0


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
        self.title(f"{APP_NAME} — Reconhecimento experimental (Etapa 2)")
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

        self.monitor_var = tk.StringVar()
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

        header = ttk.Frame(self, padding=(18, 16))
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME, font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(header, text="Etapa 2 · Reconhecimento OCR experimental de BUY/SELL",
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(3, 0))

        warning = ttk.Label(
            self,
            text="SOMENTE OBSERVAÇÃO — OCR pode errar; candidatos não são sinais validados. Não controla mouse/teclado e não envia ordens.",
            foreground="#8a4b08", background="#fff3cd", padding=9,
        )
        warning.pack(fill="x", padx=18, pady=(0, 10))

        body = ttk.Frame(self, padding=(18, 0, 18, 18))
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

        ttk.Checkbutton(
            controls, text="Ativar OCR experimental BUY/SELL", variable=self.ocr_enabled_var
        ).grid(row=15, column=0, sticky="w", pady=(8, 2))
        ttk.Label(controls, text="Confiança OCR mínima (0–100)").grid(row=16, column=0, sticky="w")
        ttk.Spinbox(controls, from_=0, to=100, textvariable=self.confidence_var, width=8).grid(
            row=17, column=0, sticky="w", pady=(2, 0)
        )

        info = ttk.LabelFrame(controls, text="Estado", padding=10)
        info.grid(row=18, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(info, textvariable=self.capture_status, wraplength=250).pack(anchor="w")
        ttk.Label(info, textvariable=self.heartbeat_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        ttk.Label(info, textvariable=self.ocr_status, wraplength=250).pack(anchor="w", pady=(5, 0))
        controls.columnconfigure(0, weight=1)

        preview_box = ttk.LabelFrame(body, text="Pré-visualização da região", padding=8)
        preview_box.pack(side="left", fill="both", expand=True)
        self.preview = ttk.Label(preview_box, text="Selecione uma região e inicie a visualização.",
                                 anchor="center")
        self.preview.pack(fill="both", expand=True)

        footer = ttk.Label(self, text=f"Configuração e imagens locais: {self.data_dir}", padding=(18, 0, 18, 12))
        footer.pack(fill="x")

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
            self.running = False
            self.start_button.configure(text="Iniciar visualização")
            self.capture_status.set("Captura parada")
            self.heartbeat_status.set("Sem captura")
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
        self.running = True
        self.last_frame_hash = None
        self.last_change_at = time.monotonic()
        self.start_button.configure(text="Parar visualização")
        self.capture_status.set("Capturando…")
        self._capture_tick()

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
                    self.last_candidates = self.detector.detect(image)
                    self.last_ocr_at = now
                    self._update_ocr_status(self.last_candidates)
                except Exception as exc:
                    # Falha do OCR não encerra a captura visual, mas interrompe novas leituras.
                    self.detector = None
                    self.ocr_status.set(f"OCR interrompido por erro: {exc}")
            self._show_preview(image)
            self.capture_status.set(f"Captura ativa · {image.width}×{image.height} px · 2 quadros/s")
        except Exception as exc:
            self.running = False
            self.start_button.configure(text="Iniciar visualização")
            self.capture_status.set(f"Erro de captura: {exc}")
            messagebox.showerror(APP_NAME, f"A captura foi interrompida:\n{exc}", parent=self)
            return
        self.after(POLL_MS, self._capture_tick)

    def _update_ocr_status(self, candidates: list[SignalCandidate]) -> None:
        if not candidates:
            self.ocr_status.set("Nenhuma etiqueta BUY/SELL legível neste quadro; isso não descarta um sinal.")
            return
        summary = " | ".join(
            f"{item.direction} {item.confidence:.0f}% em ({item.left},{item.top})"
            for item in candidates[:4]
        )
        if len(candidates) > 4:
            summary += f" | +{len(candidates) - 4}"
        self.ocr_status.set(f"Candidato(s) OCR — revisar visualmente: {summary}")

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
                draw.text((item.left, max(0, item.top - 16)),
                          f"{item.direction} {item.confidence:.0f}%", fill=color)
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
        payload = {"region": self.region.as_mss_dict(), "monitor_index": self._selected_monitor_index()}
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
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.capture_status.set(f"Configuração anterior ignorada ({exc}).")

    def _on_close(self) -> None:
        self.running = False
        self.destroy()


def main() -> None:
    app = AutoTraderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
