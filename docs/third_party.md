# Third-party libraries & licences

Charter constraint #3: no GPL code; record every third-party library's licence
here before relying on it. Cuemacro libs (findatapy/finmarketpy/chartpy) are
Apache-2.0 and may be adapted with attribution; `pysystemtrade` is GPL-3.0 and
must **never** be copied or closely adapted — reimplement concepts from scratch.

## Runtime dependencies

| Library | Licence | Used for | Notes |
|---|---|---|---|
| pydantic | MIT | schemas / config | |
| pandas | BSD-3-Clause | fact table, all analytics | |
| pyarrow | Apache-2.0 | Parquet store | |
| numpy | BSD-3-Clause | numerics | |
| requests | Apache-2.0 | adapters | |
| pyyaml | MIT | registry loader | |
| python-dotenv | BSD-3-Clause | secrets from `.env` | |
| tenacity | Apache-2.0 | adapter retry/backoff | |
| openpyxl | MIT | registry control workbook | |
| ruamel.yaml | MIT | workbook↔YAML round-trip | |
| yfinance | Apache-2.0 | price-proxy capture | |
| streamlit | Apache-2.0 | dashboard app | |
| altair | BSD-3-Clause | charts | |

## Quant toolkit numerical stack (`pip install -e .[quant]`)

| Library | Licence | Used for | Notes |
|---|---|---|---|
| scipy | BSD-3-Clause | distributions (DM/DSR), pinv, stats | |
| statsmodels | BSD-3-Clause | OLS + Newey–West HAC errors | |
| scikit-learn | BSD-3-Clause | PCA (point-in-time composites) | |

All three are permissive BSD-3 — charter-compliant. No GPL in the tree.

## Track-record PDF (`pip install -e .[report]`)

| Library | Licence | Used for | Notes |
|---|---|---|---|
| weasyprint | BSD-3-Clause | tracker one-page track-record PDF | Optional. HTML report always works without it; only the PDF renderer needs it. Native deps (Pango/cairo) can be awkward on Windows — the renderer degrades PDF→HTML if absent. |

**Reimplemented, not borrowed:** the backtester's Carver-style forecast capping
and volatility-targeted sizing are reimplemented from the published concepts, not
copied from `pysystemtrade` (GPL-3.0).
