"""Regression checks for station accents and closing-result semantics."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CashColorUiTest(unittest.TestCase):
    def test_station_identity_has_two_distinct_palette_classes(self):
        js = (ROOT / "static/app.js").read_text()
        css = (ROOT / "static/signature.css").read_text()
        self.assertIn('data-cash="${state.cash}"', js)
        self.assertIn('cash-station-${state.cash}', js)
        self.assertIn('class="cash-one ', js)
        self.assertIn('class="cash-two ', js)
        self.assertIn('.cash-toggle button.cash-one.active', css)
        self.assertIn('.cash-toggle button.cash-two.active', css)
        self.assertIn('#9f77eb', css)  # violet
        self.assertIn('#d78a5c', css)  # copper

    def test_shortage_and_surplus_have_independent_colors(self):
        js = (ROOT / "static/app.js").read_text()
        css = (ROOT / "static/signature.css").read_text()
        self.assertIn("delta>0?'shortage':'surplus'", js)
        self.assertIn("delta>0?'Ammanco: mancano contanti fisici'", js)
        self.assertIn("'Eccedenza: contanti fisici in più'", js)
        self.assertIn('function archiveDifferenceRow(delta)', js)
        self.assertIn('function archiveDifference(delta)', js)
        self.assertIn('.result-box.shortage', css)
        self.assertIn('.result-box.surplus', css)
        self.assertIn('.archive-balance.shortage', css)
        self.assertIn('.archive-balance.surplus', css)


if __name__ == '__main__':
    unittest.main()