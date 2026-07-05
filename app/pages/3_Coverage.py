"""Coverage — per-series row counts, date spans, and vintage freshness.

Descriptive reads of the fact table (counts, min/max date, latest as_of). This is
reading the store, not analytics.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app import data_access as da  # noqa: E402
from app import theme

theme.configure_page("Coverage")

st.markdown("<div class='page-kicker'>Coverage</div>", unsafe_allow_html=True)
st.markdown("<div class='page-title'>Data coverage & freshness</div>",
            unsafe_allow_html=True)
st.markdown(
    "<div class='chart-sub'>Every declared series, its history depth, and how stale its "
    "latest observation is. n_rows counts point-in-time vintages; n_obs counts distinct "
    "observation dates.</div>",
    unsafe_allow_html=True,
)

reg = da.registry()
cov = da.coverage_table()

if cov.empty:
    st.info("The fact table is empty — run an adapter to populate data/facts.parquet.")
    st.stop()

# Enrich with registry context (name, theme, region) — all reads.
cov = cov.assign(
    name=cov["series_id"].map(lambda s: reg[s].name if s in reg else s),
    theme=cov["series_id"].map(
        lambda s: reg[s].tags.macro_theme.value if s in reg and reg[s].tags.macro_theme else "—"
    ),
    region=cov["series_id"].map(
        lambda s: da.region_for(reg[s].tags.country) if s in reg else "—"
    ),
)
cov["first_date"] = cov["first_date"].dt.date
cov["last_date"] = cov["last_date"].dt.date
cov["latest_as_of"] = cov["latest_as_of"].dt.date

c1, c2, c3 = st.columns(3)
c1.metric("Series with data", len(cov))
c2.metric("Total vintages (rows)", f"{int(cov['n_rows'].sum()):,}")
c3.metric("Stalest (days)", int(cov["staleness_days"].max()))

st.markdown("---")

cols = ["series_id", "name", "theme", "region", "source", "frequency",
        "n_obs", "n_rows", "first_date", "last_date", "latest_as_of", "staleness_days"]
st.dataframe(
    cov[cols].sort_values("staleness_days", ascending=False),
    hide_index=True, use_container_width=True,
)

theme.source_line(
    "Freshness is now − last observation date; weekly/monthly series will naturally show "
    "a few days/weeks of staleness between releases. Loud staleness (an adapter stopped) "
    "shows here as an unexpectedly large gap."
)
