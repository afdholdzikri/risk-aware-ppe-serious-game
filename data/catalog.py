"""Centralized, versioned PPE and hazard catalogs loaded from JSON."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CatalogItem:
    """One selectable PPE or hazard with stable research identifier."""

    id: str
    label: str
    detail: str = ""
    scored: bool = True


def _load_catalog(filename: str) -> dict[str, CatalogItem]:
    """Load a catalog and reject duplicate or incomplete identifiers."""
    path = Path(__file__).resolve().parent / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    items = [CatalogItem(**item) for item in data["items"]]
    if not items or any(not item.id or not item.label for item in items):
        raise ValueError(f"{filename} contains an incomplete item")
    result = {item.id: item for item in items}
    if len(result) != len(items):
        raise ValueError(f"{filename} contains duplicate identifiers")
    return result


PPE_CATALOG = _load_catalog("ppe_catalog.json")
HAZARD_CATALOG = _load_catalog("hazard_catalog.json")
