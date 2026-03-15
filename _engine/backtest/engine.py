from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from ..models import BacktestMetrics, BacktestResult, CandleRequest, Mode, RiskParameters, Trade

# Approximate number of bars per year for Sharpe annualization.
_BARS_PER_YEAR: dict[str, float] = {
    "1":    365 * 24 * 60,   # 1m
    "3":    365 * 24 * 20,   # 3m
    "5":    365 * 24 * 12,   # 5m
    "15":   365 * 24 * 4,    # 15m
    "30":   365 * 24 * 2,    # 30m
    "45":   365 * 16,        # 45m
    "60":   365 * 24,        # 1h
    "120":  365 * 12,        # 2h
    "180":  365 * 8,         # 3h
    "240":  365 * 6,         # 4h
    "1D":   365,
    "1W":   52,
    "1M":   12,
}


def _annualization_factor(timeframe: str) -> float:
    """Return sqrt(bars-per-year) for Sharpe annualization."""
    # Timeframe strings: "1h" → "60", "4h" → "240", "1D", "1W", "1M",
    # or raw minute strings like "60", "240".
    tf = timeframe.upper().replace(" ", "")
    # Convert common aliases: "1H" → "60", "4H" → "240", etc.
    if tf.endswith("H"):
        hours = tf[:-1]
        try:
            tf = str(int(hours) * 60)
        except ValueError:
            pass
    bars = _BARS_PER_YEAR.get(tf, 365 * 24)  # default to 1h
    return math.sqrt(bars)


@dataclass
class _Position:
    direction: str
    entry_time: int
    entry_price: float
    stop_price: float
    target_price: float
    equity_before: float


@dataclass
class _PendingOrder:
    action: str
    signal_close: float


