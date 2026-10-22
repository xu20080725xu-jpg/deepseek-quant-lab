from abc import ABC, abstractmethod


class BrokerAdapter(ABC):
    @abstractmethod
    def account(self):
        ...

    @abstractmethod
    def submit_order(self, order):
        ...

    @abstractmethod
    def cancel_order(self, order_id):
        ...


class PaperBroker(BrokerAdapter):
    """Phase-two boundary only; no pretend fills or account mutation in phase one."""
    def account(self):
        return {"status": "not_enabled", "message": "第二阶段待实现独立虚拟账户"}

    def submit_order(self, order):
        raise RuntimeError("第一阶段仅历史回测，模拟账户执行尚未启用")

    def cancel_order(self, order_id):
        raise RuntimeError("第一阶段无模拟订单")


class FutureLiveBroker(BrokerAdapter):
    def __init__(self, *args, **kwargs):
        raise RuntimeError("实盘接口永久禁用：当前版本无实盘实现及启用配置")

    def account(self):
        raise RuntimeError("实盘禁用")

    def submit_order(self, order):
        raise RuntimeError("实盘禁用")

    def cancel_order(self, order_id):
        raise RuntimeError("实盘禁用")
