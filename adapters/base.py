"""BaseAdapter — the contract every data adapter subclasses.

Required behaviour (charter):
- retry/backoff on transient fetch failures
- incremental update (only pulls; the store dedups vintages)
- schema validation of parsed output against the series' ``SeriesSpec``
- revision capture (parsed rows carry ``as_of``; the store keeps vintages)
- **loud failure** — never silent staleness; a broken source raises
- manual-inbox fallback (``data/manual/``) for fragile sources

A subclass implements two methods:
    fetch_raw(spec)      -> raw payload (bytes / dict / str)
    parse(spec, raw)     -> DataFrame with columns [date, value, as_of, last_updated]

The base handles orchestration, retry, validation/enrichment and storage in
``run(series_id)``.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any

import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from quant import store
from quant.store import DATA_DIR
from registry.loader import load_registry
from registry.schema import SeriesSpec

# Columns a subclass's parse() must return. series_id/source/frequency/unit are
# enriched from the registry spec by the base class, not the adapter.
PARSED_COLUMNS = ["date", "value", "as_of", "last_updated"]


class AdapterError(RuntimeError):
    """Raised on unrecoverable adapter failure (loud failure — no silent staleness)."""


class TransientFetchError(AdapterError):
    """A retryable fetch failure (network blip, 5xx, rate limit)."""


class BaseAdapter(abc.ABC):
    """Base class for all source adapters.

    Subclasses set ``source`` to the registry source key they serve and
    implement ``fetch_raw`` and ``parse``.
    """

    #: Registry ``source`` value this adapter serves, e.g. "fred".
    source: str = ""

    #: Retry policy for fetch_raw (tenacity). Retries only TransientFetchError.
    max_attempts: int = 4

    def __init__(
        self,
        registry: dict[str, SeriesSpec] | None = None,
        manual_dir: Path | None = None,
    ):
        if not self.source:
            raise AdapterError(f"{type(self).__name__} must set a class-level 'source'")
        self._registry = registry if registry is not None else load_registry()
        self._manual_dir = manual_dir or (DATA_DIR / "manual" / self.source)

    # ---- subclass contract ------------------------------------------------

    @abc.abstractmethod
    def fetch_raw(self, spec: SeriesSpec) -> Any:
        """Fetch the raw payload for ``spec`` from the live source.

        Raise ``TransientFetchError`` for retryable problems (timeouts, 5xx,
        rate limits) and ``AdapterError`` for permanent ones (bad request,
        auth). The base class wraps this with retry/backoff.
        """

    @abc.abstractmethod
    def parse(self, spec: SeriesSpec, raw: Any) -> pd.DataFrame:
        """Parse ``raw`` into a DataFrame with columns ``PARSED_COLUMNS``.

        ``as_of`` is the vintage of each observation (point-in-time discipline);
        ``last_updated`` is when the source last refreshed the series.
        """

    def load_manual(self, spec: SeriesSpec) -> Any | None:
        """Manual-inbox fallback: return a raw payload from ``data/manual/`` or None.

        Override for fragile sources. Default: look for a single file named
        ``<source_code>.*`` under the adapter's manual dir and return its bytes.
        """
        if not self._manual_dir.exists():
            return None
        matches = sorted(self._manual_dir.glob(f"{spec.source_code}.*"))
        return matches[0].read_bytes() if matches else None

    # ---- orchestration ----------------------------------------------------

    def _spec(self, series_id: str) -> SeriesSpec:
        try:
            spec = self._registry[series_id]
        except KeyError:
            raise AdapterError(f"series '{series_id}' is not declared in the registry") from None
        if spec.source != self.source:
            raise AdapterError(
                f"series '{series_id}' has source '{spec.source}', not '{self.source}' "
                f"(handled by {type(self).__name__})"
            )
        return spec

    def _fetch_with_retry(self, spec: SeriesSpec) -> Any:
        retryer = retry(
            retry=retry_if_exception_type(TransientFetchError),
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
            reraise=True,
        )
        return retryer(self.fetch_raw)(spec)

    def _validate_and_enrich(self, spec: SeriesSpec, df: pd.DataFrame) -> pd.DataFrame:
        missing = set(PARSED_COLUMNS) - set(df.columns)
        if missing:
            raise AdapterError(
                f"{type(self).__name__}.parse('{spec.series_id}') "
                f"missing columns: {sorted(missing)}"
            )
        out = df.loc[:, PARSED_COLUMNS].copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out["as_of"] = pd.to_datetime(out["as_of"], errors="coerce")
        out["last_updated"] = pd.to_datetime(out["last_updated"], errors="coerce")
        out["value"] = pd.to_numeric(out["value"], errors="coerce")

        # Drop rows FRED-style "." missing values leave as NaN, but never drop
        # rows with a value yet no date/as_of — that's a parse bug, fail loudly.
        bad_pit = out[out["value"].notna() & (out["date"].isna() | out["as_of"].isna())]
        if not bad_pit.empty:
            raise AdapterError(
                f"{type(self).__name__}.parse('{spec.series_id}') produced {len(bad_pit)} "
                "row(s) with a value but no date/as_of (point-in-time discipline violated)"
            )
        out = out[out["value"].notna()]
        if out.empty:
            raise AdapterError(
                f"{type(self).__name__}.parse('{spec.series_id}') yielded zero usable observations "
                "(possible layout change) — failing loudly rather than storing nothing"
            )

        # Enrich with registry-sourced identity columns.
        out["series_id"] = spec.series_id
        out["source"] = spec.source
        out["frequency"] = spec.frequency.value
        out["unit"] = spec.unit
        return out

    def run(self, series_id: str, path: Path = store.FACTS_PATH) -> int:
        """Fetch → parse → validate → store one series. Returns rows written.

        On fetch failure after retries, tries the manual-inbox fallback; if that
        is also unavailable, raises ``AdapterError`` (loud failure).
        """
        spec = self._spec(series_id)
        try:
            raw = self._fetch_with_retry(spec)
        except Exception as e:  # noqa: BLE001 — convert any fetch failure into fallback/loud path
            raw = self.load_manual(spec)
            if raw is None:
                raise AdapterError(
                    f"fetch failed for '{series_id}' and no manual-inbox fallback at "
                    f"{self._manual_dir}/{spec.source_code}.* — {e}"
                ) from e

        df = self.parse(spec, raw)
        enriched = self._validate_and_enrich(spec, df)
        return store.write_observations(enriched, path)