class TradingViewLikeBacktester:
    """Backtester that mirrors TradingView's default broker-emulator assumptions."""

    def __init__(
        self,
        candle_request: CandleRequest,
        initial_equity: float = 100_000.0,
    ) -> None:
        self.candle_request = candle_request
        self.initial_equity = float(initial_equity)

    def run(
        self,
        signal_frame: pd.DataFrame,
        risk: RiskParameters,
        mode: Mode,
    ) -> BacktestResult:
        dataframe = signal_frame.reset_index(drop=True)
        # Round OHLC to tick precision to match TradingView's syminfo.mintick
        decimals = max(0, len(str(self.candle_request.mintick).rstrip('0').split('.')[-1]))
        for col in ("open", "high", "low", "close"):
            if col in dataframe.columns:
                dataframe[col] = dataframe[col].round(decimals)
        pending: _PendingOrder | None = None
        position: _Position | None = None
        equity = self.initial_equity
        equity_curve: list[float] = [equity]
        trades: list[Trade] = []

        for index, bar in dataframe.iterrows():
            position, equity, filled_trades = self._apply_pending_order(position, pending, bar, risk, equity)
            pending = None
            trades.extend(filled_trades)

            if position is not None:
                exit_price, exit_reason = self._check_bar_exit(position, bar)
                if exit_price is not None and exit_reason is not None:
                    trade, equity = self._close_position(position, int(bar["time"]), exit_price, exit_reason, equity)
                    trades.append(trade)
                    position = None

            equity_curve.append(self._mark_to_market(equity, position, float(bar["close"])))

            pending = self._build_next_order(bar, mode)
            if pending is not None and index == len(dataframe) - 1:
                pending = None

        metrics = self._build_metrics(trades, equity_curve, risk, mode, dataframe)
        return BacktestResult(metrics=metrics, trades=trades, equity_curve=equity_curve)

    def _apply_pending_order(
        self,
        position: _Position | None,
        pending: _PendingOrder | None,
        bar: pd.Series,
        risk: RiskParameters,
        equity: float,
    ) -> tuple[_Position | None, float, list[Trade]]:
        if pending is None:
            return position, equity, []

        open_price = float(bar["open"])
        bar_time = int(bar["time"])
        trades: list[Trade] = []

        if pending.action == "open_long":
            if position is not None and position.direction == "short":
                trade, equity = self._close_position(position, bar_time, open_price, "reverse_to_long", equity)
                trades.append(trade)
                position = None
            if position is None:
                sl_offset = pending.signal_close * (risk.long_stoploss_pct / 100.0)
                tp_offset = pending.signal_close * (risk.long_takeprofit_pct / 100.0)
                position = _Position(
                    direction="long",
                    entry_time=bar_time,
                    entry_price=open_price,
                    stop_price=open_price - sl_offset,
                    target_price=open_price + tp_offset,
                    equity_before=equity,
                )
        elif pending.action == "open_short":
            if position is not None and position.direction == "long":
                trade, equity = self._close_position(position, bar_time, open_price, "reverse_to_short", equity)
                trades.append(trade)
                position = None
            if position is None:
                sl_offset = pending.signal_close * (risk.short_stoploss_pct / 100.0)
                tp_offset = pending.signal_close * (risk.short_takeprofit_pct / 100.0)
                position = _Position(
                    direction="short",
                    entry_time=bar_time,
                    entry_price=open_price,
                    stop_price=open_price + sl_offset,
                    target_price=open_price - tp_offset,
                    equity_before=equity,
                )

        return position, equity, trades

    def _check_bar_exit(self, position: _Position, bar: pd.Series) -> tuple[float | None, str | None]:
        open_price = float(bar["open"])
        high_price = float(bar["high"])
        low_price = float(bar["low"])
        close_price = float(bar["close"])

        if abs(open_price - high_price) <= abs(open_price - low_price):
            path = [open_price, high_price, low_price, close_price]
        else:
            path = [open_price, low_price, high_price, close_price]

        reason_by_price = {
            position.stop_price: "stop_loss",
            position.target_price: "take_profit",
        }

        for start, end in zip(path, path[1:]):
            lower, upper = sorted((start, end))
            hits = [price for price in reason_by_price if lower <= price <= upper]
            if not hits:
                continue

            first_hit = min(hits) if end >= start else max(hits)
            return first_hit, reason_by_price[first_hit]

        return None, None

    def _build_next_order(self, bar: pd.Series, mode: Mode) -> _PendingOrder | None:
        if not bool(bar["in_date_range"]):
            return None

        buy_signal = bool(bar["buy_signal"])
        sell_signal = bool(bar["sell_signal"])
        long_allowed = bool(bar["enable_long"]) and mode in {"long", "both"}
        short_allowed = bool(bar["enable_short"]) and mode in {"short", "both"}

        if buy_signal and long_allowed and not sell_signal:
            return _PendingOrder("open_long", signal_close=float(bar["close"]))
        if sell_signal and short_allowed and not buy_signal:
            return _PendingOrder("open_short", signal_close=float(bar["close"]))
        return None

    def _close_position(
        self,
        position: _Position,
        exit_time: int,
        exit_price: float,
        exit_reason: str,
        equity: float,
    ) -> tuple[Trade, float]:
        if position.direction == "long":
            return_pct = ((exit_price - position.entry_price) / position.entry_price) * 100.0
        else:
            return_pct = ((position.entry_price - exit_price) / position.entry_price) * 100.0

        equity_after = equity * (1.0 + return_pct / 100.0)
        trade = Trade(
            entry_time=position.entry_time,
            exit_time=exit_time,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=exit_price,
            exit_reason=exit_reason,
            return_pct=return_pct,
            equity_before=position.equity_before,
            equity_after=equity_after,
        )
        return trade, equity_after

    def _mark_to_market(self, equity: float, position: _Position | None, close_price: float) -> float:
        if position is None:
            return equity
        if position.direction == "long":
            return equity * (close_price / position.entry_price)
        return equity * (position.entry_price / close_price)

    def _build_metrics(
        self,
        trades: list[Trade],
        equity_curve: list[float],
        risk: RiskParameters,
        mode: Mode,
        dataframe: pd.DataFrame,
    ) -> BacktestMetrics:
        positive_pnl = 0.0
        negative_pnl = 0.0
        wins = 0
        equity_reference = self.initial_equity

        win_returns: list[float] = []
        loss_returns: list[float] = []

        for trade in trades:
            pnl = trade.equity_after - equity_reference
            equity_reference = trade.equity_after
            if pnl >= 0:
                positive_pnl += pnl
                wins += 1
                win_returns.append(trade.return_pct)
            else:
                negative_pnl += pnl
                loss_returns.append(trade.return_pct)

        peak = equity_curve[0]
        max_drawdown = 0.0
        for value in equity_curve:
            if value > peak:
                peak = value
            if peak > 0:
                drawdown = ((peak - value) / peak) * 100.0
                if drawdown > max_drawdown:
                    max_drawdown = drawdown

        win_rate = (wins / len(trades) * 100.0) if trades else 0.0
        if negative_pnl == 0.0:
            profit_factor = float("inf") if positive_pnl > 0.0 else 0.0
        else:
            profit_factor = positive_pnl / abs(negative_pnl) if positive_pnl > 0.0 else 0.0

        sl_pct = risk.long_stoploss_pct if mode != "short" else risk.short_stoploss_pct
        tp_pct = risk.long_takeprofit_pct if mode != "short" else risk.short_takeprofit_pct
        final_equity = trades[-1].equity_after if trades else self.initial_equity
        net_profit_pct = ((final_equity - self.initial_equity) / self.initial_equity) * 100.0

        # --- New metrics ---

        # Per-trade quality
        avg_win = (sum(win_returns) / len(win_returns)) if win_returns else 0.0
        avg_loss = (sum(loss_returns) / len(loss_returns)) if loss_returns else 0.0
        expectancy = (sum(t.return_pct for t in trades) / len(trades)) if trades else 0.0
        worst_trade = min((t.return_pct for t in trades), default=0.0)

        # Max consecutive losses
        max_consec = 0
        cur_consec = 0
        for t in trades:
            if t.return_pct < 0:
                cur_consec += 1
                if cur_consec > max_consec:
                    max_consec = cur_consec
            else:
                cur_consec = 0

        # Exit reason breakdown
        n = len(trades) or 1
        sl_exits = sum(1 for t in trades if t.exit_reason == "stop_loss")
        tp_exits = sum(1 for t in trades if t.exit_reason == "take_profit")
        sig_exits = len(trades) - sl_exits - tp_exits
        sl_exit_pct = sl_exits / n * 100.0
        tp_exit_pct = tp_exits / n * 100.0
        signal_exit_pct = sig_exits / n * 100.0

        # Sharpe ratio (annualised, from bar-level equity returns)
        sharpe = 0.0
        if len(equity_curve) > 1:
            returns = []
            for i in range(1, len(equity_curve)):
                prev = equity_curve[i - 1]
                if prev != 0:
                    returns.append((equity_curve[i] - prev) / prev)
            if returns:
                mean_r = sum(returns) / len(returns)
                var_r = sum((r - mean_r) ** 2 for r in returns) / len(returns)
                std_r = math.sqrt(var_r)
                if std_r > 0:
                    sharpe = (mean_r / std_r) * _annualization_factor(self.candle_request.timeframe)

        # Calmar ratio
        calmar = 0.0
        if max_drawdown > 0:
            calmar = net_profit_pct / max_drawdown

        return BacktestMetrics(
            symbol=f"{self.candle_request.exchange}:{self.candle_request.symbol}",
            timeframe=self.candle_request.timeframe,
            start=self.candle_request.start,
            end=self.candle_request.end or pd.Timestamp(int(dataframe["time"].max()), unit="s", tz="UTC").strftime("%Y-%m-%d"),
            mode=mode,
            sl_pct=round(sl_pct, 2),
            tp_pct=round(tp_pct, 2),
            net_profit_pct=round(net_profit_pct, 2),
            max_drawdown_pct=round(max_drawdown, 2),
            win_rate_pct=round(win_rate, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else profit_factor,
            trade_count=len(trades),
            equity_final=round(final_equity, 2),
            sharpe_ratio=round(sharpe, 2),
            calmar_ratio=round(calmar, 2),
            expectancy_pct=round(expectancy, 2),
            avg_win_pct=round(avg_win, 2),
            avg_loss_pct=round(avg_loss, 2),
            worst_trade_pct=round(worst_trade, 2),
            max_consec_losses=max_consec,
            sl_exit_pct=round(sl_exit_pct, 2),
            tp_exit_pct=round(tp_exit_pct, 2),
            signal_exit_pct=round(signal_exit_pct, 2),
        )
