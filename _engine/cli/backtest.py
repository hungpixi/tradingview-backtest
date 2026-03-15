from __future__ import annotations

import argparse
import time
import logging

from .._utils import _format_time, build_risk
from ..models import BacktestMetrics, CandleRequest
from ..backtest.engine import TradingViewLikeBacktester
from ._helpers import _resolve, load_candles, generate_signals, resolve_pairlist
from strategy import list_strategies


def _run_single_backtest(
    symbol: str,
    exchange: str,
    timeframe: str,
    session: str,
    adjustment: str,
    strategy_name: str,
    initial_capital: float,
    data_dir: str,
    mode: str,
    sl: float,
    tp: float,
    start: str | None,
    end: str | None,
    *,
    pair_index: int = 1,
    pair_total: int = 1,
) -> BacktestMetrics | None:
    
    pair_label = f"{exchange}:{symbol}"
    tag = f"[{pair_index}/{pair_total}] {pair_label} "
    dot_width = max(40 - len(tag), 3)
    print(f"\n  {tag}{'.' * dot_width} ", end="", flush=True)

    candle_request = CandleRequest(
        symbol=symbol,
        exchange=exchange,
        timeframe=timeframe,
        start=start,
        end=end,
        session=session,
        adjustment=adjustment,
    )

    t_total = time.time()

    try:
        # 1. Load data
        candles = load_candles(candle_request, data_dir, step="1/3", quiet=True)
        if candles is None or len(candles) == 0:
            print("skipped (no candle data)")
            return None

        # 2. Generate signals
        signal_frame, _ = generate_signals(
            strategy_name, candles, mode, start, end, step="2/3", quiet=True
        )
        if signal_frame is None or len(signal_frame) == 0:
            print("skipped (no signals generated)")
            return None

        # 3. Run backtest
        risk = build_risk(mode, sl, tp)
        backtester = TradingViewLikeBacktester(
            candle_request=candle_request, 
            initial_equity=initial_capital
        )
        
        result = backtester.run(signal_frame, risk, mode)
        elapsed = _format_time(time.time() - t_total)

        print(f"done ({elapsed})")
        return result.metrics

    except Exception as e:
        print(f"failed ({e})")
        logging.exception(f"Error during backtest of {pair_label}")
        return None


