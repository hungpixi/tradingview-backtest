from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
from typing import Any

from ..pine.splitter import split_pine_bundle
from ..tv_runner import TradingViewCollector, balanced_gate, parse_pine_inputs
from ..tv_runner.inputs import default_params, to_dimensions
from ..tv_runner.models import TVRunResult


def run_pine_split(args: argparse.Namespace, _config: dict[str, Any]) -> int:
    blocks = split_pine_bundle(args.input, args.out)
    strategies = [item for item in blocks if item.kind == "strategy"]
    indicators = [item for item in blocks if item.kind == "indicator"]
    print(f"✔ Split done: {len(strategies)} strategy, {len(indicators)} indicator")
    print(f"✔ Output dir: {Path(args.out)}")
    return 0


def run_tv_backtest_batch(args: argparse.Namespace, _config: dict[str, Any]) -> int:
    collector = TradingViewCollector(args.collector_cmd)
    input_dir = Path(args.input_dir)
    pine_files = sorted(input_dir.glob("*.pine"))
    if not pine_files:
        print(f"Error: no .pine files found in {input_dir}")
        return 1

    symbols = args.symbols
    timeframes = args.timeframes
    run_id = _utc_run_id()
    report_root = Path(args.report_root)
    leaderboard: list[dict[str, Any]] = []
    failures = 0
    for pine_file in pine_files:
        source_text = pine_file.read_text(encoding="utf-8")
        params = default_params(parse_pine_inputs(source_text))
        strategy_slug = pine_file.stem
        source_hash = _sha1(source_text)
        for symbol in symbols:
            for timeframe in timeframes:
                try:
                    metrics = collector.collect(
                        strategy_file=str(pine_file),
                        symbol=symbol,
                        timeframe=timeframe,
                        params=params,
                        start=args.start,
                        end=args.end,
                        timeout_seconds=args.timeout_seconds,
                    )
                except Exception as exc:
                    failures += 1
                    print(f"   • failed {pine_file.name} {symbol} {timeframe}: {exc}")
                    continue
                result = TVRunResult(
                    strategy_slug=strategy_slug,
                    symbol=symbol,
                    timeframe=timeframe,
                    params=params,
                    metrics=metrics,
                    gate_passed=balanced_gate(metrics),
                    collected_at_utc=_utc_now(),
                    run_id=run_id,
                    source_hash=source_hash,
                )
                out_dir = report_root / _safe_symbol(symbol) / timeframe.lower() / strategy_slug
                out_dir.mkdir(parents=True, exist_ok=True)
                context_path = out_dir / "context.json"
                context_path.write_text(json.dumps({"engine": "tradingview_ui", "result": result.to_dict()}, indent=2) + "\n", encoding="utf-8")
                leaderboard.append(
                    {
                        "strategy": strategy_slug,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "metrics": result.metrics.to_dict(),
                        "gate_passed": result.gate_passed,
                        "context_file": str(context_path),
                    }
                )
                print(f"✔ backtest {pine_file.name} {symbol} {timeframe}")

    _write_leaderboard(report_root, leaderboard)
    if failures > 0:
        print(f"⚠ Completed with failures: {failures}")
        return 1
    return 0


def run_tv_optimize(args: argparse.Namespace, _config: dict[str, Any]) -> int:
    collector = TradingViewCollector(args.collector_cmd)
    input_dir = Path(args.input_dir)
    pine_files = sorted(input_dir.glob("*.pine"))
    if not pine_files:
        print(f"Error: no .pine files found in {input_dir}")
        return 1
    run_id = _utc_run_id()
    rng = random.Random(args.seed)
    report_root = Path(args.report_root)
    leaderboard_rows: list[dict[str, Any]] = []
    failures = 0
    for pine_file in pine_files:
        source_text = pine_file.read_text(encoding="utf-8")
        specs = parse_pine_inputs(source_text)
        dims = to_dimensions(specs)
        base = default_params(specs)
        if not dims:
            print(f"   • skip {pine_file.name}: no optimizable inputs")
            continue
        strategy_slug = pine_file.stem
        source_hash = _sha1(source_text)
        for symbol in args.symbols:
            for timeframe in args.timeframes:
                candidates: list[TVRunResult] = []
                for _ in range(max(1, args.coarse_trials)):
                    params = _sample_params(dims, base, rng)
                    try:
                        metrics = collector.collect(
                            strategy_file=str(pine_file),
                            symbol=symbol,
                            timeframe=timeframe,
                            params=params,
                            start=args.start,
                            end=args.end,
                            timeout_seconds=args.timeout_seconds,
                        )
                    except Exception as exc:
                        failures += 1
                        print(f"   • coarse failed {pine_file.name} {symbol} {timeframe}: {exc}")
                        continue
                    candidates.append(
                        TVRunResult(
                            strategy_slug=strategy_slug,
                            symbol=symbol,
                            timeframe=timeframe,
                            params=params,
                            metrics=metrics,
                            gate_passed=balanced_gate(metrics),
                            collected_at_utc=_utc_now(),
                            run_id=run_id,
                            source_hash=source_hash,
                        )
                    )
                if not candidates:
                    continue
                candidates.sort(key=lambda x: x.metrics.net_profit_pct, reverse=True)
                seeds = candidates[: max(1, args.top_k)]
                for seed in seeds:
                    for _ in range(max(1, args.fine_trials)):
                        params = _nearby_params(seed.params, dims, rng, args.fine_span_ratio)
                        try:
                            metrics = collector.collect(
                                strategy_file=str(pine_file),
                                symbol=symbol,
                                timeframe=timeframe,
                                params=params,
                                start=args.start,
                                end=args.end,
                                timeout_seconds=args.timeout_seconds,
                            )
                        except Exception as exc:
                            failures += 1
                            print(f"   • fine failed {pine_file.name} {symbol} {timeframe}: {exc}")
                            continue
                        candidates.append(
                            TVRunResult(
                                strategy_slug=strategy_slug,
                                symbol=symbol,
                                timeframe=timeframe,
                                params=params,
                                metrics=metrics,
                                gate_passed=balanced_gate(metrics),
                                collected_at_utc=_utc_now(),
                                run_id=run_id,
                                source_hash=source_hash,
                            )
                        )
                candidates.sort(key=lambda x: x.metrics.net_profit_pct, reverse=True)
                top = candidates[: max(1, args.top_n)]
                out_dir = report_root / _safe_symbol(symbol) / timeframe.lower() / strategy_slug
                out_dir.mkdir(parents=True, exist_ok=True)
                context_payload = {
                    "engine": "tradingview_ui",
                    "run_id": run_id,
                    "strategy_slug": strategy_slug,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "source_hash": source_hash,
                    "gate": "balanced",
                    "candidates": [item.to_dict() for item in top],
                }
                context_path = out_dir / "context.json"
                context_path.write_text(json.dumps(context_payload, indent=2) + "\n", encoding="utf-8")
                if top:
                    best = top[0]
                    leaderboard_rows.append(
                        {
                            "strategy": strategy_slug,
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "metrics": best.metrics.to_dict(),
                            "gate_passed": best.gate_passed,
                            "context_file": str(context_path),
                        }
                    )
                print(f"✔ optimize {pine_file.name} {symbol} {timeframe}")

    _write_leaderboard(report_root, leaderboard_rows)
    if failures > 0:
        print(f"⚠ Completed with failures: {failures}")
        return 1
    return 0


