from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TVMetrics:
    net_profit_pct: float
    max_drawdown_pct: float
    profit_factor: float
    trade_count: int
    win_rate_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["net_profit_pct"] = round(self.net_profit_pct, 4)
        payload["max_drawdown_pct"] = round(self.max_drawdown_pct, 4)
        payload["profit_factor"] = round(self.profit_factor, 4)
        payload["win_rate_pct"] = round(self.win_rate_pct, 4)
        return payload


@dataclass(frozen=True)
class TVRunResult:
    strategy_slug: str
    symbol: str
    timeframe: str
    params: dict[str, Any]
    metrics: TVMetrics
    gate_passed: bool
    collected_at_utc: str
    run_id: str
    source_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_slug": self.strategy_slug,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "params": self.params,
            "metrics": self.metrics.to_dict(),
            "gate_passed": self.gate_passed,
            "collected_at_utc": self.collected_at_utc,
            "run_id": self.run_id,
            "source_hash": self.source_hash,
        }
