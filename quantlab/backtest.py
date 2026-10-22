"""Single-stock, next-open research simulator. Unfilled orders are recorded."""
from dataclasses import asdict, dataclass
import math
import numpy as np
import pandas as pd
from quantlab.data import validate_bars
from quantlab.market_rules import FeeConfig, cents, fees, price_limits, validate_symbol
from quantlab.strategies import StrategySpec, targets


@dataclass
class BacktestConfig:
    symbol: str = "000001"
    initial_cash: float = 10000.0
    allocation: float = 0.95
    participation: float = 0.01

    def __post_init__(self):
        validate_symbol(self.symbol)
        if not math.isfinite(self.initial_cash) or self.initial_cash <= 0:
            raise ValueError("初始资金必须为正数")
        if not 0 < self.allocation <= 1 or not 0 < self.participation <= 0.05:
            raise ValueError("无效仓位或流动性参数")


@dataclass
class BacktestResult:
    metrics: dict
    curve: pd.DataFrame
    trades: list
    rejections: list


def metrics(curve, trades, initial):
    equity = np.r_[initial, curve.equity.to_numpy()]
    returns = pd.Series(equity).pct_change().dropna()
    total = equity[-1] / initial - 1
    days = max(1, (curve.date.iloc[-1] - curve.date.iloc[0]).days)
    annual = (1 + total) ** (365.25 / days) - 1
    dd = 1 - equity / np.maximum.accumulate(equity)
    pnls = [t["realized_pnl"] for t in trades if t["side"] == "SELL"]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    return {"total_return": float(total), "annual_return": float(annual),
            "max_drawdown": float(dd.max()),
            "win_rate": len(wins) / len(pnls) if pnls else None,
            "trade_count": len(trades), "closed_trades": len(pnls),
            "payoff_ratio": float(np.mean(wins) / abs(np.mean(losses))) if wins and losses else None,
            "sharpe": float(returns.mean() / returns.std(ddof=1) * np.sqrt(252))
                      if len(returns) > 1 and returns.std(ddof=1) > 1e-12 else None,
            "total_fees": cents(sum(t["fees"]["total"] for t in trades)),
            "slippage_cost": cents(sum(t["slippage_cost"] for t in trades)),
            "ending_equity": float(equity[-1]), "open_shares": int(curve.shares.iloc[-1])}


def run_backtest(frame, spec=StrategySpec(), config=None, fee_config=FeeConfig(),
                 start=None, end=None, buy_hold=False):
    cfg = config or BacktestConfig()
    df = validate_bars(frame)
    if len(df) < 3:
        raise ValueError("至少需要3根日线")
    if df.date.min() < pd.Timestamp("2015-08-03"):
        raise ValueError("费率历史支持范围从2015-08-03开始")
    signal = pd.Series(1.0, index=df.index) if buy_hold else targets(df, spec)
    cash, shares, entry_cost = cfg.initial_cash, 0, 0.0
    entry_day = None
    trades, rejected, curve = [], [], []
    start = pd.Timestamp(start) if start else df.date.iloc[0]
    end = pd.Timestamp(end) if end else df.date.iloc[-1]
    for i, row in df.iterrows():
        if not start <= row.date <= end:
            continue
        desired = bool(signal.iloc[i-1]) if i > 0 else False
        # A segment starts in cash, but can use fully known warmup observations.
        side = "BUY" if desired and shares == 0 else "SELL" if not desired and shares > 0 else None
        if side and i > 0:
            prior = df.iloc[i-1]
            reason = None
            upper, lower = price_limits(prior.close)
            upper = float(row.get("limit_up", upper))
            lower = float(row.get("limit_down", lower))
            if row.volume <= 0 or bool(row.get("suspended", False)):
                reason = "停牌或无成交量"
            elif bool(row.get("corporate_action", False)):
                # No invented dividend/split return. Abort the entire run, even if flat.
                raise ValueError("区间存在公司行动，第一版需选择无除权除息区间")
            elif row.open > upper + 0.011 or row.open < lower - 0.011:
                reason = "超出普通主板价格范围，疑似公司行动或特殊证券状态"
            elif side == "BUY" and row.open >= upper - 0.001:
                reason = "开盘涨停，保守拒绝买入"
            elif side == "SELL" and row.open <= lower + 0.001:
                reason = "开盘跌停，保守拒绝卖出"
            elif side == "SELL" and entry_day >= row.date:
                reason = "T+1 可卖数量不足"
            elif prior.volume <= 0:
                reason = "上一日流动性不足"
            price = cents(row.open * (1 + fee_config.slippage_bps / 10000 * (1 if side == "BUY" else -1)))
            if not reason and not row.low - 0.001 <= price <= row.high + 0.001:
                reason = "滑点成交价超出日内范围"
            if not reason and side == "BUY":
                budget = cash * cfg.allocation
                qty = min(int(budget / price / 100) * 100,
                          int(prior.volume * cfg.participation / 100) * 100)
                while qty > 0:
                    cost = fees(qty * price, side, row.date, cfg.symbol, fee_config)
                    if qty * price + cost["total"] <= budget:
                        break
                    qty -= 100
                if qty <= 0:
                    reason = "资金或上一交易日流动性不足一手"
            elif not reason:
                qty = shares
                if qty > prior.volume * cfg.participation:
                    reason = "卖出量超过上一日成交量参与上限，整笔拒绝"
            if reason:
                rejected.append({"date": str(row.date.date()), "side": side, "reason": reason})
            else:
                cost = fees(qty * price, side, row.date, cfg.symbol, fee_config)
                realized = None
                if side == "BUY":
                    entry_cost = cents(qty * price + cost["total"])
                    cash = cents(cash - entry_cost)
                    shares, entry_day = qty, row.date
                else:
                    proceeds = cents(qty * price - cost["total"])
                    cash = cents(cash + proceeds)
                    realized = cents(proceeds - entry_cost)
                    shares = 0
                trades.append({"date": str(row.date.date()), "signal_date": str(prior.date.date()),
                    "side": side, "price": price, "shares": qty, "fees": cost,
                    "slippage_cost": cents(abs(price - row.open) * qty),
                    "realized_pnl": realized, "cash_after": cash})
        # Known corporate actions invalidate even a period without an order.
        if bool(row.get("corporate_action", False)):
            raise ValueError("公司行动未实现，拒绝输出该区间收益")
        curve.append({"date": row.date, "equity": cents(cash + shares * row.close),
                      "cash": cash, "shares": shares, "close": float(row.close)})
    if len(curve) < 3:
        raise ValueError("评估区间至少需要3个交易日")
    out = pd.DataFrame(curve)
    return BacktestResult(metrics(out, trades, cfg.initial_cash), out, trades, rejected)


def evaluate_splits(frame, spec, config, fee_config):
    """Chronological 60/20/20; frozen parameters, independent starting cash, shared past warmup."""
    if len(frame) < 100:
        raise ValueError("分段验证至少需要100根日线")
    n = len(frame)
    rows = []
    for name, a, b in [("训练 60%", 0, int(n*.6)), ("验证 20%", int(n*.6), int(n*.8)),
                        ("样本外 20%", int(n*.8), n)]:
        r = run_backtest(frame.iloc[:b], spec, config, fee_config, start=frame.date.iloc[a])
        rows.append({"区间": name, "开始": str(frame.date.iloc[a].date()),
                     "结束": str(frame.date.iloc[b-1].date()), **r.metrics})
    return rows
