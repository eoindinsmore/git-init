"""Registry loader — reads ``registry/*.yaml`` into validated ``SeriesSpec`` objects.

Fails loudly on: unreadable YAML, schema violations (via pydantic), duplicate
``series_id`` across files, and price proxies missing caveats. A malformed
registry must never load silently — everything downstream trusts it.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from registry.schema import SeriesSpec

REGISTRY_DIR = Path(__file__).resolve().parent


class RegistryError(RuntimeError):
    """Raised on any registry-integrity problem (loud failure)."""


def _load_file(path: Path) -> list[SeriesSpec]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RegistryError(f"{path.name}: invalid YAML — {e}") from e

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RegistryError(
            f"{path.name}: expected a top-level list of series, got {type(raw).__name__}"
        )

    specs: list[SeriesSpec] = []
    for i, item in enumerate(raw):
        try:
            specs.append(SeriesSpec.model_validate(item))
        except ValidationError as e:
            raise RegistryError(f"{path.name}: series #{i} failed validation —\n{e}") from e
    return specs


def load_registry(registry_dir: Path | None = None) -> dict[str, SeriesSpec]:
    """Load every ``*.yaml`` under ``registry_dir`` into a ``series_id -> SeriesSpec`` map.

    Raises ``RegistryError`` on any integrity problem, including duplicate ids
    across files (reported with both source files).
    """
    directory = registry_dir or REGISTRY_DIR
    out: dict[str, SeriesSpec] = {}
    origin: dict[str, str] = {}  # series_id -> filename, for duplicate reporting

    for path in sorted(directory.glob("*.yaml")):
        for spec in _load_file(path):
            if spec.series_id in out:
                raise RegistryError(
                    f"duplicate series_id '{spec.series_id}' "
                    f"in {path.name} (already declared in {origin[spec.series_id]})"
                )
            out[spec.series_id] = spec
            origin[spec.series_id] = path.name

    return out


def get_spec(series_id: str, registry_dir: Path | None = None) -> SeriesSpec:
    """Fetch a single spec by id, raising ``RegistryError`` if undeclared."""
    registry = load_registry(registry_dir)
    try:
        return registry[series_id]
    except KeyError:
        raise RegistryError(f"series '{series_id}' is not declared in the registry") from None
