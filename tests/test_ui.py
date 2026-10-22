"""Run the actual Streamlit app with an isolated database, including save/reload."""
from pathlib import Path
from streamlit.testing.v1 import AppTest
from quantlab.storage import Store

APP = Path(__file__).resolve().parent.parent / "app.py"


def test_all_pages_and_save_experiment_workflow(tmp_path, monkeypatch):
    store = Store(tmp_path / "ui.sqlite3")
    monkeypatch.setattr("quantlab.storage.Store", lambda: store)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert any("人工合成" in x.value for x in app.warning)
    for page in ["股票行情", "AI 策略研究", "策略回测", "模拟交易", "策略实验室", "系统设置"]:
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception, page
    app.sidebar.radio[0].set_value("策略回测").run()
    app.button[0].click().run()
    assert not app.exception
    assert len(app.metric) == 8
    save = next(b for b in app.button if b.label == "保存为新实验版本")
    save.click().run()
    assert not app.exception
    assert len(store.rows("experiments")) == 1
    app.sidebar.radio[0].set_value("策略实验室").run()
    assert not app.exception
    assert app.dataframe
    assert "ma_cross" in store.rows("experiments")[0]["name"]
