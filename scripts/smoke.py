"""End-to-end offline research path, no credentials needed."""
from dataclasses import asdict
from pathlib import Path
import json
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from quantlab.backtest import BacktestConfig, evaluate_splits, run_backtest
from quantlab.data import load_example
from quantlab.market_rules import FeeConfig
from quantlab.storage import Store
from quantlab.strategies import StrategySpec


def main():
    data = load_example()
    summary = {}
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / "smoke.sqlite3")
        for kind in ("ma_cross", "volume_breakout"):
            spec, cfg = StrategySpec(kind=kind), BacktestConfig()
            result = run_backtest(data.frame, spec, cfg)
            splits = evaluate_splits(data.frame, spec, cfg, FeeConfig())
            benchmark = run_backtest(data.frame, spec, cfg, buy_hold=True)
            config = {"strategy": spec.model_dump(), "account": asdict(cfg), "data": data.meta,
                      "splits": splits, "fees": asdict(FeeConfig()), "benchmark": benchmark.metrics}
            exp_id = store.save_experiment("Smoke / " + kind, config, result, data.fingerprint)
            assert exp_id and result.metrics["trade_count"] > 0
            assert result.curve.cash.min() >= 0
            summary[kind] = result.metrics
        assert len(store.rows("experiments")) == 2
    print(json.dumps({"status": "passed", "data": "synthetic, not real stock returns", "results": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
