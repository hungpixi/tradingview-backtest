from __future__ import annotations

import unittest

from hyperview.tv_runner.gates import balanced_gate
from hyperview.tv_runner.models import TVMetrics


class TVGateTests(unittest.TestCase):
    def test_balanced_gate_accepts_good_metrics(self) -> None:
        metrics = TVMetrics(
            net_profit_pct=12.5,
            max_drawdown_pct=20.0,
            profit_factor=1.4,
            trade_count=40,
            win_rate_pct=53.0,
        )
        self.assertTrue(balanced_gate(metrics))

    def test_balanced_gate_rejects_low_trade_count(self) -> None:
        metrics = TVMetrics(
            net_profit_pct=12.5,
            max_drawdown_pct=20.0,
            profit_factor=1.4,
            trade_count=20,
            win_rate_pct=53.0,
        )
        self.assertFalse(balanced_gate(metrics))


if __name__ == "__main__":
    unittest.main()
