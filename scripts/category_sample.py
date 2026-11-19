"""
Browse by category: pick a field value (e.g. MataraDesc) and get images of
N random contracts or plots with that value, one image per item.

CLI:
    uv run scripts/category_sample.py contracts MataraDesc "מסחר ושרותים אחרים"
    uv run scripts/category_sample.py plots KVUZ_TRG "מגורים" --count 3
"""

import argparse
import random
import sys
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

import requests

from arcgis_utils import object_ids, query_by_object_ids, value_counts
from combined_orthophoto import make_group_image
from contract_query import LAYER_URL as CONTRACTS_LAYER_URL
from contract_query import find_contract_field, get_layer_fields
from orthophoto import SPATIAL_REF
from plot_query import PLOTS_LAYER_URL, sql_string

# Which fields the user may browse by (a whitelist: field names never come from the user)
CATEGORY_FIELDS = {
    "contracts": ["MataraDesc"],
    "plots": ["TARGUMYEUD", "KVUZ_TRG"],
}
LAYER_URLS = {"contracts": CONTRACTS_LAYER_URL, "plots": PLOTS_LAYER_URL}
KIND = {"contracts": "contract", "plots": "plot"}

DEFAULT_COUNT = 5
MAX_COUNT = 10
OPTIONS_CACHE_SECONDS = 600  # field values rarely change; keep them for 10 minutes

_options_cache: dict[tuple[str, str], tuple[float, list]] = {}
_contract_id_field: str | None = None


def check_field(layer: str, field: str) -> None:
    if field not in CATEGORY_FIELDS.get(layer, []):
        raise ValueError(f"Unknown layer/field: {layer}/{field}")


def category_options(layer: str, field: str) -> list[dict]:
    """All values of the field with their counts, most common first (cached)."""
    check_field(layer, field)
    key = (layer, field)
    cached = _options_cache.get(key)
    if cached and time.time() - cached[0] < OPTIONS_CACHE_SECONDS:
        return cached[1]
    options = [{"value": v, "count": c} for v, c in value_counts(LAYER_URLS[layer], field)]
    _options_cache[key] = (time.time(), options)
    return options


def where_for(field: str, value) -> str:
    """SQL filter for field == value (NULL needs IS NULL in SQL)."""
    if value is None:
        return f"{field} IS NULL"
    return f"{field} = {sql_string(value)}"


def contract_id_field() -> str:
    """Name of the contract ID field (looked up once)."""
    global _contract_id_field
    if _contract_id_field is None:
        _contract_id_field = find_contract_field(get_layer_fields(CONTRACTS_LAYER_URL))
    return _contract_id_field


def item_label(layer: str, feature: dict) -> str:
    """Contract ID for contracts; 'TOCHNIT / MIGRASH' for plots."""
    attrs = feature.get("attributes") or {}
    if layer == "contracts":
        return str(attrs.get(contract_id_field(), attrs.get("OBJECTID")))
    tochnit, migrash = attrs.get("TOCHNIT"), attrs.get("MIGRASH")
    return f"{tochnit} / {migrash}" if tochnit else str(migrash)


def _error_text(e: Exception) -> str:
    if isinstance(e, requests.RequestException):
        return f"Network error: {e}"
    return str(e)


def sample_items(
    layer: str,
    field: str,
    value,
    count: int,
    render: Callable[[dict, str, int], Path | list[Path]],
    exclude_ids: Iterable[int] = (),
) -> dict:
    """Pick `count` random items with field == value and render one image per item.

    render(feature, label, index) -> image path or list of paths. Items that fail (no geometry,
    no orthophoto coverage, ...) are replaced by other random items, up to
    3 × count attempts. OBJECTIDs in exclude_ids are never picked.
    Returns {"total_matches", "images": [{"image_path", "label", "attributes"}], "failed"}.
    """
    check_field(layer, field)
    count = max(1, min(int(count), MAX_COUNT))
    layer_url = LAYER_URLS[layer]

    ids = object_ids(layer_url, where_for(field, value))
    excluded = set(exclude_ids)
    candidates = [i for i in ids if i not in excluded]
    random.shuffle(candidates)
    candidates = candidates[: 3 * count]

    images, failed = [], []
    items_done = 0  # count is the number of items, even if one item gives several images
    position = 0
    while items_done < count and position < len(candidates):
        batch = candidates[position: position + (count - items_done)]
        position += len(batch)
        for feature in query_by_object_ids(layer_url, batch, out_sr=SPATIAL_REF):
            label = item_label(layer, feature)
            if not (feature.get("geometry") or {}):
                failed.append({"id": label, "error": "No geometry"})
                continue
            try:
                rendered = render(feature, label, len(images) + 1)
            except (requests.RequestException, RuntimeError, ValueError) as e:
                failed.append({"id": label, "error": _error_text(e)})
                continue
            # render may return one image or several (e.g. tiles of a large contract)
            paths = rendered if isinstance(rendered, list) else [rendered]
            for n, image_path in enumerate(paths, start=1):
                images.append({
                    "image_path": image_path,
                    "label": label if len(paths) == 1 else f"{label} ({n}/{len(paths)})",
                    "attributes": feature.get("attributes", {}),
                })
            items_done += 1

    return {"total_matches": len(ids), "images": images, "failed": failed}


def sample_images(layer: str, field: str, value, count: int = DEFAULT_COUNT) -> dict:
    """Images of `count` random items whose field equals value, one image per item,
    with the item's outline and label drawn (contracts red, plots blue)."""
    run = f"sample_{layer}_{datetime.now():%Y%m%d-%H%M%S}_{uuid.uuid4().hex[:6]}"

    def render(feature: dict, label: str, index: int) -> Path:
        item = {"kind": KIND[layer], "request": label, "feature": feature}
        return make_group_image([item], f"{run}_{index}")["image_path"]

    return sample_items(layer, field, value, count, render)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Random images by category value")
    parser.add_argument("layer", choices=CATEGORY_FIELDS)
    parser.add_argument("field")
    parser.add_argument("value")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    args = parser.parse_args()

    result = sample_images(args.layer, args.field, args.value, args.count)
    print(f"{result['total_matches']} matching items")
    for image in result["images"]:
        print(f"  {image['label']}: {image['image_path']}")
    for f in result["failed"]:
        print(f"  FAILED {f['id']}: {f['error']}")


if __name__ == "__main__":
    main()
