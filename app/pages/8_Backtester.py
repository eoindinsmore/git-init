"""Backtester — signal → position → P&L, honestly.

Calls quant.backtest; the app renders the equity curve and the honest headline stats
(deflated Sharpe, bootstrap p-value). Uses the copper positioning composite as the
signal by default."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app import data_access as da  # noqa: E402
from app import theme  # noqa: E402
from app import toolkit_ui as ui  # noqa: E402
from quant.backtest import backtest_signal  # noqa: E402
from quant.composites import build_composite, load_named  # noqa: E402

theme.configure_page("Backtester")

ui.page_header(
    "Would it survive real capital?",
    "Backtester",
    "Vol-targeted, cost-aware, walk-forward. The deflated Sharpe and bootstrap p-value "
    "discount the headline for multiple testing and return autocorrelation.",
)

ids = ui.series_with_data()
price_like = [s for s in ["copper_price_global", "aluminium_premium_mw_us",
                          "aluminium_premium_eu_dp"] if s in ids] or ids[:1]
instrument = st.sidebar.selectbox("Instrument (traded)", price_like, key="bt_instrument")
n_tried = st.sidebar.slider("Variants tried (deflates Sharpe)", 1, 100, 8, key="bt_ntried")


@st.cache_data(show_spinner="Backtesting…")
def _run(instrument: str, n_tried: int):
    sig = build_composite(load_named("positioning_copper"), as_of=None,
                          registry=da.registry()).signal
    res = backtest_signal(sig, instrument, n_variants_tried=n_tried)
    return res, ui.signal_frame(res.equity), sig.signal_id


res, equity, sig_id = _run(instrument, n_tried)
m = res.metrics

st.markdown(f"<div class='chart-sub'>Signal: <b>{sig_id}</b> → traded on "
            f"<b>{instrument}</b></div>", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sharpe (ann)", f"{m['sharpe_ann']:.2f}")
c2.metric("Deflated Sharpe", f"{m['deflated_sharpe']:.2f}",
          help="P(true Sharpe > 0) after adjusting for variants tried")
c3.metric("Max drawdown", f"{m['max_drawdown']:.3f}")
c4.metric("Bootstrap p", f"{m['bootstrap_pvalue']:.2f}",
          help="One-sided block-bootstrap p-value that mean P&L ≤ 0")

st.markdown("---")
theme.title_block("Cumulative net P&L", "Return units · after costs")
st.altair_chart(ui.area_chart(equity, y_unit="cum. P&L"), use_container_width=True)

with st.expander("All metrics"):
    st.dataframe(
        [{"metric": k, "value": round(float(v), 5)} for k, v in m.items()],
        use_container_width=True, hide_index=True,
    )
theme.source_line("Source: quant.backtest · reimplemented forecast capping + vol targeting, "
                  "per-instrument bps costs.")
