from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    leaderboard_path = root / "results" / "tv_optimizations_local_full" / "leaderboard.json"
    out_dir = root / "strategies" / "optimized_local_mock"
    out_dir.mkdir(parents=True, exist_ok=True)

    items = json.loads(leaderboard_path.read_text(encoding="utf-8"))["items"]
    items = sorted(items, key=lambda x: float(x["metrics"]["net_profit_pct"]), reverse=True)

    def find_source(strategy_slug: str) -> Path:
        cands = list((root / "strategies" / "raw_split").glob(f"*{strategy_slug}.pine"))
        if not cands:
            raise FileNotFoundError(f"No source for {strategy_slug}")
        return cands[0]

    def write_export(row: dict, rank: int, tag: str) -> Path:
        strategy = row["strategy"]
        symbol = row["symbol"]
        tf = row["timeframe"]
        m = row["metrics"]
        source = find_source(strategy)
        src_text = source.read_text(encoding="utf-8")
        safe_symbol = symbol.replace(":", "_").replace("/", "_")
        filename = (
            f"{tag}_r{rank:02d}_{safe_symbol}_{tf}_{strategy}"
            f"_np{float(m['net_profit_pct']):.2f}_dd{float(m['max_drawdown_pct']):.2f}"
            f"_pf{float(m['profit_factor']):.2f}_tc{int(m['trade_count'])}.pine"
        )
        target = out_dir / filename
        header = [
            "// --- Local batch export (mock collector) ---",
            f"// strategy={strategy}",
            f"// symbol={symbol}",
            f"// timeframe={tf}",
            f"// net_profit_pct={float(m['net_profit_pct']):.2f}",
            f"// max_drawdown_pct={float(m['max_drawdown_pct']):.2f}",
            f"// profit_factor={float(m['profit_factor']):.2f}",
            f"// trade_count={int(m['trade_count'])}",
            f"// gate_passed={bool(row.get('gate_passed'))}",
            f"// source_file={source}",
            "",
        ]
        target.write_text("\n".join(header) + src_text, encoding="utf-8")
        return target

    best_path = write_export(items[0], 1, "best_overall")
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in items:
        key = (row["symbol"], row["timeframe"])
        groups.setdefault(key, []).append(row)

    exports = [best_path]
    for key, rows in sorted(groups.items()):
        key_slug = f"{key[0].replace(':', '_')}_{key[1]}"
        for idx, row in enumerate(rows[:5], 1):
            exports.append(write_export(row, idx, f"top5_{key_slug}"))

    summary = out_dir / "EXPORT_SUMMARY.md"
    lines = ["# Exported Pine Files (Local Mock Ranking)", ""]
    lines.extend(f"- {path.name}" for path in exports)
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"EXPORTED {len(exports)} files")
    print(f"SUMMARY {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
