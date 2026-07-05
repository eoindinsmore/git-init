"""Price decomposition — "why did the price move" attribution.

Calls quant.decomp; the app renders the contributions and betas. The orthogonalization
order and any missing drivers are shown so the tool's limits are visible.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app import theme  # noqa: E402
from app import toolkit_ui as ui  # noqa: E402
from quant.decomp import contributions_frame, load_named, run_decomposition  # noqa: E402

theme.configure_page("Decomposition")

ui.page_header(
    "Desk product",
    "Price decomposition",
    "Rolling regression of a target's returns on a declared driver set, with the "
    "residual explicitly labelled unexplained. Contributions are additive.",
)

SPECS = ["copper", "aluminium"]
name = st.sidebar.radio("Target", SPECS, format_func=str.title, key="decomp_target")


@st.cache_data(show_spinner="Running the decomposition…")
def _run(spec_name: str):
    run = run_decomposition(load_named(spec_name))
    return run, contributions_frame(run)


run, contrib = _run(name)
r = run.result

c1, c2, c3 = st.columns(3)
c1.metric("R²", f"{r.rsquared:.2f}")
c2.metric("Observations", r.nobs)
c3.metric("Drivers used", len(run.used))

ui.missing_note(run.missing)

st.markdown(
    f"<div class='chart-sub'>Orthogonalization order: "
    f"<b>{' → '.join(run.spec.label_of(s) for s in r.order) or '(none)'}</b> "
    "(sequential economic residualization).</div>",
    unsafe_allow_html=True,
)
st.markdown("---")

left, right = st.columns([3, 2])
with left:
    theme.title_block("Contribution to the price change", "Log-return units · additive")
    st.altair_chart(
        ui.contribution_bar(contrib, label_field="label", value_field="contribution"),
        use_container_width=True,
    )
    st.caption(f"Actual (total): {r.actual:+.4f}  ·  sum of contributions matches by construction.")

with right:
    theme.title_block("Betas", "HAC t-stats · rolling sign-flips")
    beta_rows = []
    for nm in r.betas.index:
        lbl = "const" if nm == "const" else run.spec.label_of(nm)
        beta_rows.append({
            "driver": lbl, "β": round(float(r.betas[nm]), 3),
            "t (HAC)": round(float(r.tvalues[nm]), 2),
            "flips": int(r.sign_flips.get(nm, 0)),
        })
    st.dataframe(beta_rows, use_container_width=True, hide_index=True)

theme.source_line(
    f"Source: quant.decomp · target {run.spec.target} · "
    f"{'point-in-time' if run.as_of is not None else 'current-best'} view."
)
