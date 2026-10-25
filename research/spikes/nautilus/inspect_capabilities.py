"""Capture installed-v1 API facts and source hashes without calling a venue."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import nautilus_trader
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel, LatencyModel
from nautilus_trader.trading.strategy import Strategy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if nautilus_trader.__version__ != "1.231.0":
        raise SystemExit("This probe is pinned to the v1 1.231.0 API")
    root = Path(nautilus_trader.__file__).parent
    source_paths = [
        "backtest/engine.pyx",
        "backtest/models/fill.pyx",
        "backtest/models/latency.pyx",
        "trading/strategy.pyx",
        "trading/trader.py",
        "common/actor.pyx",
    ]
    engine_doc = BacktestEngine.add_venue.__doc__ or ""
    source_hashes = {
        path: hashlib.sha256((root / path).read_bytes()).hexdigest()
        for path in source_paths
    }
    metadata = importlib.metadata.distribution("nautilus_trader")
    result = {
        "engine_version": nautilus_trader.__version__,
        "license_metadata": metadata.metadata.get("License"),
        "wheel": metadata.read_text("WHEEL"),
        "public_engine_members": sorted(name for name in dir(BacktestEngine) if not name.startswith("_")),
        "strategy_callbacks": sorted(name for name in dir(Strategy) if name.startswith("on_")),
        "add_venue_documented_options": {
            name: name in engine_doc
            for name in ("queue_position", "liquidity_consumption", "latency_model", "use_message_queue")
        },
        "custom_fill_model_hook_present": hasattr(FillModel, "get_orderbook_for_fill_simulation"),
        "latency_model_present": LatencyModel is not None,
        "installed_source_sha256": source_hashes,
        "interpretation": "API/source inventory only; presence is not a successful behavioral test",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"engine_version": result["engine_version"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
