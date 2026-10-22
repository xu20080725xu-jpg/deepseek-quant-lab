"""Historical-only providers with provenance, bounded worker lifetime and no fake fallback."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import numpy as np
import pandas as pd
from quantlab.config import DATA, ROOT, SHANGHAI
from quantlab.market_rules import validate_symbol


class DataError(RuntimeError):
    pass


def cache_directory():
    from quantlab.cloud_access import session_cache
    return session_cache.get() or DATA / "cache"


@dataclass
class MarketData:
    frame: pd.DataFrame
    meta: dict

    @property
    def fingerprint(self):
        return hashlib.sha256(self.frame.to_csv(index=False).encode()).hexdigest()


def validate_bars(frame):
    df = frame.copy()
    required = ["date", "open", "high", "low", "close", "volume"]
    if not set(required).issubset(df.columns) or df.empty:
        raise DataError("行情为空或缺少 OHLCV 字段")
    df["date"] = pd.to_datetime(df.date, errors="raise").dt.normalize()
    if df.date.isna().any():
        raise DataError("行情存在无效交易日")
    if df.date.duplicated().any():
        raise DataError("行情存在重复交易日")
    for col in required[1:] + (["amount"] if "amount" in df else []):
        df[col] = pd.to_numeric(df[col], errors="raise")
        if not np.isfinite(df[col]).all():
            raise DataError("行情存在空值或非有限数")
    if (df[["open", "high", "low", "close"]] <= 0).any().any() or (df.volume < 0).any():
        raise DataError("行情价格或成交量异常")
    if ((df.high < df[["open", "close", "low"]].max(axis=1)) |
            (df.low > df[["open", "close", "high"]].min(axis=1))).any():
        raise DataError("OHLC 高低价格关系异常")
    return df.sort_values("date").reset_index(drop=True)


class MarketDataProvider(ABC):
    @abstractmethod
    def history(self, symbol, start, end) -> MarketData:
        ...

    def quote(self, symbol):
        raise DataError("第一版无经过授权验证的实时源；禁止用日线生成实时模拟交易订单")


class AKShareProvider(MarketDataProvider):
    def __init__(self, source="tencent"):
        if source not in {"tencent", "eastmoney"}:
            raise ValueError("Unknown provider")
        self.source = source

    def history(self, symbol, start, end):
        validate_symbol(symbol)
        if pd.Timestamp(start) > pd.Timestamp(end):
            raise DataError("开始日期必须早于结束日期")
        # Each fetch runs in a killable worker; some AKShare functions omit timeouts.
        with tempfile.TemporaryDirectory(prefix="quantlab-") as temp:
            output = Path(temp) / "bars.csv"
            command = [sys.executable, "-m", "quantlab.data_worker", self.source, symbol,
                       str(start)[:10], str(end)[:10], str(output)]
            error = ""
            for attempt in range(2):
                try:
                    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=35)
                    if proc.returncode != 0:
                        error = "源站拒绝请求、数据结构变化或网络不可达"
                        continue
                    df = validate_bars(pd.read_csv(output))
                    break
                except subprocess.TimeoutExpired:
                    error = "行情请求超过 35 秒，已终止"
                except (ValueError, OSError, DataError):
                    error = "源站返回空数据或格式不合法"
            else:
                raise DataError(f"{self.source} 获取失败（最多2次）：{error}。可切换来源或使用明确标注的离线示例。")
        now = datetime.now(SHANGHAI)
        # Never include an unfinished daily candle, even if the remote source returns one.
        cutoff = pd.Timestamp(now.date())
        df = df[(df.date >= pd.Timestamp(start)) & (df.date <= pd.Timestamp(end)) & (df.date <= cutoff)]
        if now.hour < 16:
            df = df[df.date < cutoff]
        if df.empty:
            raise DataError("所选区间没有已完成日 K 线")
        meta = {"symbol": symbol, "source": f"AKShare/{self.source}", "kind": "historical",
                "label": "历史日线 · 非实时 · 不复权", "adjust": "none", "volume_unit": "shares",
                "fetched_at": now.isoformat(), "last_bar": str(df.date.max().date()),
                "sample": False, "authorization": "公开接口，仅供个人学术研究；无实时授权及可用性保证"}
        result = MarketData(df.reset_index(drop=True), meta)
        cache = cache_directory()
        cache.mkdir(exist_ok=True, parents=True)
        key = f"{symbol}_{self.source}_{str(start)[:10]}_{str(end)[:10]}"
        result.frame.to_csv(cache / f"{key}.csv", index=False)
        (cache / f"{key}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        # Content-addressed snapshot keeps saved experiments reproducible after later refreshes.
        result.frame.to_csv(cache / f"{result.fingerprint}.csv", index=False)
        (cache / f"{result.fingerprint}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
        return result


def load_example():
    folder = DATA / "examples"
    return MarketData(validate_bars(pd.read_csv(folder / "synthetic_000001.csv")),
                      json.loads((folder / "synthetic_000001.json").read_text()))


def load_cached(path):
    path = Path(path).resolve()
    if path.parent != cache_directory().resolve() or path.suffix != ".csv":
        raise DataError("只允许读取本项目历史缓存")
    meta = json.loads(path.with_suffix(".json").read_text())
    meta = {**meta, "label": "本地历史缓存 · 非实时 · 不复权"}
    return MarketData(validate_bars(pd.read_csv(path)), meta)


def market_status(now=None):
    now = now or datetime.now(SHANGHAI)
    now = now.astimezone(SHANGHAI)
    minute = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        return "周末休市（未接入权威交易日历）"
    if 570 <= minute < 690 or 780 <= minute < 900:
        return "处于常规交易时段；节假日与临时休市未核验，实时信号关闭"
    return "常规交易时段外；第一版只提供历史日线"