def _safe_symbol(value: str) -> str:
    return value.replace(":", "_").replace("/", "_")


def _utc_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _sample_params(dimensions: list[dict[str, Any]], base: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    params = dict(base)
    for item in dimensions:
        name = item["name"]
        kind = item["kind"]
        if kind == "categorical":
            values = list(item["values"])
            if values:
                params[name] = rng.choice(values)
            continue
        if kind == "int":
            step = max(1, int(item["step"]))
            low = int(item["minval"])
            high = int(item["maxval"])
            points = list(range(low, high + 1, step))
            params[name] = rng.choice(points) if points else int(item["default"])
            continue
        if kind == "float":
            low = float(item["minval"])
            high = float(item["maxval"])
            step = max(0.0001, float(item["step"]))
            points = int((high - low) / step)
            if points <= 1:
                params[name] = round(low, 6)
            else:
                value = low + rng.randint(0, points) * step
                params[name] = round(value, 6)
    return params


def _nearby_params(seed: dict[str, Any], dimensions: list[dict[str, Any]], rng: random.Random, span_ratio: float) -> dict[str, Any]:
    params = dict(seed)
    for item in dimensions:
        name = item["name"]
        kind = item["kind"]
        if kind == "categorical":
            values = list(item["values"])
            if values and rng.random() < 0.25:
                params[name] = rng.choice(values)
            continue
        if kind == "int":
            low = int(item["minval"])
            high = int(item["maxval"])
            step = max(1, int(item["step"]))
            current = int(params.get(name, item["default"]))
            span = max(step, int((high - low) * max(0.05, span_ratio)))
            near_low = max(low, current - span)
            near_high = min(high, current + span)
            points = list(range(near_low, near_high + 1, step))
            if points:
                params[name] = rng.choice(points)
            continue
        if kind == "float":
            low = float(item["minval"])
            high = float(item["maxval"])
            step = max(0.0001, float(item["step"]))
            current = float(params.get(name, item["default"]))
            span = max(step, (high - low) * max(0.05, span_ratio))
            near_low = max(low, current - span)
            near_high = min(high, current + span)
            if near_high <= near_low:
                params[name] = round(near_low, 6)
            else:
                value = rng.uniform(near_low, near_high)
                snapped = round((value - low) / step) * step + low
                params[name] = round(min(high, max(low, snapped)), 6)
    return params


def _write_leaderboard(report_root: Path, rows: list[dict[str, Any]]) -> None:
    report_root.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda item: float(item["metrics"].get("net_profit_pct", 0.0)), reverse=True)
    (report_root / "leaderboard.json").write_text(json.dumps({"items": rows}, indent=2) + "\n", encoding="utf-8")
    lines = ["# TradingView UI Leaderboard", ""]
    if not rows:
        lines.extend(["_No successful runs._", ""])
    else:
        lines.append("| rank | strategy | symbol | tf | np% | dd% | pf | trades | gate | context |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for idx, row in enumerate(rows, start=1):
            metrics = row["metrics"]
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(idx),
                        str(row["strategy"]),
                        str(row["symbol"]),
                        str(row["timeframe"]),
                        f"{float(metrics.get('net_profit_pct', 0.0)):.2f}",
                        f"{float(metrics.get('max_drawdown_pct', 0.0)):.2f}",
                        f"{float(metrics.get('profit_factor', 0.0)):.2f}",
                        str(int(metrics.get("trade_count", 0))),
                        "yes" if row.get("gate_passed") else "no",
                        str(row.get("context_file", "")),
                    ]
                )
                + " |"
            )
        lines.append("")
    (report_root / "leaderboard.md").write_text("\n".join(lines), encoding="utf-8")
