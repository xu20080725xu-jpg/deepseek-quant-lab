"""Versioned fees for supported ordinary Shanghai/Shenzhen main-board A shares."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import math
import re


def cents(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def validate_symbol(symbol):
    if not re.fullmatch(r"(?:600|601|603|605|000|001|002|003)\d{3}", symbol):
        raise ValueError("第一版仅支持沪深普通主板 A 股；暂不支持 ST、新股、科创板、创业板、ETF、北交所")
    return "sh" if symbol.startswith("6") else "sz"


@dataclass(frozen=True)
class FeeConfig:
    commission: float = 0.00015
    minimum: float = 5.0
    slippage_bps: float = 5.0
    # CITIC published schedule: Shenzhen transfer fee borne by broker.
    shenzhen_transfer_pass_through: bool = False

    def __post_init__(self):
        if not all(math.isfinite(x) and x >= 0 for x in (self.commission, self.minimum, self.slippage_bps)):
            raise ValueError("费用必须为非负有限数")
        if self.commission > 0.003 or self.slippage_bps > 100:
            raise ValueError("费用或滑点超出研究支持范围")


def fees(notional, side, trading_date, symbol, cfg=FeeConfig()):
    market = validate_symbol(symbol)
    day = date.fromisoformat(str(trading_date)[:10])
    if day < date(2015, 8, 3):
        raise ValueError("历史费率仅实现 2015-08-03 以后")
    if side not in {"BUY", "SELL"} or not math.isfinite(notional) or notional <= 0:
        raise ValueError("无效成交")
    commission = cents(max(cfg.minimum, notional * cfg.commission))
    stamp = cents(notional * (0.0005 if day >= date(2023, 8, 28) else 0.001)) if side == "SELL" else 0.0
    transfer_rate = 0.00001 if day >= date(2022, 4, 29) else 0.00002
    transfer = cents(notional * transfer_rate) if market == "sh" or cfg.shenzhen_transfer_pass_through else 0.0
    return {"commission": commission, "stamp_tax": stamp, "transfer_fee": transfer,
            "total": cents(commission + stamp + transfer)}


def price_limits(previous_close):
    # Only ordinary mature main-board stocks; supplied official limits override these.
    return cents(previous_close * 1.1), cents(previous_close * 0.9)
