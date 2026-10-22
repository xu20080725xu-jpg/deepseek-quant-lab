"""Phase-one fail-closed guard. Full paper account controls arrive in phase two."""
from dataclasses import dataclass
from datetime import datetime
import math
from quantlab.config import SHANGHAI


@dataclass(frozen=True)
class RiskLimits:
    max_order_ratio: float = 0.2
    max_symbol_ratio: float = 0.3
    max_daily_loss: float = 0.02
    max_drawdown: float = 0.1
    min_daily_amount: float = 10_000_000
    max_errors: int = 3
    max_quote_age_seconds: int = 30


class RiskManager:
    def __init__(self, store):
        self.store = store

    def check_market_data(self, meta, price, now=None):
        now = now or datetime.now(SHANGHAI)
        if self.store.setting("emergency_stop", True):
            return False, "紧急停止开关开启"
        if meta.get("kind") != "verified_realtime" or meta.get("sample"):
            return False, "历史/未验证/示例行情禁止生成模拟交易订单"
        try:
            timestamp = datetime.fromisoformat(meta["quote_time"])
            age = (now - timestamp).total_seconds()
        except (KeyError, TypeError, ValueError):
            return False, "行情时间戳无效"
        if not 0 <= age <= 30 or not math.isfinite(price) or price <= 0:
            return False, "行情过期或价格异常"
        return False, "第一阶段模拟交易执行尚未启用"
