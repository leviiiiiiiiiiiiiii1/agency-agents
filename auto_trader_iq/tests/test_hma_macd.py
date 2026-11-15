import math
import random
import unittest

from auto_trader_iq.hma_macd import (
    BLOCK_LATERAL,
    HmaMacdConfig,
    backtest,
    confirmation_lags,
    direction_of,
    ema,
    generate_signals,
    hma,
    load_config,
    macd,
    save_config,
    series_from_ladder,
    wma,
)


def reference_wma(values, period):
    out = [None] * len(values)
    total = period * (period + 1) / 2
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        if any(v is None for v in window):
            continue
        out[i] = sum((k + 1) * v for k, v in enumerate(window)) / total
    return out


def reference_hma(values, period=16):
    half = max(1, period // 2)
    root = max(1, int(math.sqrt(period)))
    fast = reference_wma(values, half)
    slow = reference_wma(values, period)
    raw = [None if fast[i] is None or slow[i] is None else 2 * fast[i] - slow[i]
           for i in range(len(values))]
    return reference_wma(raw, root)


def reference_ema(values, period):
    out = [None] * len(values)
    alpha = 2 / (period + 1)
    seed = None
    seen = 0
    total = 0.0
    for i, v in enumerate(values):
        if v is None:
            continue
        if seed is None:
            total += v
            seen += 1
            if seen == period:
                seed = total / period
                out[i] = seed
            continue
        seed = alpha * v + (1 - alpha) * seed
        out[i] = seed
    return out


def walk(seed=7, size=600, drift=0.0, noise=1.0, wave=0.0, period=18):
    random.seed(seed)
    values = []
    level = 100.0
    for i in range(size):
        level += drift + random.gauss(0, noise)
        values.append(level + wave * math.sin(i / period))
    return values


class IndicatorTests(unittest.TestCase):
    def test_wma_matches_the_definition(self):
        values = walk(size=80)
        self.assertEqual(wma(values, 5), reference_wma(values, 5))

    def test_hma_matches_the_definition(self):
        values = walk(size=200)
        produced = hma(values, 16)
        expected = reference_hma(values, 16)
        for got, want in zip(produced, expected):
            if want is None:
                self.assertIsNone(got)
            else:
                self.assertAlmostEqual(got, want, places=9)

    def test_hma_is_flat_on_a_flat_series(self):
        values = [50.0] * 60
        series = hma(values, 16)
        self.assertAlmostEqual(series[-1], 50.0, places=9)
        self.assertTrue(all(value == 0 for value in direction_of(series)))

    def test_ema_matches_the_reference_and_keeps_constants(self):
        values = walk(size=120)
        self.assertEqual(ema(values, 12), reference_ema(values, 12))
        self.assertAlmostEqual(ema([30.0] * 40, 12)[-1], 30.0, places=9)

    def test_macd_histogram_is_line_minus_signal(self):
        values = walk(size=200)
        line, signal, histogram = macd(values)
        for i in range(len(values)):
            if None in (line[i], signal[i], histogram[i]):
                self.assertIsNone(histogram[i])
            else:
                self.assertAlmostEqual(histogram[i], line[i] - signal[i], places=9)

    def test_a_too_short_series_returns_no_readings(self):
        self.assertTrue(all(value is None for value in macd([1.0] * 10)[0]))


class SignalTests(unittest.TestCase):
    def config(self, **kwargs):
        base = dict(
            confirm_window=60,
            block_lateral=False,
            block_weak_hist=False,
            block_volatility=False,
            min_slope_units=0.0,
        )
        base.update(kwargs)
        return HmaMacdConfig(**base)

    def test_signals_exist_and_their_ids_are_unique(self):
        signals = generate_signals(walk(size=900), self.config())
        self.assertGreater(len(signals), 0)
        self.assertEqual(len({item.signal_id for item in signals}), len(signals))

    def test_the_entry_is_the_candle_after_the_confirmation(self):
        for signal in generate_signals(walk(size=900), self.config()):
            self.assertEqual(signal.entry_index, signal.confirm_index + 1)
            self.assertGreaterEqual(signal.confirm_index, signal.turn_index)
            self.assertLessEqual(signal.lag, 60)

    def test_no_signal_reads_a_future_candle(self):
        values = walk(size=800)
        full = generate_signals(values, self.config())
        prefix = generate_signals(values[:500], self.config())
        stable = [item for item in full if item.confirm_index < 495]
        self.assertEqual(
            [(item.signal_id, item.direction, item.blocked) for item in stable],
            [(item.signal_id, item.direction, item.blocked) for item in prefix],
        )

    def test_a_zero_window_requires_the_cross_on_the_turn_candle(self):
        for signal in generate_signals(walk(size=900), self.config(confirm_window=0)):
            self.assertEqual(signal.lag, 0)

    def test_a_choppy_market_is_blocked_as_lateral(self):
        values = [100 + (2 if i % 2 else -2) + i * 0.01 for i in range(600)]
        clean = generate_signals(values, self.config())
        self.assertGreater(len(clean), 0)
        guarded = generate_signals(
            values,
            self.config(block_lateral=True, max_direction_changes=0, lateral_lookback=12),
        )
        self.assertTrue(guarded)
        self.assertTrue(all(BLOCK_LATERAL in item.blocked for item in guarded))

    def test_a_low_payout_blocks_every_signal(self):
        signals = generate_signals(
            walk(size=600), self.config(min_payout=0.9), payout=0.86
        )
        self.assertTrue(all("payout insuficiente" in item.blocked for item in signals))

    def test_hours_outside_the_window_are_blocked(self):
        values = walk(size=600)
        hours = [9] * len(values)
        signals = generate_signals(values, self.config(allowed_hours=(10, 11)), hours=hours)
        self.assertTrue(all("fora do horário permitido" in item.blocked for item in signals))


class BacktestTests(unittest.TestCase):
    def test_net_matches_the_payout_arithmetic(self):
        config = HmaMacdConfig(
            confirm_window=60,
            block_lateral=False,
            block_weak_hist=False,
            block_volatility=False,
            min_slope_units=0.0,
        )
        stats = backtest(walk(size=900), config, payout=0.86, stake=2.0, expiry_bars=1)
        self.assertGreater(stats.executed, 0)
        expected = stats.wins * 2.0 * 0.86 - (stats.losses + stats.draws) * 2.0
        self.assertAlmostEqual(stats.net, expected, places=9)

    def test_direction_wins_when_price_moves_its_way(self):
        config = HmaMacdConfig(
            confirm_window=60,
            block_lateral=False,
            block_weak_hist=False,
            block_volatility=False,
            min_slope_units=0.0,
            expiry_bars=1,
        )
        # Só altas: uma compra confirmada tem de ganhar.
        values = [100 + i for i in range(400)]
        stats = backtest(values, config, payout=0.9)
        self.assertEqual(stats.losses, 0)

    def test_confirmation_lags_reports_the_distance_to_the_cross(self):
        found = confirmation_lags(walk(size=900, wave=6.0), HmaMacdConfig())
        self.assertGreater(found["turns"], 0)
        self.assertIsNotNone(found["median"])
        self.assertEqual(found["lags"], sorted(found["lags"]))


class ConfigTests(unittest.TestCase):
    def test_round_trip_keeps_every_field(self):
        config = HmaMacdConfig(
            hma_period=20, macd_fast=8, macd_slow=21, macd_signal=5, expiry_bars=3,
            allowed_hours=(9, 10, 11), allowed_assets=("EURUSD",),
        )
        settings = save_config({"region": {"x": 1}}, config)
        self.assertEqual(settings["region"], {"x": 1})
        self.assertEqual(load_config(settings), config)

    def test_missing_section_falls_back_to_the_defaults(self):
        self.assertEqual(load_config({}), HmaMacdConfig())

    def test_junk_fields_do_not_destroy_the_rest(self):
        settings = {"hma_macd": {"hma_period": "abc", "macd_fast": 5, "extra": 1}}
        config = load_config(settings)
        self.assertEqual(config.hma_period, 16)
        self.assertEqual(config.macd_fast, 5)

    def test_invalid_numbers_are_refused(self):
        with self.assertRaises(ValueError):
            HmaMacdConfig(macd_fast=30, macd_slow=26)
        with self.assertRaises(ValueError):
            HmaMacdConfig(hma_period=1)


class LadderTests(unittest.TestCase):
    def frame(self, at, closes, session="s1"):
        return {
            "occurred_at_utc": at,
            "session_id": session,
            "price_ladder": {"closes_px": closes, "median_range_px": 10.0},
        }

    def test_pixels_are_inverted_once(self):
        frames = [
            self.frame("2026-11-12T10:00:00+00:00", [100.0, 110.0]),
            self.frame("2026-11-12T10:01:00+00:00", [90.0, 100.0, 110.0]),
        ]
        series = series_from_ladder(frames)
        self.assertEqual(len(series), 1)
        # y menor = preço maior: -90 é o topo da série.
        self.assertEqual(list(series[0].closes), [-110.0, -100.0, -90.0])

    def test_a_long_gap_starts_a_new_series(self):
        frames = [
            self.frame("2026-11-12T10:00:00+00:00", [100.0]),
            self.frame("2026-11-12T10:01:00+00:00", [99.0]),
            self.frame("2026-11-12T10:40:00+00:00", [80.0]),
            self.frame("2026-11-12T10:41:00+00:00", [79.0]),
        ]
        series = series_from_ladder(frames)
        self.assertEqual(len(series), 2)
        self.assertEqual([len(item) for item in series], [2, 2])

    def test_sessions_are_never_joined(self):
        frames = [
            self.frame("2026-11-12T10:00:00+00:00", [100.0], session="a"),
            self.frame("2026-11-12T10:01:00+00:00", [99.0], session="a"),
            self.frame("2026-11-12T10:00:00+00:00", [100.0], session="b"),
            self.frame("2026-11-12T10:01:00+00:00", [99.0], session="b"),
        ]
        self.assertEqual(len(series_from_ladder(frames)), 2)


if __name__ == "__main__":
    unittest.main()
