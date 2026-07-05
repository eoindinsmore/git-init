"""The ``Signal`` abstraction — the one object every quant module emits.

Spec §0.1: the backtester, dashboard, tracker and reports consume *only* this
interface, so an indicator, a composite and a nowcast are interchangeable to
everything downstream. A ``Signal`` is a point-in-time-constructed, date-indexed
series plus the provenance and methodology needed to trust it.

Point-in-time note: ``values`` must already be point-in-time constructed by the
producer (via :func:`quant.pit.get_series_asof`). A ``Signal`` also carries its
own ``publication_lag_days`` — the worst-case lag across its inputs — so a
consumer knows a value dated period-end ``T`` is only *usable* at
``T + publication_lag_days``. Use :meth:`Signal.resolve_as_of` to get the usable
series as of a decision date.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class ScorecardRef(BaseModel):
    """A lightweight pointer to a written scorecard.

    Kept separate from the full :class:`quant.scorecard.Scorecard` so a ``Signal``
    can reference its evaluation without importing (or embedding) the heavier
    stats payload. ``path`` is repo-relative (e.g. ``docs/scorecards/<id>.json``).
    """

    model_config = ConfigDict(extra="forbid")

    scorecard_id: str
    path: str


class Signal(BaseModel):
    """A standard, point-in-time signal emitted by any quant module.

    Failure modes (all raise ``ValidationError``): a non-``DatetimeIndex``,
    unsorted or duplicate-dated ``values``; empty ``provenance``; negative
    ``publication_lag_days``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    signal_id: str
    values: pd.Series  # DatetimeIndex, point-in-time constructed
    direction_convention: str  # e.g. "high = bullish copper"
    target: str  # what it is meant to lead/explain
    provenance: list[str]  # registry series_ids used to build it
    construction: str  # short human-readable methodology
    publication_lag_days: int  # worst-case lag across all inputs (days)
    created_as_of: date
    scorecard: ScorecardRef | None = None

    @field_validator("values")
    @classmethod
    def _check_values(cls, v: pd.Series) -> pd.Series:
        if not isinstance(v, pd.Series):
            raise ValueError("values must be a pandas Series")
        if not isinstance(v.index, pd.DatetimeIndex):
            raise ValueError("values must be indexed by a DatetimeIndex (point-in-time dates)")
        if v.index.has_duplicates:
            raise ValueError("values index has duplicate dates; one value per date")
        if not v.index.is_monotonic_increasing:
            raise ValueError("values must be sorted by date ascending")
        return v

    @field_validator("provenance")
    @classmethod
    def _check_provenance(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("provenance must list at least one registry series_id")
        return v

    @field_validator("publication_lag_days")
    @classmethod
    def _check_lag(cls, v: int) -> int:
        if v < 0:
            raise ValueError("publication_lag_days must be >= 0")
        return v

    @model_validator(mode="after")
    def _name_values(self) -> Signal:
        # Give the Series a stable name so downstream frames/plots label correctly.
        if self.values.name is None:
            self.values.rename(self.signal_id, inplace=True)
        return self

    def to_frame(self) -> pd.DataFrame:
        """Return ``[date, value]`` — the shape the chart/transform code consumes."""
        return pd.DataFrame(
            {"date": self.values.index, "value": self.values.to_numpy()}
        ).reset_index(drop=True)

    def resolve_as_of(self, as_of: str | pd.Timestamp) -> pd.Series:
        """The sub-series usable on ``as_of``: values whose ``date + lag <= as_of``.

        This applies the signal's *own* publication lag. A value dated period-end
        ``T`` only becomes usable at ``T + publication_lag_days``, so a consumer
        making a decision on ``as_of`` must not see values released after it.
        """
        cutoff = pd.Timestamp(as_of)
        usable_dates = self.values.index + pd.Timedelta(days=self.publication_lag_days)
        return self.values[usable_dates <= cutoff]


def worst_case_lag(provenance: list[str], registry: dict) -> int:
    """Max ``publication_lag_days`` across the provenance series in the registry.

    A signal built from several inputs is only as timely as its slowest input, so
    modules call this instead of hand-setting the lag. ``registry`` is the
    ``series_id -> SeriesSpec`` map from :func:`registry.loader.load_registry`.
    Raises ``KeyError`` if a provenance id is not declared (fail loud).
    """
    if not provenance:
        raise ValueError("provenance must list at least one series_id")
    lags = []
    for sid in provenance:
        spec = registry[sid]  # KeyError on undeclared id — intentional loud failure
        lags.append(int(spec.publication_lag_days))
    return max(lags)
