"""Cloud publication must not expose the owner's key or saved research."""
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from quantlab.cloud_access import hash_password, verify_password, owner_authorized
from quantlab.deepseek_client import DeepSeekClient, AIError
from quantlab.config import api_config


def test_password_hash_validation():
    encoded = hash_password("only-for-unit-test-123")
    assert verify_password("only-for-unit-test-123", encoded)
    assert not verify_password("wrong", encoded)
    assert not verify_password("x", "invalid")
    with pytest.raises(ValueError):
        hash_password("short")


def test_guest_cannot_access_ai_even_with_injected_config(monkeypatch):
    monkeypatch.setenv("QUANTLAB_CLOUD", "1")
    monkeypatch.setattr("quantlab.config.settings", lambda: {"DEEPSEEK_API_KEY": "test-only-secret"})
    token = owner_authorized.set(False)
    try:
        assert api_config()["key"] == ""
        with pytest.raises(AIError, match="站主"):
            DeepSeekClient(None, {"key": "test-only-secret"})
        owner_authorized.set(True)
        assert api_config()["key"] == "test-only-secret"
    finally:
        owner_authorized.reset(token)


def test_cloud_guest_pages_and_isolated_experiments(monkeypatch):
    monkeypatch.setenv("QUANTLAB_CLOUD", "1")
    app_path = str(Path(__file__).resolve().parent.parent / "cloud_app.py")
    a = AppTest.from_file(app_path, default_timeout=30).run()
    assert not a.exception
    for page in ["股票行情", "AI 策略研究", "策略回测", "模拟交易", "策略实验室", "系统设置"]:
        a.sidebar.radio[0].set_value(page).run()
        assert not a.exception, page
    a.sidebar.radio[0].set_value("策略回测").run()
    next(b for b in a.button if b.label == "运行回测与分段验证").click().run()
    assert not a.exception
    next(b for b in a.button if b.label == "保存为新实验版本").click().run()
    assert not a.exception
    b = AppTest.from_file(app_path, default_timeout=30).run()
    assert not b.exception
    assert a.session_state.visitor_directory.name != b.session_state.visitor_directory.name
    from quantlab.storage import Store
    first = Store(Path(a.session_state.visitor_directory.name) / "quantlab.sqlite3")
    second = Store(Path(b.session_state.visitor_directory.name) / "quantlab.sqlite3")
    assert len(first.rows("experiments")) == 1
    assert not second.rows("experiments")


def test_cloud_login_logout_and_password_revocation(monkeypatch, tmp_path):
    monkeypatch.setenv("QUANTLAB_CLOUD", "1")
    monkeypatch.setattr("quantlab.config.DATA", tmp_path)
    encoded = hash_password("only-for-ui-test-123")
    monkeypatch.setattr("quantlab.config.settings", lambda: {"QUANTLAB_PASSWORD_HASH": encoded})
    app_path = str(Path(__file__).resolve().parent.parent / "cloud_app.py")
    app = AppTest.from_file(app_path, default_timeout=30).run()
    next(x for x in app.text_input if x.label == "访问口令").set_value("only-for-ui-test-123")
    next(x for x in app.button if x.label == "登录").click().run()
    assert not app.exception
    assert any(x.value == "站主已登录" for x in app.success)
    app.session_state["private_result"] = "private"
    next(x for x in app.button if x.label == "退出站主账号").click().run()
    assert "private_result" not in app.session_state
    assert "owner_signature" not in app.session_state
    app.session_state["owner_signature"] = "revoked-old-hash"
    app.session_state["private_result"] = "private"
    app.run()
    assert not app.exception
    assert "private_result" not in app.session_state
