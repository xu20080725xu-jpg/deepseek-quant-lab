from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from quantlab.backtest import BacktestConfig, evaluate_splits, metrics, run_backtest
from quantlab.data import DataError, load_example, validate_bars
from quantlab.market_rules import FeeConfig, fees, price_limits, validate_symbol
from quantlab.strategies import StrategySpec, targets


def bars(prices):
    return pd.DataFrame({"date": pd.bdate_range("2024-01-02", periods=len(prices)),
        "open": prices, "high": np.array(prices) + .3, "low": np.array(prices) - .3,
        "close": prices, "volume": 1_000_000})


@pytest.mark.parametrize("day,expected", [("2023-08-27", 100), ("2023-08-28", 50)])
def test_stamp_tax_date_boundary(day, expected):
    assert fees(100000, "SELL", day, "600000")["stamp_tax"] == expected
    assert fees(100000, "BUY", day, "600000")["stamp_tax"] == 0


@pytest.mark.parametrize("day,expected", [("2022-04-28", 2), ("2022-04-29", 1)])
def test_transfer_date_boundary(day, expected):
    assert fees(100000, "BUY", day, "600000")["transfer_fee"] == expected


def test_minimum_commission_and_citic_shenzhen_policy():
    assert fees(1000, "BUY", "2024-01-02", "600000")["commission"] == 5
    assert fees(100000, "BUY", "2024-01-02", "000001")["transfer_fee"] == 0
    assert fees(100000, "BUY", "2024-01-02", "000001", FeeConfig(shenzhen_transfer_pass_through=True))["transfer_fee"] == 1
    assert price_limits(10.05) == (11.06, 9.05)


@pytest.mark.parametrize("symbol", ["688001", "300001", "510300", "920001", "600000;DROP"])
def test_unsupported_securities_fail_closed(symbol):
    with pytest.raises(ValueError):
        validate_symbol(symbol)


def test_no_same_close_execution_and_board_lots():
    data = load_example().frame
    spec = StrategySpec()
    signals = targets(data, spec)
    r = run_backtest(data, spec)
    assert len(r.trades) >= 3
    for t in r.trades:
        assert t["date"] > t["signal_date"]
        assert t["shares"] % 100 == 0
        idx = data.index[data.date == pd.Timestamp(t["date"])][0]
        assert bool(signals.iloc[idx-1]) == (t["side"] == "BUY")
        assert data.iloc[idx].low <= t["price"] <= data.iloc[idx].high
    assert r.curve.cash.min() >= 0
    for buy, sell in zip(r.trades[::2], r.trades[1::2]):
        assert sell["date"] > buy["date"]
        expected = sell["price"] * sell["shares"] - sell["fees"]["total"] - buy["price"] * buy["shares"] - buy["fees"]["total"]
        assert sell["realized_pnl"] == pytest.approx(expected, abs=.011)


def test_future_changes_do_not_affect_past_signals_or_fills():
    data = load_example().frame
    changed = data.copy()
    changed.loc[250:, ["open", "high", "low", "close"]] *= 1.01
    for spec in [StrategySpec(), StrategySpec(kind="volume_breakout")]:
        pd.testing.assert_series_equal(targets(data, spec)[:250], targets(changed, spec)[:250])
        old = run_backtest(data, spec).curve.iloc[:250]
        new = run_backtest(changed, spec).curve.iloc[:250]
        pd.testing.assert_frame_equal(old, new)


def test_limit_up_and_suspension_never_invent_fill(monkeypatch):
    data = bars([10, 11, 10, 10, 10])
    data.loc[2, "volume"] = 0
    monkeypatch.setattr("quantlab.backtest.targets", lambda frame, spec: pd.Series([1.] * len(frame)))
    r = run_backtest(data, fee_config=FeeConfig(slippage_bps=0))
    assert [x["reason"] for x in r.rejections][:2] == ["开盘涨停，保守拒绝买入", "停牌或无成交量"]
    assert r.rejections[2]["reason"] == "上一日流动性不足"
    assert r.trades[0]["date"] == str(data.date.iloc[4].date())


def test_limit_down_blocks_exit(monkeypatch):
    data = bars([10, 10, 9, 9])
    monkeypatch.setattr("quantlab.backtest.targets", lambda frame, spec: pd.Series([1., 0., 0., 0.]))
    r = run_backtest(data, fee_config=FeeConfig(slippage_bps=0))
    assert r.trades[0]["side"] == "BUY"
    assert r.rejections[0]["reason"] == "开盘跌停，保守拒绝卖出"
    assert r.trades[-1]["date"] == str(data.date.iloc[3].date())


def test_small_cash_does_not_buy_unaffordable_lot():
    r = run_backtest(bars([100, 100, 100, 100]), config=BacktestConfig(initial_cash=1000), buy_hold=True)
    assert not r.trades and r.metrics["total_return"] == 0
    assert r.metrics["win_rate"] is None


def test_commission_included_in_first_day_drawdown():
    r = run_backtest(bars([10, 10, 10, 10]), fee_config=FeeConfig(slippage_bps=0), buy_hold=True)
    assert r.metrics["total_return"] < 0
    assert r.metrics["max_drawdown"] > 0


def test_corporate_action_invalidates_even_when_no_order():
    data = bars([10, 10, 10, 10])
    data["corporate_action"] = [False, False, True, False]
    with pytest.raises(ValueError, match="公司行动"):
        run_backtest(data)


def test_validation_rejects_duplicate_nan_and_invalid_ohlc():
    original = bars([10, 10, 10, 10])
    for col, value in [("high", 1), ("close", float("nan")), ("volume", -1)]:
        bad = original.copy()
        bad.loc[1, col] = value
        with pytest.raises((DataError, ValueError)):
            validate_bars(bad)
    with pytest.raises(DataError):
        validate_bars(pd.concat([original, original.iloc[:1]]))


def test_split_boundaries_are_disjoint():
    data = load_example().frame
    result = evaluate_splits(data, StrategySpec(), BacktestConfig(), FeeConfig())
    assert len(result) == 3
    assert result[0]["结束"] < result[1]["开始"] <= result[1]["结束"] < result[2]["开始"]


def test_volume_breakout_excludes_current_high_and_volume():
    data = bars([10, 10, 10, 10, 10.5, 10.6])
    data.loc[4, "volume"] = 2_000_000
    spec = StrategySpec(kind="volume_breakout", lookback=3, volume_multiple=1.5)
    assert targets(data, spec).iloc[4] == 1
