from __future__ import annotations

import hashlib
import json
import os


def main() -> int:
    raw = os.environ.get("TV_RUNNER_PAYLOAD", "{}")
    payload = json.loads(raw)
    seed_text = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha1(seed_text.encode("utf-8")).hexdigest()
    seed = int(digest[:8], 16)

    net_profit_pct = (seed % 3500) / 100.0 - 5.0
    max_drawdown_pct = 8.0 + (seed % 1800) / 100.0
    profit_factor = 0.8 + (seed % 170) / 100.0
    trade_count = 10 + (seed % 120)
    win_rate_pct = 35.0 + (seed % 4500) / 100.0

    output = {
        "net_profit_pct": round(net_profit_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "profit_factor": round(profit_factor, 4),
        "trade_count": int(trade_count),
        "win_rate_pct": round(win_rate_pct, 4),
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
