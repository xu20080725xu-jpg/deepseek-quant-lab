"""Public visitors get isolated temporary stores; server-paid AI requires owner login."""
from contextvars import ContextVar
import hashlib
import hmac
import secrets
import tempfile
import time
from pathlib import Path

owner_authorized = ContextVar("owner_authorized", default=False)
session_cache = ContextVar("session_cache", default=None)


def hash_password(password, salt=None):
    if len(password) < 16:
        raise ValueError("请使用至少16个字符的独立访问口令")
    salt = salt or secrets.token_hex(16)
    iterations = 600_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, digest = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(iterations) <= 1_000_000:
            return False
        if len(salt) != 32 or len(digest) != 64 or len(password) > 1024:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(actual, digest)
    except (TypeError, ValueError, AttributeError):
        return False


def cloud_store():
    import streamlit as st
    from quantlab.config import DATA, settings
    from quantlab.storage import Store

    encoded = str(settings().get("QUANTLAB_PASSWORD_HASH", ""))
    signature = hashlib.sha256(encoded.encode()).hexdigest() if encoded else None
    authorized = bool(signature and st.session_state.get("owner_signature") == signature)
    if st.session_state.get("owner_signature") and not authorized:
        # Revoking/rotating the owner credential also removes private UI state.
        st.session_state.clear()
    owner_authorized.set(authorized)
    with st.sidebar.expander("站主登录", expanded=False):
        if authorized:
            st.success("站主已登录")
            if st.button("退出站主账号"):
                st.session_state.clear()
                owner_authorized.set(False)
                st.rerun()
        elif encoded:
            with st.form("owner_login", clear_on_submit=True):
                password = st.text_input("访问口令", type="password", max_chars=1024)
                submitted = st.form_submit_button("登录")
            if submitted:
                locked_until = st.session_state.get("login_locked_until", 0)
                if time.monotonic() < locked_until:
                    st.error("尝试次数过多，请稍后重试")
                elif verify_password(password, encoded):
                    st.session_state.clear()
                    st.session_state.owner_signature = signature
                    st.rerun()
                else:
                    count = st.session_state.get("login_failures", 0) + 1
                    st.session_state.login_failures = count
                    if count >= 5:
                        st.session_state.login_locked_until = time.monotonic() + 60
                        st.session_state.login_failures = 0
                    st.error("访问口令不正确")
        else:
            st.caption("站主尚未配置访问口令。请按部署指南在平台 Secrets 配置口令哈希和 DeepSeek Key。")
    if authorized:
        folder = DATA / "owner"
        folder.mkdir(parents=True, exist_ok=True)
    else:
        if "visitor_directory" not in st.session_state:
            st.session_state.visitor_directory = tempfile.TemporaryDirectory(prefix="quantlab-visitor-")
        folder = Path(st.session_state.visitor_directory.name)
    session_cache.set(folder / "cache")
    st.sidebar.caption("云端站主模式" if authorized else "访客模式 · 本次会话数据独立")
    st.sidebar.caption("免费云端磁盘可能重置，请导出重要实验和研究报告。")
    return Store(folder / "quantlab.sqlite3"), authorized
