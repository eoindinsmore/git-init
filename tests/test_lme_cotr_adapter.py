"""LME COTR adapter tests — offline, against the real captured XLSX."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from adapters.base import AdapterError
from adapters.lme_cotr import (
    LmeCotrAdapter,
    _file_url,
    _recent_tuesdays,
    extract_position,
    read_cotr_xlsx,
)
from registry.schema import Category, Frequency, SAStatus, SeriesSpec, Tags

SPEC = SeriesSpec(
    series_id="copper_lme_inv_funds_long",
    source="lme_cotr",
    source_code="ca",
    name="LME Copper COTR — Investment Funds long (total)",
    unit="lots",
    frequency=Frequency.W,
    sa_status=SAStatus.NSA,
    tags=Tags(metal="copper", country="GB", category=Category.POSITIONING),
    source_params={"folder": "ca-copper", "key": "ca", "category": "Investment Funds",
                   "side": "Long", "basis": "Total"},
)
REGISTRY = {SPEC.series_id: SPEC}


def _a() -> LmeCotrAdapter:
    return LmeCotrAdapter(registry=REGISTRY)


def test_recent_tuesdays():
    tues = _recent_tuesdays(date(2026, 7, 5), 3)  # Sunday
    assert tues == [date(2026, 6, 30), date(2026, 6, 23), date(2026, 6, 16)]
    assert all(t.weekday() == 1 for t in tues)  # all Tuesdays


def test_file_url_scheme():
    url = _file_url("ca-copper", "ca", date(2026, 6, 30))
    assert url.endswith("/ca-copper/mifid-weekly-cotr-report--ca--30062026.xlsx")


def test_read_dates(lme_cotr_xlsx):
    position_date, publish_ts, rows = read_cotr_xlsx(lme_cotr_xlsx)
    # position date = prior Friday; publication = the Tuesday. as_of must be > date.
    assert publish_ts > position_date
    assert str(position_date.date()) == "2026-06-26"
    assert len(rows) > 15


def test_extract_known_cells(lme_cotr_xlsx):
    _, _, rows = read_cotr_xlsx(lme_cotr_xlsx)
    # Values verified against the raw fixture inspection.
    ep = extract_position
    assert ep(rows, "Investment Funds", "Long", "Total") == pytest.approx(53744.88)
    assert ep(rows, "Investment Funds", "Short", "Total") == pytest.approx(27274.24)
    assert ep(rows, "Commercial Undertaking", "Long", "Total") == pytest.approx(131384.69)


def test_parse_and_pit(lme_cotr_xlsx):
    df = _a().parse(SPEC, [lme_cotr_xlsx])
    assert list(df.columns) == ["date", "value", "as_of", "last_updated"]
    assert len(df) == 1
    row = df.iloc[0]
    assert float(row["value"]) == pytest.approx(53744.88)
    assert pd.to_datetime(row["as_of"]) > pd.to_datetime(row["date"])  # published after snapshot


def test_run_writes_pit_safe(tmp_path, lme_cotr_xlsx, monkeypatch):
    facts = tmp_path / "facts.parquet"
    a = _a()
    monkeypatch.setattr(a, "fetch_raw", lambda spec: [lme_cotr_xlsx])
    assert a.run("copper_lme_inv_funds_long", path=facts) == 1

    from quant import store
    _, publish_ts, rows = read_cotr_xlsx(lme_cotr_xlsx)
    position_date = pd.to_datetime(read_cotr_xlsx(lme_cotr_xlsx)[0])
    # not visible on the Friday snapshot date; visible once published
    assert len(store.get_series("copper_lme_inv_funds_long", as_of=position_date, path=facts)) == 0
    assert len(store.get_series("copper_lme_inv_funds_long", as_of=publish_ts, path=facts)) == 1
    assert a.run("copper_lme_inv_funds_long", path=facts) == 0  # idempotent


def test_bad_category_fails_loudly(lme_cotr_xlsx):
    _, _, rows = read_cotr_xlsx(lme_cotr_xlsx)
    with pytest.raises(AdapterError, match="category 'Nonexistent' not found"):
        extract_position(rows, "Nonexistent", "Long", "Total")


def test_fetch_requires_folder_key():
    spec = SPEC.model_copy(
        update={"source_params": {"category": "Investment Funds", "side": "Long"}}
    )
    a = LmeCotrAdapter(registry={spec.series_id: spec})
    with pytest.raises(AdapterError, match="needs 'folder' and 'key'"):
        a.fetch_raw(spec)
