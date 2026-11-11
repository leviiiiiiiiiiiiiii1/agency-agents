"""SQLite journal for opportunities and explicitly separated execution/result events.

Unknown broker data is stored as NULL, never fabricated. A click-sent event is not an
order confirmation and an order confirmation is not a settled financial result.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Mapping
from uuid import uuid4


SCHEMA_VERSION = 3
EVENT_TYPES = {
    "CAPTURE_SESSION_STARTED",
    "CAPTURE_SESSION_STOPPED",
    "CAPTURE_SESSION_INTERRUPTED",
    "CAPTURE_FRAME_ACCEPTED",
    "CAPTURE_FRAME_REJECTED",
    "OCR_COMPLETED",
    "OCR_FAILED",
    "CLOCK_PROBE",
    "SIMULATION_ARMED",
    "SIMULATION_CANCELLED",
    "SIMULATION_CONFIRMED",
    "SIMULATION_CANDLE_ROLLOVER",
    "SIMULATION_EXPIRED",
    "CLICK_REQUESTED",
    "EXECUTION_REJECTED",
    "SIGNAL_IDENTIFIED",
    "SIGNAL_REFRESHED",
    "SIGNAL_LIFECYCLE_CHANGED",
    "SIGNAL_TRACK_EXPIRED",
    "SIGNAL_TRACK_REAPPEARED",
    "SIGNAL_TEXT_REPAINTED",
    "SIGNAL_DIRECTION_CHANGED",
    "SIGNAL_DUPLICATE_DETECTED",
    "SIGNAL_TRACK_INDETERMINATE",
    "OPPORTUNITY_APPROVED",
    "OPPORTUNITY_DISCARDED",
    "CLICK_SENT",
    "ORDER_CONFIRMED",
    "TRADE_SETTLED",
    "EXECUTION_UNCONFIRMED",
}
OUTCOMES = {"WIN", "LOSS", "DRAW", "UNCONFIRMED"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _finite_optional(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} precisa ser finito.")
    return result


class OpportunityStore:
    """Durable local journal with additive migrations and pre-migration backups."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _session(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _backup_before_migration(self, connection: sqlite3.Connection) -> Path | None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        backup_path = self.path.with_name(
            f"{self.path.stem}.backup-v{SCHEMA_VERSION}-{stamp}{self.path.suffix}"
        )
        suffix = 1
        while backup_path.exists():
            backup_path = self.path.with_name(
                f"{self.path.stem}.backup-v{SCHEMA_VERSION}-{stamp}-{suffix}{self.path.suffix}"
            )
            suffix += 1
        destination = sqlite3.connect(backup_path)
        try:
            connection.backup(destination)
        finally:
            destination.close()
        return backup_path

    def _initialize(self) -> None:
        with self._session() as connection:
            current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Banco versão {current_version} é mais novo que o app ({SCHEMA_VERSION}); "
                    "não será modificado."
                )
            if current_version < SCHEMA_VERSION and self.path.exists() and self.path.stat().st_size:
                self._backup_before_migration(connection)

            # Base schema is additive. Existing opportunity/event rows are never
            # rebuilt or deleted by this initializer.
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS opportunities (
                    opportunity_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    created_at_utc TEXT NOT NULL,
                    last_seen_at_utc TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 1 CHECK (seen_count >= 1),
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    asset TEXT,
                    direction TEXT NOT NULL CHECK (direction IN ('BUY','SELL')),
                    strategy_id TEXT,
                    strategy_version TEXT,
                    timeframe TEXT,
                    score REAL,
                    grade TEXT,
                    filter_results_json TEXT NOT NULL DEFAULT '{}',
                    market_features_json TEXT NOT NULL DEFAULT '{}',
                    payout REAL,
                    signal_at_utc TEXT NOT NULL,
                    execution_attempt_at_utc TEXT,
                    execution_delay_ms REAL,
                    order_confirmed INTEGER CHECK (order_confirmed IN (0,1) OR order_confirmed IS NULL),
                    order_confirmation_source TEXT,
                    stake REAL,
                    expiry_seconds REAL,
                    settled_at_utc TEXT,
                    outcome TEXT CHECK (outcome IN ('WIN','LOSS','DRAW','UNCONFIRMED') OR outcome IS NULL),
                    pnl REAL,
                    outcome_source TEXT,
                    ocr_text TEXT NOT NULL,
                    ocr_confidence REAL,
                    frame_quality_json TEXT NOT NULL DEFAULT '{}',
                    rejection_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_opportunities_signal_time
                    ON opportunities(signal_at_utc);
                CREATE INDEX IF NOT EXISTS idx_opportunities_strategy_time
                    ON opportunities(strategy_id, signal_at_utc);
                CREATE INDEX IF NOT EXISTS idx_opportunities_status
                    ON opportunities(status, signal_at_utc);
                CREATE TABLE IF NOT EXISTS opportunity_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opportunity_id TEXT NOT NULL REFERENCES opportunities(opportunity_id),
                    event_type TEXT NOT NULL,
                    occurred_at_utc TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_opportunity_events_opportunity
                    ON opportunity_events(opportunity_id, event_id);
                """
            )
            if current_version < 1:
                connection.execute("PRAGMA user_version = 1")
                current_version = 1

            if current_version < 2:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS signal_tracks (
                        tracking_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL UNIQUE,
                        opportunity_id TEXT NOT NULL UNIQUE
                            REFERENCES opportunities(opportunity_id),
                        profile_id TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        direction TEXT NOT NULL CHECK (direction IN ('BUY','SELL')),
                        observed_text TEXT NOT NULL,
                        left_px INTEGER NOT NULL,
                        top_px INTEGER NOT NULL,
                        width_px INTEGER NOT NULL,
                        height_px INTEGER NOT NULL,
                        confidence REAL,
                        first_seen_at_utc TEXT NOT NULL,
                        last_seen_at_utc TEXT NOT NULL,
                        lifecycle TEXT NOT NULL,
                        consecutive_observations INTEGER NOT NULL DEFAULT 1,
                        missing_observations INTEGER NOT NULL DEFAULT 0,
                        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
                        duplicate_count INTEGER NOT NULL DEFAULT 0,
                        related_tracking_id TEXT,
                        last_frame_id TEXT,
                        detector_version TEXT NOT NULL
                    )"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_signal_tracks_profile_active "
                    "ON signal_tracks(profile_id, timeframe, active, last_seen_at_utc)"
                )
                connection.execute("PRAGMA user_version = 2")
                current_version = 2

            if current_version < 3:
                connection.execute("BEGIN IMMEDIATE")
                # Keep existing event IDs/order intact while extending the ledger to
                # non-opportunity capture events and idempotency keys.
                connection.execute(
                    """CREATE TABLE opportunity_events_v3 (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        opportunity_id TEXT REFERENCES opportunities(opportunity_id),
                        session_id TEXT,
                        event_type TEXT NOT NULL,
                        occurred_at_utc TEXT NOT NULL,
                        source TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        idempotency_key TEXT NOT NULL UNIQUE
                    )"""
                )
                connection.execute(
                    """INSERT INTO opportunity_events_v3 (
                        event_id, opportunity_id, session_id, event_type,
                        occurred_at_utc, source, payload_json, idempotency_key
                    ) SELECT event_id, opportunity_id, NULL, event_type,
                             occurred_at_utc, source, payload_json,
                             'legacy-v2:' || event_id
                      FROM opportunity_events"""
                )
                connection.execute("DROP TABLE opportunity_events")
                connection.execute(
                    "ALTER TABLE opportunity_events_v3 RENAME TO opportunity_events"
                )
                connection.execute(
                    "CREATE INDEX idx_opportunity_events_opportunity "
                    "ON opportunity_events(opportunity_id, event_id)"
                )
                connection.execute(
                    "CREATE INDEX idx_opportunity_events_session "
                    "ON opportunity_events(session_id, event_id)"
                )
                connection.execute(
                    """CREATE TRIGGER opportunity_events_no_update
                       BEFORE UPDATE ON opportunity_events
                       BEGIN SELECT RAISE(ABORT, 'opportunity_events is append-only'); END"""
                )
                connection.execute(
                    """CREATE TRIGGER opportunity_events_no_delete
                       BEFORE DELETE ON opportunity_events
                       BEGIN SELECT RAISE(ABORT, 'opportunity_events is append-only'); END"""
                )
                connection.execute("PRAGMA user_version = 3")

    def load_signal_tracks(
        self, *, profile_id: str, timeframe: str, inactive_limit: int = 100
    ) -> list[dict[str, Any]]:
        """Load active tracks plus recent tombstones for restart reconciliation."""
        with self._session() as connection:
            rows = connection.execute(
                """SELECT * FROM (
                       SELECT * FROM signal_tracks
                       WHERE profile_id = ? AND timeframe = ? AND active = 1
                       UNION ALL
                       SELECT * FROM signal_tracks
                       WHERE profile_id = ? AND timeframe = ? AND active = 0
                       ORDER BY last_seen_at_utc DESC LIMIT ?
                   ) ORDER BY last_seen_at_utc DESC""",
                (profile_id, timeframe, profile_id, timeframe, max(0, int(inactive_limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_signal_tracks(
        self,
        *,
        profile_id: str,
        timeframe: str,
        tracks: list[Mapping[str, Any]],
        source: str = "SIGNAL_LIFECYCLE_TRACKER",
    ) -> None:
        """Persist a tracker snapshot and lifecycle transitions in one transaction."""
        with self._session() as connection:
            for track in tracks:
                tracking_id = str(track["tracking_id"])
                opportunity_id = str(track.get("opportunity_id") or tracking_id)
                values = (
                    tracking_id,
                    str(track["fingerprint"]),
                    opportunity_id,
                    profile_id,
                    timeframe,
                    str(track["direction"]),
                    str(track["observed_text"]),
                    int(track["left"]),
                    int(track["top"]),
                    int(track["width"]),
                    int(track["height"]),
                    _finite_optional(track.get("confidence"), "confidence"),
                    str(track["first_seen_at_utc"]),
                    str(track["last_seen_at_utc"]),
                    str(track["lifecycle"]),
                    max(1, int(track.get("consecutive_observations", 1))),
                    max(0, int(track.get("missing_observations", 0))),
                    int(bool(track.get("active", True))),
                    max(0, int(track.get("duplicate_count", 0))),
                    track.get("related_tracking_id"),
                    track.get("last_frame_id"),
                    str(track.get("detector_version") or "unknown"),
                )
                previous = connection.execute(
                    "SELECT lifecycle, active, duplicate_count FROM signal_tracks WHERE tracking_id = ?",
                    (tracking_id,),
                ).fetchone()
                if previous is None:
                    connection.execute(
                        """INSERT INTO signal_tracks (
                            tracking_id, fingerprint, opportunity_id, profile_id, timeframe,
                            direction, observed_text, left_px, top_px, width_px, height_px,
                            confidence, first_seen_at_utc, last_seen_at_utc, lifecycle,
                            consecutive_observations, missing_observations, active,
                            duplicate_count, related_tracking_id, last_frame_id, detector_version
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        values,
                    )
                    if values[19]:
                        related = connection.execute(
                            "SELECT opportunity_id FROM signal_tracks WHERE tracking_id = ?",
                            (values[19],),
                        ).fetchone()
                        if related is not None:
                            event = (
                                "SIGNAL_DIRECTION_CHANGED"
                                if values[14] == "DIRECTION_CHANGED"
                                else "SIGNAL_TEXT_REPAINTED"
                                if values[14] in {"REPINTED", "ALTERED"}
                                else "SIGNAL_TRACK_INDETERMINATE"
                            )
                            payload = {
                                "related_tracking_id": values[19],
                                "tracking_id": tracking_id,
                                "lifecycle": values[14],
                            }
                            self._insert_event(connection, opportunity_id, event, source, payload)
                            self._insert_event(connection, str(related["opportunity_id"]), event, source, payload)
                    if values[18] > 0:
                        self._insert_event(connection, opportunity_id, "SIGNAL_DUPLICATE_DETECTED", source, {
                            "duplicate_count": values[18],
                            "tracking_id": tracking_id,
                            "frame_id": values[20],
                        })
                else:
                    connection.execute(
                        """UPDATE signal_tracks SET
                            fingerprint=?, opportunity_id=?, profile_id=?, timeframe=?,
                            direction=?, observed_text=?, left_px=?, top_px=?, width_px=?,
                            height_px=?, confidence=?, first_seen_at_utc=?, last_seen_at_utc=?,
                            lifecycle=?, consecutive_observations=?, missing_observations=?,
                            active=?, duplicate_count=?, related_tracking_id=?, last_frame_id=?, detector_version=?
                           WHERE tracking_id=?""",
                        (*values[1:], tracking_id),
                    )
                    state_changed = (
                        previous["lifecycle"] != values[14]
                        or previous["active"] != values[17]
                    )
                    if state_changed:
                        event = (
                            "SIGNAL_TRACK_EXPIRED"
                            if values[14] == "EXPIRED"
                            else "SIGNAL_LIFECYCLE_CHANGED"
                        )
                        self._insert_event(connection, opportunity_id, event, source, {
                            "previous_lifecycle": previous["lifecycle"],
                            "lifecycle": values[14],
                            "previous_active": bool(previous["active"]),
                            "active": bool(values[17]),
                            "missing_observations": values[16],
                            "tracking_id": tracking_id,
                            "last_frame_id": values[20],
                        })
                    if values[18] > int(previous["duplicate_count"] or 0):
                        self._insert_event(connection, opportunity_id, "SIGNAL_DUPLICATE_DETECTED", source, {
                            "duplicate_count": values[18],
                            "tracking_id": tracking_id,
                            "frame_id": values[20],
                        })

    def record_signal(
        self,
        *,
        fingerprint: str,
        mode: str,
        direction: str,
        ocr_text: str,
        ocr_confidence: float | None,
        signal_at_utc: str,
        opportunity_id: str | None = None,
        asset: str | None = None,
        strategy_id: str | None = None,
        strategy_version: str | None = None,
        timeframe: str | None = None,
        frame_quality: Mapping[str, Any] | None = None,
        market_features: Mapping[str, Any] | None = None,
    ) -> tuple[str, bool]:
        """Insert a first-seen signal or refresh its last-seen metadata."""
        if not fingerprint.strip():
            raise ValueError("fingerprint não pode ficar vazio.")
        if direction not in {"BUY", "SELL"}:
            raise ValueError("direction deve ser BUY ou SELL.")
        confidence = _finite_optional(ocr_confidence, "ocr_confidence")
        if confidence is not None and not 0 <= confidence <= 100:
            raise ValueError("ocr_confidence deve estar entre 0 e 100.")
        now = _utc_now()
        quality_json = _json(dict(frame_quality or {}))
        features_json = _json(dict(market_features or {}))
        with self._session() as connection:
            row = connection.execute(
                "SELECT opportunity_id, market_features_json FROM opportunities WHERE fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if row is None:
                new_opportunity_id = str(opportunity_id or uuid4().hex)
                if not new_opportunity_id.strip():
                    raise ValueError("opportunity_id não pode ficar vazio.")
                connection.execute(
                    """INSERT INTO opportunities (
                        opportunity_id, fingerprint, created_at_utc, last_seen_at_utc, mode,
                        status, asset, direction, strategy_id, strategy_version, timeframe,
                        signal_at_utc, ocr_text, ocr_confidence, frame_quality_json,
                        market_features_json
                    ) VALUES (?, ?, ?, ?, ?, 'IDENTIFIED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        new_opportunity_id, fingerprint, now, now, mode, asset, direction,
                        strategy_id, strategy_version, timeframe, signal_at_utc, ocr_text,
                        confidence, quality_json, features_json,
                    ),
                )
                self._insert_event(connection, new_opportunity_id, "SIGNAL_IDENTIFIED", mode, {
                    "signal_at_utc": signal_at_utc,
                    "ocr_text": ocr_text,
                    "ocr_confidence": confidence,
                    "frame_quality": dict(frame_quality or {}),
                    "market_features": dict(market_features or {}),
                })
                return new_opportunity_id, True

            opportunity_id = str(row["opportunity_id"])
            try:
                previous_features = json.loads(row["market_features_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                previous_features = {}
            previous_lifecycle = previous_features.get("signal_lifecycle")
            current_features = dict(market_features or {})
            current_lifecycle = current_features.get("signal_lifecycle")
            connection.execute(
                """UPDATE opportunities SET last_seen_at_utc = ?, seen_count = seen_count + 1,
                   ocr_text = ?, ocr_confidence = ?, frame_quality_json = ?, market_features_json = ?
                   WHERE opportunity_id = ?""",
                (now, ocr_text, confidence, quality_json, features_json, opportunity_id),
            )
            if current_lifecycle and current_lifecycle != previous_lifecycle:
                self._insert_event(
                    connection,
                    opportunity_id,
                    "SIGNAL_LIFECYCLE_CHANGED",
                    mode,
                    {
                        "previous": previous_lifecycle,
                        "current": current_lifecycle,
                        "signal_at_utc": signal_at_utc,
                    },
                )
            return opportunity_id, False

    def record_decision(
        self,
        opportunity_id: str,
        *,
        approved: bool,
        source: str,
        reasons: list[str],
        score: float | None = None,
        grade: str | None = None,
        filters: Mapping[str, Any] | None = None,
        market_features: Mapping[str, Any] | None = None,
        payout: float | None = None,
        strategy_id: str | None = None,
        strategy_version: str | None = None,
    ) -> None:
        """Record a decision; an approval is not an execution or order confirmation."""
        score_value = _finite_optional(score, "score")
        payout_value = _finite_optional(payout, "payout")
        if score_value is not None and not 0 <= score_value <= 100:
            raise ValueError("score deve estar entre 0 e 100.")
        if payout_value is not None and payout_value < 0:
            raise ValueError("payout não pode ser negativo.")
        event_type = "OPPORTUNITY_APPROVED" if approved else "OPPORTUNITY_DISCARDED"
        status = "APPROVED" if approved else "DISCARDED"
        with self._session() as connection:
            cursor = connection.execute(
                """UPDATE opportunities SET status = ?, score = ?, grade = ?,
                   filter_results_json = ?, market_features_json = COALESCE(?, market_features_json),
                   payout = COALESCE(?, payout), strategy_id = COALESCE(?, strategy_id),
                   strategy_version = COALESCE(?, strategy_version), rejection_reason = ?
                   WHERE opportunity_id = ?""",
                (
                    status, score_value, grade, _json(dict(filters or {})),
                    _json(dict(market_features)) if market_features is not None else None,
                    payout_value, strategy_id, strategy_version,
                    "; ".join(reasons) if not approved else None, opportunity_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Oportunidade inexistente: {opportunity_id}")
            self._insert_event(connection, opportunity_id, event_type, source, {
                "approved": approved,
                "reasons": list(reasons),
                "score": score_value,
                "grade": grade,
                "filters": dict(filters or {}),
                "payout": payout_value,
            })

    def record_click_sent(
        self,
        opportunity_id: str,
        *,
        occurred_at_utc: str,
        delay_ms: float | None,
        source: str = "GUI_CLICK_ATTEMPT",
    ) -> None:
        """Record only the click attempt; never imply that an order was accepted."""
        delay = _finite_optional(delay_ms, "delay_ms")
        with self._session() as connection:
            cursor = connection.execute(
                """UPDATE opportunities SET status = 'CLICK_SENT',
                   execution_attempt_at_utc = ?, execution_delay_ms = ?
                   WHERE opportunity_id = ?""",
                (occurred_at_utc, delay, opportunity_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Oportunidade inexistente: {opportunity_id}")
            self._insert_event(connection, opportunity_id, "CLICK_SENT", source, {
                "execution_attempt_at_utc": occurred_at_utc,
                "execution_delay_ms": delay,
                "order_confirmed": None,
            })

    def confirm_order(
        self,
        opportunity_id: str,
        *,
        source: str,
        confirmed: bool,
        stake: float | None = None,
        expiry_seconds: float | None = None,
    ) -> None:
        """Record explicit manual/API confirmation, keeping unknown data NULL."""
        if source not in {"MANUAL", "BROKER_API"}:
            raise ValueError("source precisa identificar confirmação manual ou API confiável.")
        stake_value = _finite_optional(stake, "stake")
        expiry_value = _finite_optional(expiry_seconds, "expiry_seconds")
        if stake_value is not None and stake_value <= 0:
            raise ValueError("stake precisa ser positiva.")
        if expiry_value is not None and expiry_value <= 0:
            raise ValueError("expiry_seconds precisa ser positivo.")
        status = "ORDER_CONFIRMED" if confirmed else "EXECUTION_UNCONFIRMED"
        event_type = "ORDER_CONFIRMED" if confirmed else "EXECUTION_UNCONFIRMED"
        with self._session() as connection:
            cursor = connection.execute(
                """UPDATE opportunities SET status = ?, order_confirmed = ?,
                   order_confirmation_source = ?, stake = ?, expiry_seconds = ?
                   WHERE opportunity_id = ?""",
                (status, int(confirmed), source, stake_value, expiry_value, opportunity_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Oportunidade inexistente: {opportunity_id}")
            self._insert_event(connection, opportunity_id, event_type, source, {
                "confirmed": confirmed,
                "stake": stake_value,
                "expiry_seconds": expiry_value,
            })

    def settle_trade(
        self,
        opportunity_id: str,
        *,
        outcome: str,
        pnl: float | None,
        source: str,
        payout: float | None = None,
        stake: float | None = None,
    ) -> None:
        """Record a verified/manual result. Unknown P&L remains NULL, never inferred."""
        normalized = outcome.upper()
        if normalized not in OUTCOMES:
            raise ValueError(f"outcome precisa ser um de {sorted(OUTCOMES)}.")
        if source not in {"MANUAL", "BROKER_API"}:
            raise ValueError("source precisa identificar resultado manual ou API confiável.")
        pnl_value = _finite_optional(pnl, "pnl")
        payout_value = _finite_optional(payout, "payout")
        stake_value = _finite_optional(stake, "stake")
        if stake_value is not None and stake_value <= 0:
            raise ValueError("stake precisa ser positiva.")
        if payout_value is not None and payout_value < 0:
            raise ValueError("payout não pode ser negativo.")
        if normalized == "UNCONFIRMED" and pnl_value is not None:
            raise ValueError("Resultado não confirmado não pode receber P&L.")
        now = _utc_now()
        with self._session() as connection:
            cursor = connection.execute(
                """UPDATE opportunities SET status = 'TRADE_SETTLED', outcome = ?, pnl = ?,
                   outcome_source = ?, settled_at_utc = ?, payout = COALESCE(?, payout),
                   stake = COALESCE(?, stake)
                   WHERE opportunity_id = ? AND order_confirmed = 1""",
                (normalized, pnl_value, source, now, payout_value, stake_value, opportunity_id),
            )
            if cursor.rowcount != 1:
                exists = connection.execute(
                    "SELECT order_confirmed FROM opportunities WHERE opportunity_id = ?",
                    (opportunity_id,),
                ).fetchone()
                if exists is None:
                    raise KeyError(f"Oportunidade inexistente: {opportunity_id}")
                raise ValueError("Não é possível liquidar sem ordem explicitamente confirmada.")
            self._insert_event(
                connection,
                opportunity_id,
                "TRADE_SETTLED",
                source,
                {
                    "outcome": normalized,
                    "pnl": pnl_value,
                    "payout": payout_value,
                    "stake": stake_value,
                },
                occurred_at_utc=now,
            )

    @staticmethod
    def _event_idempotency_key(
        *,
        opportunity_id: str | None,
        session_id: str | None,
        event_type: str,
        source: str,
        payload_json: str,
    ) -> str:
        material = _json({
            "opportunity_id": opportunity_id,
            "session_id": session_id,
            "event_type": event_type,
            "source": source,
            "payload": json.loads(payload_json),
        })
        return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        opportunity_id: str | None,
        event_type: str,
        source: str,
        payload: Mapping[str, Any],
        *,
        session_id: str | None = None,
        occurred_at_utc: str | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"Tipo de evento inválido: {event_type}")
        if not source.strip():
            raise ValueError("source não pode ficar vazio.")
        if session_id is not None and not session_id.strip():
            raise ValueError("session_id não pode ficar vazio.")
        payload_json = _json(dict(payload))
        key = idempotency_key or OpportunityStore._event_idempotency_key(
            opportunity_id=opportunity_id,
            session_id=session_id,
            event_type=event_type,
            source=source,
            payload_json=payload_json,
        )
        if not key.strip():
            raise ValueError("idempotency_key não pode ficar vazio.")
        connection.execute(
            """INSERT OR IGNORE INTO opportunity_events
               (opportunity_id, session_id, event_type, occurred_at_utc,
                source, payload_json, idempotency_key)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                opportunity_id, session_id, event_type,
                occurred_at_utc or _utc_now(), source, payload_json, key,
            ),
        )
        row = connection.execute(
            """SELECT event_id, opportunity_id, session_id, event_type, source, payload_json
               FROM opportunity_events WHERE idempotency_key = ?""",
            (key,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Evento de journal não foi persistido.")
        expected = (opportunity_id, session_id, event_type, source, payload_json)
        actual = (
            row["opportunity_id"], row["session_id"], row["event_type"],
            row["source"], row["payload_json"],
        )
        if actual != expected:
            raise ValueError(
                "idempotency_key já utilizado por evento com payload ou escopo diferente."
            )
        return int(row["event_id"])

    def record_journal_event(
        self,
        event_type: str,
        *,
        source: str,
        payload: Mapping[str, Any],
        opportunity_id: str | None = None,
        session_id: str | None = None,
        occurred_at_utc: str | None = None,
        idempotency_key: str | None = None,
    ) -> int:
        """Append one idempotent event; a retry returns the original event ID."""
        with self._session() as connection:
            return self._insert_event(
                connection,
                opportunity_id,
                event_type,
                source,
                payload,
                session_id=session_id,
                occurred_at_utc=occurred_at_utc,
                idempotency_key=idempotency_key,
            )

    def list_journal_events(
        self, *, session_id: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        with self._session() as connection:
            if session_id is None:
                rows = connection.execute(
                    "SELECT * FROM opportunity_events ORDER BY event_id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT * FROM opportunity_events WHERE session_id = ?
                       ORDER BY event_id DESC LIMIT ?""",
                    (session_id, int(limit)),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_open_capture_sessions(self) -> list[dict[str, Any]]:
        """Find capture sessions lacking an explicit stop/interruption event."""
        with self._session() as connection:
            rows = connection.execute(
                """SELECT started.session_id,
                          MIN(started.occurred_at_utc) AS started_at_utc,
                          MAX(all_events.occurred_at_utc) AS last_event_at_utc,
                          COUNT(*) AS event_count
                   FROM opportunity_events AS started
                   JOIN opportunity_events AS all_events
                     ON all_events.session_id = started.session_id
                   WHERE started.event_type = 'CAPTURE_SESSION_STARTED'
                     AND started.session_id IS NOT NULL
                   GROUP BY started.session_id
                   HAVING SUM(CASE WHEN all_events.event_type IN
                       ('CAPTURE_SESSION_STOPPED', 'CAPTURE_SESSION_INTERRUPTED')
                       THEN 1 ELSE 0 END) = 0
                   ORDER BY started_at_utc"""
            ).fetchall()
        return [dict(row) for row in rows]

    def reconcile_capture_session(
        self,
        session_id: str,
        *,
        confirmed_inactive: bool,
        reason: str = "PROCESS_ENDED_WITHOUT_STOP_EVENT",
    ) -> int:
        """Append an interruption marker only after an operator confirms inactivity."""
        if not confirmed_inactive:
            raise ValueError(
                "Confirme que a captura desta sessão não está ativa antes de reconciliar."
            )
        if not session_id.strip():
            raise ValueError("session_id não pode ficar vazio.")
        key = f"{session_id}:capture-session-interrupted"
        payload = {"reason": reason, "operator_confirmed_inactive": True}
        with self._session() as connection:
            existing_reconciliation = connection.execute(
                """SELECT event_id, event_type, source, session_id, payload_json
                   FROM opportunity_events WHERE idempotency_key = ?""",
                (key,),
            ).fetchone()
            if existing_reconciliation is not None:
                if (
                    existing_reconciliation["event_type"] != "CAPTURE_SESSION_INTERRUPTED"
                    or existing_reconciliation["source"] != "MANUAL_RECOVERY"
                    or existing_reconciliation["session_id"] != session_id
                    or existing_reconciliation["payload_json"] != _json(payload)
                ):
                    raise ValueError(
                        "A chave de reconciliação já foi usada com outro conteúdo."
                    )
                return int(existing_reconciliation["event_id"])
            session = connection.execute(
                """SELECT
                       SUM(CASE WHEN event_type = 'CAPTURE_SESSION_STARTED' THEN 1 ELSE 0 END) AS starts,
                       SUM(CASE WHEN event_type IN
                           ('CAPTURE_SESSION_STOPPED','CAPTURE_SESSION_INTERRUPTED')
                           THEN 1 ELSE 0 END) AS terminals
                   FROM opportunity_events WHERE session_id = ?""",
                (session_id,),
            ).fetchone()
            if session is None or not session["starts"]:
                raise KeyError(f"Sessão de captura não encontrada: {session_id}")
            if session["terminals"]:
                raise ValueError("A sessão já possui evento terminal; nenhuma alteração foi feita.")
            return self._insert_event(
                connection,
                None,
                "CAPTURE_SESSION_INTERRUPTED",
                "MANUAL_RECOVERY",
                payload,
                session_id=session_id,
                idempotency_key=key,
            )

    def reconcile_open_capture_sessions(
        self,
        *,
        confirmed_inactive: bool,
        reason: str = "PROCESS_ENDED_WITHOUT_STOP_EVENT",
    ) -> list[str]:
        """Explicitly mark orphan sessions interrupted; never called automatically."""
        if not confirmed_inactive:
            raise ValueError("A reconciliação exige confirmação explícita de captura inativa.")
        session_ids = [row["session_id"] for row in self.list_open_capture_sessions()]
        for session_id in session_ids:
            self.reconcile_capture_session(
                str(session_id),
                confirmed_inactive=True,
                reason=reason,
            )
        return [str(session_id) for session_id in session_ids]

    def list_unresolved_executions(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """Return attempts without a verified terminal order state; never auto-retry."""
        if limit < 1:
            return []
        with self._session() as connection:
            rows = connection.execute(
                """SELECT * FROM opportunities
                   WHERE status IN ('CLICK_SENT', 'EXECUTION_UNCONFIRMED')
                     AND order_confirmed IS NULL
                   ORDER BY execution_attempt_at_utc LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def integrity_report(self) -> dict[str, Any]:
        """Read-only SQLite and journal consistency checks for startup/recovery."""
        with self._session() as connection:
            integrity_rows = connection.execute("PRAGMA quick_check").fetchall()
            foreign_key_rows = connection.execute("PRAGMA foreign_key_check").fetchall()
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            counts = {
                "opportunities": int(connection.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]),
                "events": int(connection.execute("SELECT COUNT(*) FROM opportunity_events").fetchone()[0]),
                "signal_tracks": int(connection.execute("SELECT COUNT(*) FROM signal_tracks").fetchone()[0]),
            }
        return {
            "schema_version": version,
            "integrity": [str(row[0]) for row in integrity_rows],
            "foreign_key_violations": [tuple(row) for row in foreign_key_rows],
            "counts": counts,
            "healthy": (
                version == SCHEMA_VERSION
                and len(integrity_rows) == 1
                and str(integrity_rows[0][0]).lower() == "ok"
                and not foreign_key_rows
            ),
        }

    def recovery_snapshot(self) -> dict[str, Any]:
        """Inspect integrity and unclosed sessions without replaying any action."""
        return {
            "integrity": self.integrity_report(),
            "unresolved_executions": self.list_unresolved_executions(),
            "open_capture_sessions": self.list_open_capture_sessions(),
        }

    def get_opportunity(self, opportunity_id: str) -> dict[str, Any] | None:
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM opportunities WHERE opportunity_id = ?", (opportunity_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def list_opportunities(self, *, limit: int = 500) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        with self._session() as connection:
            rows = connection.execute(
                "SELECT * FROM opportunities ORDER BY signal_at_utc DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, opportunity_id: str) -> list[dict[str, Any]]:
        with self._session() as connection:
            rows = connection.execute(
                "SELECT * FROM opportunity_events WHERE opportunity_id = ? ORDER BY event_id",
                (opportunity_id,),
            ).fetchall()
        return [dict(row) for row in rows]
