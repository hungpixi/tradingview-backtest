from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

from .models import TVMetrics


class TradingViewCollector:
    """Collect TradingView metrics through an external command."""

    def __init__(self, collector_cmd: str) -> None:
        self.collector_cmd = collector_cmd.strip()
        if not self.collector_cmd:
            raise ValueError("collector_cmd must be non-empty")

    def collect(
        self,
        *,
        strategy_file: str,
        symbol: str,
        timeframe: str,
        params: dict[str, Any],
        start: str | None,
        end: str | None,
        timeout_seconds: int = 180,
    ) -> TVMetrics:
        payload = {
            "strategy_file": strategy_file,
            "symbol": symbol,
            "timeframe": timeframe,
            "params": params,
            "start": start,
            "end": end,
        }
        cmd = self.collector_cmd
        env = dict(os.environ)
        env["TV_RUNNER_PAYLOAD"] = json.dumps(payload)

        completed = subprocess.run(
            cmd,
            shell=True,
            text=True,
            capture_output=True,
            env=env,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "collector command failed "
                f"(code={completed.returncode}): {completed.stderr.strip() or completed.stdout.strip()}"
            )
        raw = completed.stdout.strip()
        if not raw:
            raise RuntimeError("collector command returned empty output")
        data = _load_json(raw)
        return TVMetrics(
            net_profit_pct=float(data["net_profit_pct"]),
            max_drawdown_pct=float(data["max_drawdown_pct"]),
            profit_factor=float(data["profit_factor"]),
            trade_count=int(data["trade_count"]),
            win_rate_pct=float(data.get("win_rate_pct", 0.0)),
        )


def _load_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        path = Path(raw)
        if not path.is_file():
            raise
        return json.loads(path.read_text(encoding="utf-8"))
