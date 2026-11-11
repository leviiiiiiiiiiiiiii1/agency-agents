import unittest

from auto_trader_iq.signal_detector import extract_clock_tokens


def data(tokens, conf=None, left=None, top=None):
    count = len(tokens)
    return {
        "text": tokens,
        "conf": conf or [90] * count,
        "left": left or [10] * count,
        "top": top or [20] * count,
    }


class ClockProbeTests(unittest.TestCase):
    def test_finds_time_and_clock_words_with_positions(self):
        probe = extract_clock_tokens(
            data(
                ["HORA", "ATUAL", "31", "21:44:50", "PETR4"],
                left=[100, 180, 220, 400, 50],
                top=[900, 900, 900, 900, 500],
            ),
            width=1000,
            height=1000,
        )
        self.assertEqual([item["text"] for item in probe["time_tokens"]], ["21:44:50"])
        self.assertEqual(probe["time_tokens"][0]["x_percent"], 40.0)
        self.assertEqual(probe["time_tokens"][0]["y_percent"], 90.0)
        self.assertEqual([item["text"] for item in probe["clock_words"]], ["HORA", "ATUAL"])

    def test_never_keeps_other_chart_text(self):
        probe = extract_clock_tokens(
            data(["PETR4", "R$", "32,18", "COMPRA", "21:44"]),
            width=1000,
            height=1000,
        )
        self.assertEqual([item["text"] for item in probe["time_tokens"]], ["21:44"])
        self.assertEqual(probe["clock_words"], [])
        # Nomes de ativo, preços e rótulos viram apenas contagem.
        self.assertEqual(probe["other_token_count"], 4)

    def test_accepts_hour_without_seconds_and_rejects_partial_shapes(self):
        probe = extract_clock_tokens(
            data(["9:05", "123:45", "21:44:50:1", "21h44"]),
            width=100,
            height=100,
        )
        self.assertEqual([item["text"] for item in probe["time_tokens"]], ["9:05"])

    def test_grid_locates_where_text_appears(self):
        probe = extract_clock_tokens(
            data(["A", "B", "C"], left=[10, 500, 990], top=[10, 500, 990]),
            width=1000,
            height=1000,
        )
        self.assertEqual(probe["grid_token_counts"], [[1, 0, 0], [0, 1, 0], [0, 0, 1]])

    def test_empty_ocr_result_is_reported_as_empty(self):
        probe = extract_clock_tokens({"text": []}, width=800, height=600)
        self.assertEqual(probe["time_tokens"], [])
        self.assertEqual(probe["clock_words"], [])
        self.assertEqual(probe["other_token_count"], 0)
        self.assertEqual(probe["frame_width"], 800)
        self.assertEqual(probe["grid_token_counts"], [[0, 0, 0], [0, 0, 0], [0, 0, 0]])


if __name__ == "__main__":
    unittest.main()
