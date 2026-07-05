"""Positioning — COMEX (CFTC) vs LME (MiFID II) copper Commitments of Traders.

Plots raw long/short positioning series side by side. No net (long−short) is computed
here — that arithmetic would be analytics; the app only reads and displays.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import controls, theme  # noqa: E402
from app import data_access as da

theme.configure_page("Positioning")

reg = da.registry()
in_store = da.series_ids_in_store()


def _short(name: str) -> str:
    """Trim the exchange prefix, keeping the descriptive tail after an em dash."""
    return name.split("—")[-1].strip() if "—" in name else name


def _long_frame(series_ids: list[str]) -> pd.DataFrame:
    frames = []
    for sid in series_ids:
        df = da.get_series(sid)  # latest vintage
        if df.empty:
            continue
        df = df.assign(series=_short(reg[sid].name))
        frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# Group positioning series by source, excluding open-interest (different scale).
positioning = [
    sid for sid, s in reg.items()
    if s.tags.macro_theme and s.tags.macro_theme.value == "positioning" and sid in in_store
]
cftc = sorted(s for s in positioning if reg[s].source == "cftc" and "open_interest" not in s)
lme = sorted(s for s in positioning if reg[s].source == "lme_cotr")
oi = [s for s in positioning if "open_interest" in s]

st.markdown("<div class='page-kicker'>Positioning</div>", unsafe_allow_html=True)
st.markdown("<div class='page-title'>Copper — who's long, who's short</div>",
            unsafe_allow_html=True)
st.markdown(
    "<div class='chart-sub'>Weekly Commitments of Traders. COMEX via CFTC "
    "(disaggregated), LME via the free MiFID II report. Positions in contracts / lots — "
    "not directly comparable across exchanges.</div>",
    unsafe_allow_html=True,
)

months = controls.horizon_picker("hz_pos", default="48", sidebar=True)
st.markdown("---")

left, right = st.columns(2)
with left:
    theme.title_block("COMEX (CFTC)", "Managed money & producer/merchant · contracts")
    frame = controls.clip_horizon(_long_frame(cftc), months)
    if frame.empty:
        st.info("No CFTC positioning data in the store yet.")
    else:
        st.altair_chart(
            theme.multi_line_chart(
                frame, y_unit="contracts", x_format=theme.date_format("W", frame)
            ),
            use_container_width=True,
        )
    theme.source_line("Source: CFTC Commitments of Traders (COMEX copper), Socrata.")

with right:
    theme.title_block("LME (MiFID II)", "Investment funds & commercial · lots")
    frame = controls.clip_horizon(_long_frame(lme), months)
    if frame.empty:
        st.info("No LME COTR data in the store yet.")
    else:
        st.altair_chart(
            theme.multi_line_chart(
                frame, y_unit="lots", x_format=theme.date_format("W", frame)
            ),
            use_container_width=True,
        )
    theme.source_line("Source: LME COTR weekly (free MiFID II Article 58 disclosure).")

if oi:
    st.markdown("---")
    theme.title_block("COMEX open interest", "Total open interest · contracts")
    frame = controls.clip_horizon(da.get_series(oi[0]), months)
    if not frame.empty:
        st.altair_chart(
            theme.line_chart(
                frame, y_unit="contracts", x_format=theme.date_format("W", frame)
            ),
            use_container_width=True,
        )
    theme.source_line(f"Source: CFTC · {reg[oi[0]].source_code} · {oi[0]}")
