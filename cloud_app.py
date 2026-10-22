"""Streamlit Community Cloud entrypoint. Public sessions cannot use server API keys."""
import os
import runpy
from pathlib import Path

os.environ["QUANTLAB_CLOUD"] = "1"
runpy.run_path(str(Path(__file__).resolve().with_name("app.py")), run_name="__main__")
