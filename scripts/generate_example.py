"""Reproducible artificial market, explicitly never labelled real stock prices."""
from pathlib import Path
import json
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def main():
    rng = np.random.default_rng(42)
    n = 360
    dates = pd.bdate_range("2024-01-02", periods=n)
    # Business days here intentionally include Chinese holidays: this is not an exchange calendar.
    trend = .001 + .012 * np.sin(np.arange(n) / 18)
    close = np.round(10 * np.exp(np.cumsum(trend + rng.normal(0, .008, n))), 2)
    op = np.round(np.r_[close[0], close[:-1]] * (1 + rng.normal(0, .002, n)), 2)
    high = np.round(np.maximum(op, close) * 1.012, 2)
    low = np.round(np.minimum(op, close) * .988, 2)
    volume = rng.integers(1_000_000, 5_000_000, n)
    df = pd.DataFrame({"date": dates, "open": op, "high": high, "low": low,
                       "close": close, "volume": volume, "amount": close * volume})
    dest = ROOT / "data" / "examples"
    dest.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest / "synthetic_000001.csv", index=False)
    meta = {"symbol": "000001", "source": "NumPy seed=42 / synthetic generator v1",
            "kind": "synthetic", "label": "人工合成测试数据（非真实行情）", "sample": True,
            "adjust": "none", "volume_unit": "shares", "fetched_at": "not_applicable",
            "last_bar": str(dates[-1].date()), "calendar": "工作日序列，包含中国节假日，仅用于测试"}
    (dest / "synthetic_000001.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"Generated {n} synthetic test bars. Not actual prices.")


if __name__ == "__main__":
    main()