def _print_summary_table(
    all_metrics: list[tuple[str, str, BacktestMetrics]],
) -> None:
    """Print a tabular summary of all pair results plus an aggregate row."""
    if not all_metrics:
        return

    # Dynamically size the Pair column
    pair_col_name = "Pair"
    max_pair = max(len(f"{ex}:{sym}") for sym, ex, _ in all_metrics)
    max_pair = max(max_pair, len(pair_col_name))

    # Define a reusable format string to ensure perfect column alignment
    row_fmt = (
        "  {idx:>3}  {pair:<{max_pair}}  {net:>+8.2f}%  {dd:>8.2f}%  "
        "{sharpe:>7.2f}  {calmar:>7.2f}  {wr:>9.2f}%  {pf:>9}  "
        "{exp:>+8.2f}%  {avg_w:>+9.2f}%  {avg_l:>+10.2f}%  {worst:>+11.2f}%  "
        "{mcl:>11}  {trades:>7}  {sl_tp_sig:>15}  ${eq:>13,.2f}"
    )

    hdr = (
        f"  {'':>3}  {pair_col_name:<{max_pair}}  {'Return %':>9}  {'Max DD %':>9}  "
        f"{'Sharpe':>7}  {'Calmar':>7}  {'Win Rate %':>10}  {'Prof Fact':>9}  "
        f"{'Expect %':>9}  {'Avg Win %':>10}  {'Avg Loss %':>11}  {'Worst Trade':>12}  "
        f"{'Loss Streak':>11}  {'Trades':>7}  {'Exits(SL/TP/Sg)':>15}  {'Final Equity':>14}"
    )
    sep = "  " + "-" * (len(hdr) - 2)

    print(f"\n{'=' * len(hdr)}")
    print("  Backtest Summary")
    print(f"{'=' * len(hdr)}")
    print(hdr)
    print(sep)

    # Accumulators for aggregate row
    total_net, total_trades, worst_dd, total_equity = 0.0, 0, 0.0, 0.0
    sharpe_sum, calmar_sum, exp_sum = 0.0, 0.0, 0.0
    avg_w_sum, avg_l_sum = 0.0, 0.0
    worst_trade_all = 0.0
    max_consec_all = 0
    
    # Back-calculate raw counts for aggregate percentages
    total_wins, total_sl, total_tp, total_sig = 0, 0.0, 0.0, 0.0

    for i, (symbol, exchange, m) in enumerate(all_metrics, 1):
        pair = f"{exchange}:{symbol}"
        sl_tp_sig = f"{m.sl_exit_pct:.0f}/{m.tp_exit_pct:.0f}/{m.signal_exit_pct:.0f}"
        
        print(row_fmt.format(
            idx=i, pair=pair, max_pair=max_pair, net=m.net_profit_pct, dd=m.max_drawdown_pct,
            sharpe=m.sharpe_ratio, calmar=m.calmar_ratio, wr=m.win_rate_pct, pf=f"{m.profit_factor:.2f}",
            exp=m.expectancy_pct, avg_w=m.avg_win_pct, avg_l=m.avg_loss_pct, worst=m.worst_trade_pct,
            mcl=m.max_consec_losses, trades=m.trade_count, sl_tp_sig=sl_tp_sig, eq=m.equity_final
        ))

        # Accumulate metrics
        total_net += m.net_profit_pct
        total_trades += m.trade_count
        total_equity += m.equity_final
        sharpe_sum += m.sharpe_ratio
        calmar_sum += m.calmar_ratio
        exp_sum += m.expectancy_pct
        avg_w_sum += m.avg_win_pct
        avg_l_sum += m.avg_loss_pct

        worst_dd = max(worst_dd, m.max_drawdown_pct)
        worst_trade_all = min(worst_trade_all, m.worst_trade_pct)
        max_consec_all = max(max_consec_all, m.max_consec_losses)

        if m.trade_count > 0:
            total_wins += round(m.win_rate_pct / 100 * m.trade_count)
            total_sl += m.sl_exit_pct / 100 * m.trade_count
            total_tp += m.tp_exit_pct / 100 * m.trade_count
            total_sig += m.signal_exit_pct / 100 * m.trade_count

    print(sep)

    # Print TOTAL row if there are multiple pairs
    n = len(all_metrics)
    if n > 1:
        avg_net = total_net / n
        avg_win = (total_wins / total_trades * 100) if total_trades > 0 else 0.0
        avg_sharpe = sharpe_sum / n
        avg_calmar = calmar_sum / n
        avg_expect = exp_sum / n
        avg_w = avg_w_sum / n
        avg_l = avg_l_sum / n

        agg_sl = (total_sl / total_trades * 100) if total_trades > 0 else 0.0
        agg_tp = (total_tp / total_trades * 100) if total_trades > 0 else 0.0
        agg_sig = (total_sig / total_trades * 100) if total_trades > 0 else 0.0
        sl_tp_sig_agg = f"{agg_sl:.0f}/{agg_tp:.0f}/{agg_sig:.0f}"

        print(row_fmt.format(
            idx="", pair="TOTAL / AVG", max_pair=max_pair, net=avg_net, dd=worst_dd,
            sharpe=avg_sharpe, calmar=avg_calmar, wr=avg_win, pf="",  # Empty PF, mathematically invalid to avg
            exp=avg_expect, avg_w=avg_w, avg_l=avg_l, worst=worst_trade_all,
            mcl=max_consec_all, trades=total_trades, sl_tp_sig=sl_tp_sig_agg, eq=total_equity
        ))

    print(f"{'=' * len(hdr)}\n")


def run_backtest(args: argparse.Namespace, config: dict) -> int:
    strategy_name = _resolve(args, config, "strategy")
    available_strategies = list_strategies()
    
    if not strategy_name or strategy_name not in available_strategies:
        print("Error: Invalid or no strategy specified.")
        print(f"Available strategies: {', '.join(available_strategies) or '(none)'}")
        return 1

    timeframe = _resolve(args, config, "timeframe")
    session = _resolve(args, config, "session")
    adjustment = args.adjustment
    initial_capital = config.get("initial_capital", 1000.0)
    data_dir = config.get("data_dir", "./data")

    pairs = resolve_pairlist(args, config)
    if not pairs:
        print("Error: No trading pairs resolved. Please check your config or arguments.")
        return 1

    print(f"\n{'#' * 60}")
    print(f"  Running backtest for {len(pairs)} pair(s)")
    print(f"  Strategy: {strategy_name} | SL={args.sl}% TP={args.tp}%")
    print(f"{'#' * 60}")

    all_metrics: list[tuple[str, str, BacktestMetrics]] = []
    rc = 0
    
    for idx, (symbol, pair_exchange) in enumerate(pairs, 1):
        m = _run_single_backtest(
            symbol=symbol,
            exchange=pair_exchange,
            timeframe=timeframe,
            session=session,
            adjustment=adjustment,
            strategy_name=strategy_name,
            initial_capital=initial_capital,
            data_dir=data_dir,
            mode=args.mode,
            sl=args.sl,
            tp=args.tp,
            start=args.start,
            end=args.end,
            pair_index=idx,
            pair_total=len(pairs),
        )
        if m is None:
            rc = 1
        else:
            all_metrics.append((symbol, pair_exchange, m))

    _print_summary_table(all_metrics)

    return rc