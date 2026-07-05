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

Step 1 in progress: registry + BaseAdapter + FRED adapter + Parquet layer.
