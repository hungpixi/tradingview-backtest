from __future__ import annotations

from .models import TVMetrics


def balanced_gate(metrics: TVMetrics) -> bool:
    return (
        metrics.net_profit_pct > 0.0
        and metrics.profit_factor >= 1.2
        and metrics.max_drawdown_pct <= 25.0
        and metrics.trade_count >= 30
    )
