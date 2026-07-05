"""Registry schema — every series is declared here before its first pull.

The registry is the single source of truth for what a series *is*: its source,
canonical units, frequency, seasonal-adjustment status, default transformations
and tags. Adapters validate their output against these declarations, and charts /
PDFs read caveats from here.

Charter requirement: any series with ``category: price_proxy`` MUST carry a
non-empty ``caveats`` field (it auto-renders on charts and reports).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Frequency(StrEnum):
    """Observation frequency. Values match FRED's ``frequency_short``."""

    D = "D"  # daily
    W = "W"  # weekly
    M = "M"  # monthly
    Q = "Q"  # quarterly
    A = "A"  # annual


class SAStatus(StrEnum):
    """Seasonal-adjustment status."""

    SA = "SA"  # seasonally adjusted
    NSA = "NSA"  # not seasonally adjusted


class Category(StrEnum):
    """Broad role of the series in the platform.

    This drives *behaviour* — e.g. ``price_proxy`` forces a ``caveats`` field and
    auto-renders it on charts. Do not overload it with dashboard grouping; that is
    what ``MacroTheme`` is for.
    """

    ACTIVITY = "activity"  # industrial production, PMIs, etc.
    PRICE_PROXY = "price_proxy"  # free stand-in for a licensed price
    SUPPLY = "supply"  # production, mine output, stocks
    DEMAND = "demand"  # apparent/end-use demand
    TRADE = "trade"  # imports/exports
    POSITIONING = "positioning"  # COT and similar
    ENERGY = "energy"  # energy input costs
    OTHER = "other"


class MacroTheme(StrEnum):
    """Dashboard grouping axis — independent of ``Category``.

    ``Category`` encodes a series' *role* (and drives behaviour like price-proxy
    caveats); ``MacroTheme`` is the reader-facing bucket the app filters on
    (Activity / Inflation / Rates / Commodity prices / Positioning). Kept separate
    so the two taxonomies can evolve without colliding. Optional: a series with no
    theme groups under "Unclassified" in the UI.
    """

    ACTIVITY = "activity"  # industrial production, PMIs, orders, output
    INFLATION = "inflation"  # CPI/PPI/deflators (no series yet)
    RATES = "rates"  # policy rates, yields (no series yet)
    COMMODITIES = "commodities"  # commodity prices & physical premiums
    POSITIONING = "positioning"  # COT / futures positioning
    ENERGY = "energy"  # energy input costs
    OTHER = "other"


class Tags(BaseModel):
    """Classification tags. ``metal`` and ``country`` are free-form but lowercased
    by convention; ``category`` drives behaviour (e.g. price-proxy caveats)."""

    model_config = ConfigDict(extra="forbid")

    metal: str | None = None  # e.g. "copper", "aluminium", or None (macro)
    country: str | None = None  # ISO-ish short code or name, e.g. "US", "DE"
    category: Category
    macro_theme: MacroTheme | None = None  # reader-facing dashboard bucket (app filter)


class SeriesSpec(BaseModel):
    """Declaration of a single series. Immutable once loaded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    series_id: str = Field(min_length=1)  # our canonical id (unique across registry)
    source: str = Field(min_length=1)  # adapter/source key, e.g. "fred"
    source_code: str = Field(min_length=1)  # the id in the source system, e.g. "INDPRO"
    name: str = Field(min_length=1)  # human-readable title
    unit: str = Field(min_length=1)  # canonical unit string
    frequency: Frequency
    sa_status: SAStatus
    transformations: list[str] = Field(default_factory=list)  # default transforms, e.g. ["yoy"]
    tags: Tags
    caveats: str | None = None  # required for price proxies; auto-rendered on charts/PDFs

    # Point-in-time honesty (quant toolkit foundation). ``publication_lag_days`` is the
    # typical number of days from an observation's period-end to its first public release.
    # It is what makes lead-lag tests and nowcasts honest: the March value of a series with
    # a 45-day lag is not knowable on 1 April even though the store may hold it (e.g. because
    # history was backfilled today under a single ``as_of``). ``quant.pit.get_series_asof``
    # enforces it. 0 = knowable at period end (correct for daily price proxies).
    publication_lag_days: int = Field(default=0, ge=0)
    release_schedule: str | None = None  # optional human note, e.g. "monthly, ~15th of month"

    # Optional, for richer sources:
    # source_params — extra query parameters the adapter sends when fetching
    #   (e.g. Eurostat dimension filters: geo, nace_r2, s_adj, unit).
    source_params: dict[str, str] = Field(default_factory=dict)
    # selector — post-fetch selection of ONE series from a multi-dimensional
    #   payload, mapping the source's dimension id to the category code to keep
    #   (e.g. e-Stat {"cat02": "2021010010"}). Empty for single-series sources.
    selector: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _price_proxy_needs_caveats(self) -> SeriesSpec:
        is_proxy = self.tags.category is Category.PRICE_PROXY
        if is_proxy and not (self.caveats and self.caveats.strip()):
            raise ValueError(
                f"series '{self.series_id}' is category=price_proxy and must carry a "
                "non-empty 'caveats' field (charter requirement)"
            )
        return self
