# Home Hedge Fund

Personal commodities research platform. Base metals, copper-weighted. Free/public data only.
See [CLAUDE Instructions for Home Hedge Fund.md](CLAUDE%20Instructions%20for%20Home%20Hedge%20Fund.md) for the project charter.

## Setup

```
python -m venv .venv && . .venv/Scripts/activate   # Windows
pip install -e ".[dev,proxies]"
cp env.example .env   # then fill in your free API keys
```

## Status

Build order steps 1–3 complete (39 tests, ruff clean):

- **Registry + store**: `registry/` (SeriesSpec + YAML loader), `quant/store.py`
  (append-only, point-in-time Parquet fact table).
- **Adapters** (`adapters/`, all on `BaseAdapter`): FRED, Eurostat, StatCan, e-Stat,
  CFTC COT.
- **Premium capture** (`adapters/premium.py`): daily yfinance AUP/EDP capture,
  vintage-stamped; scheduled via Windows task `HomeFund-PremiumCapture`.

See `docs/*_handover.md` per module. Next: Step 4 quant toolkit.
