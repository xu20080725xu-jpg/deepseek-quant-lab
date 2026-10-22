import json
from datetime import datetime, timedelta
import httpx
import pytest
from quantlab.broker import FutureLiveBroker, PaperBroker
from quantlab.config import SHANGHAI
from quantlab.data import AKShareProvider, load_example
from quantlab.deepseek_client import AIError, DeepSeekClient, EXAMPLE, ResearchReply, redact
from quantlab.risk_manager import RiskManager
from quantlab.storage import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.sqlite3")


def config(**kwargs):
    return {"key": "sk-test-secret123456", "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
            "timeout": 1., "input_price": "0.3", "output_price": "1.2", **kwargs}


def response(content=None, finish_reason="stop"):
    return {"choices": [{"finish_reason": finish_reason, "message": {"content": json.dumps(content or EXAMPLE)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200}}


def test_real_client_contract_strict_schema_and_secret_redaction(store):
    def handler(request):
        assert request.url.host == "api.deepseek.com"
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert "sk-test-secret123456" not in request.content.decode()
        return httpx.Response(200, json=response())
    reply = DeepSeekClient(store, config(), httpx.MockTransport(handler)).research("分析 sk-test-secret123456", {"source": "historical"})
    assert isinstance(reply, ResearchReply)
    usage = store.rows("api_usage")[0]
    assert usage["input_tokens"] == 100
    assert usage["estimated_usd"] == pytest.approx(.00027)
    assert "sk-test" not in str(store.rows("reports"))


@pytest.mark.parametrize("change", [{"unexpected": True}, {"strategy": {"kind": "execute_python"}},
                                  {"strategy": {"short": 30, "long": 20}}])
def test_ai_output_fails_closed(store, change):
    invalid = {**EXAMPLE, **change}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=response(invalid)))
    with pytest.raises(AIError, match="校验"):
        DeepSeekClient(store, config(), transport).research("test", {})
    assert not store.rows("reports")
    assert len(store.rows("api_usage")) == 1  # Tokens still recorded on invalid AI content.


def test_api_finite_retry_and_nonretryable_401(store):
    calls = []
    def limited(request):
        calls.append(1)
        return httpx.Response(429)
    with pytest.raises(AIError):
        DeepSeekClient(store, config(), httpx.MockTransport(limited), sleeper=lambda _: None).research("x", {})
    assert len(calls) == 3
    calls.clear()
    def unauthorized(request):
        calls.append(1)
        return httpx.Response(401)
    with pytest.raises(AIError, match="无效"):
        DeepSeekClient(store, config(), httpx.MockTransport(unauthorized)).research("x", {})
    assert len(calls) == 1


def test_timeout_no_duplicate_billing_retry(store):
    calls = []
    def timeout(request):
        calls.append(1)
        raise httpx.ReadTimeout("sensitive error text", request=request)
    with pytest.raises(AIError, match="可能已计费"):
        DeepSeekClient(store, config(), httpx.MockTransport(timeout)).research("x", {})
    assert len(calls) == 1
    assert "sensitive" not in str(store.rows("api_usage"))


def test_missing_key_never_calls_network(store):
    def handler(_):
        pytest.fail("No key must not call HTTP")
    with pytest.raises(AIError, match="未配置"):
        DeepSeekClient(store, config(key=""), httpx.MockTransport(handler)).research("x", {})


def test_official_host_required(store):
    with pytest.raises(AIError):
        DeepSeekClient(store, config(base_url="https://example.com"))


def test_risk_history_sample_and_stale_data_fail_closed(store):
    guard = RiskManager(store)
    assert not guard.check_market_data(load_example().meta, 10)[0]
    store.save_setting("emergency_stop", False)
    assert not guard.check_market_data({"kind": "historical"}, 10)[0]
    now = datetime.now(SHANGHAI)
    meta = {"kind": "verified_realtime", "quote_time": (now - timedelta(minutes=2)).isoformat()}
    assert "过期" in guard.check_market_data(meta, 10, now)[1]
    assert not guard.check_market_data({"kind": "verified_realtime", "quote_time": now.isoformat()}, 10, now)[0]


def test_live_and_paper_execution_disabled():
    with pytest.raises(RuntimeError):
        FutureLiveBroker()
    with pytest.raises(RuntimeError):
        PaperBroker().submit_order({"side": "BUY"})
    with pytest.raises(Exception):
        AKShareProvider().quote("000001")


def test_setting_audit_and_watchlist_persist(store):
    store.save_setting("fees", {"minimum": 5})
    assert store.setting("fees")["minimum"] == 5
    assert store.rows("audit")[0]["action"] == "setting_changed"
    store.watch("000001", "平安银行")
    assert store.rows("watchlist")[0]["symbol"] == "000001"
    store.watch("000001", "", remove=True)
    assert not store.rows("watchlist")
