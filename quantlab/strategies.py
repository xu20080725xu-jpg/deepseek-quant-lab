"""Allowlisted deterministic rules. No generated Python, eval or dynamic imports."""
from typing import Literal
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrategySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["ma_cross", "volume_breakout"] = "ma_cross"
    short: int = Field(default=5, ge=2, le=120)
    long: int = Field(default=20, ge=3, le=250)
    lookback: int = Field(default=20, ge=3, le=120)
    volume_multiple: float = Field(default=1.5, ge=1.0, le=10.0)
    exit_ma: int = Field(default=10, ge=2, le=120)

    @model_validator(mode="after")
    def check_periods(self):
        if self.short >= self.long:
            raise ValueError("短均线必须小于长均线")
        return self


def targets(frame: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    close = frame.close
    if spec.kind == "ma_cross":
        fast = close.rolling(spec.short, min_periods=spec.short).mean()
        slow = close.rolling(spec.long, min_periods=spec.long).mean()
        diff = fast - slow
        up = (diff > 0) & (diff.shift(1) <= 0)
        down = (diff < 0) & (diff.shift(1) >= 0)
    else:
        # Exclude today from both the breakout price and volume baseline.
        prior_high = frame.high.shift(1).rolling(spec.lookback).max()
        prior_volume = frame.volume.shift(1).rolling(spec.lookback).mean()
        up = (close > prior_high) & (frame.volume > prior_volume * spec.volume_multiple)
        down = close < close.rolling(spec.exit_ma).mean()
    signal = pd.Series(np.nan, index=frame.index)
    signal.loc[up] = 1.0
    signal.loc[down & ~up] = 0.0
    return signal.ffill().fillna(0.0)


def indicators(frame):
    df = frame.copy()
    for n in (5, 10, 20, 60):
        df[f"MA{n}"] = df.close.rolling(n).mean()
    df["DIF"] = df.close.ewm(span=12, adjust=False).mean() - df.close.ewm(span=26, adjust=False).mean()
    df["DEA"] = df.DIF.ewm(span=9, adjust=False).mean()
    df["MACD"] = 2 * (df.DIF - df.DEA)
    delta = df.close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    df["RSI14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    df.loc[(loss == 0) & (gain > 0), "RSI14"] = 100
    df.loc[(loss == 0) & (gain == 0), "RSI14"] = 50
    return df
