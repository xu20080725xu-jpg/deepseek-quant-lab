from pathlib import Path
from zoneinfo import ZoneInfo
import os
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def is_cloud():
    return os.getenv("QUANTLAB_CLOUD", "0") == "1"


def settings():
    # Never mutate process environment when reloading a local .env.
    values = {} if is_cloud() else dict(dotenv_values(ROOT / ".env"))
    values.update(os.environ)
    if is_cloud():
        import streamlit as st
        try:
            values.update(st.secrets.to_dict())
        except FileNotFoundError:
            pass
    return values


def api_config():
    values = settings()
    key = str(values.get("DEEPSEEK_API_KEY", "")).strip()
    if is_cloud():
        from quantlab.cloud_access import owner_authorized
        if not owner_authorized.get():
            key = ""
    return {
        "key": key,
        "base_url": values.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": values.get("DEEPSEEK_MODEL", "deepseek-flash"),
        "timeout": float(values.get("DEEPSEEK_TIMEOUT", "45")),
        "input_price": values.get("DEEPSEEK_INPUT_PRICE", ""),
        "output_price": values.get("DEEPSEEK_OUTPUT_PRICE", ""),
    }
