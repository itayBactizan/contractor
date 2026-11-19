"""
Combined image: contracts (red) and plots (blue) on the same orthophoto.

Contracts and plots have no shared field (many-to-many), so they are combined
by location only. Items close to each other share one image; items far from the
rest get their own image, so no image has to cover a huge area at low detail.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

import requests

from contract_orthophoto import (
    BUFFER_METERS,
    OUTPUT_DIR,
    features_bbox,
    geometry_points,
    make_square,
)
from contract_query import query_by_contract_id
from draw_outline import LINE_COLOR, PLOT_COLOR, draw_outlines
from orthophoto import SPATIAL_REF, BBox, export_image, query_footprints
from plot_query import plot_label, query_plots

# Largest square side (metres) for one image. Items that don't fit together
# go to another image. 1500 m at 0.2 m/pixel = 7500 px, still sharp after the
# server's size limit.
MAX_SIDE_METERS = 1500


def _error_text(e: Exception) -> str:
    if isinstance(e, requests.RequestException):
        return f"Network error: {e}"
    return str(e)


def collect_items(contract_ids: list[str], plots: list[dict]) -> tuple[list[dict], list[dict]]:
    """Query every contract and plot. One item per feature found.

    Returns (items, failed). Each item: {"kind", "request", "feature"}.
    """
    items, failed = [], []

    for cid in dict.fromkeys(contract_ids):
        try:
            features = query_by_contract_id(cid, return_geometry=True, out_sr=SPATIAL_REF)
            if not features:
                raise ValueError(f"No contract found with ID {cid}")
            items += [{"kind": "contract", "request": cid, "feature": f} for f in features]
        except (requests.RequestException, RuntimeError, ValueError) as e:
            failed.append({"type": "contract", "id": cid, "error": _error_text(e)})

    unique_plots = {(p.get("tochnit") or "", p["migrash"]): p for p in plots}.values()
    for plot in unique_plots:
        label = plot_label(plot)
        try:
            features = query_plots(plot["migrash"], plot.get("tochnit"))
            if not features:
                raise ValueError(f"No plot found: {label}")
            items += [{"kind": "plot", "request": label, "feature": f} for f in features]
        except (requests.RequestException, RuntimeError, ValueError) as e:
            failed.append({"type": "plot", "id": label, "error": _error_text(e)})

    # A feature without geometry can't be placed on the map
    return [i for i in items if geometry_points(i["feature"].get("geometry") or {})], failed


def _merge(a: BBox, b: BBox) -> BBox:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _side(b: BBox) -> float:
    return max(b[2] - b[0], b[3] - b[1])


def group_by_distance(items: list[dict], max_side: float = MAX_SIDE_METERS) -> list[list[dict]]:
    """Put items into groups whose combined square (with buffer) fits in max_side."""
    for item in items:
        item["bbox"] = features_bbox([item["feature"]], buffer=0)
    # Sort west to east so neighbours are usually met one after another
    ordered = sorted(items, key=lambda i: (i["bbox"][0], i["bbox"][1]))

    groups = []  # each: {"bbox": BBox, "items": [...]}
    for item in ordered:
        for group in groups:
            merged = _merge(group["bbox"], item["bbox"])
            if _side(merged) + 2 * BUFFER_METERS <= max_side:
                group["bbox"] = merged
                group["items"].append(item)
                break
        else:
            groups.append({"bbox": item["bbox"], "items": [item]})
    return [g["items"] for g in groups]


def _plot_label_for(feature: dict) -> str:
    return str((feature.get("attributes") or {}).get("MIGRASH", ""))


def make_group_image(group: list[dict], name: str) -> dict:
    """Download and draw one image for a group of nearby items."""
    contracts = [i for i in group if i["kind"] == "contract"]
    plots = [i for i in group if i["kind"] == "plot"]

    bbox = make_square(features_bbox([i["feature"] for i in group]))
    if not query_footprints(bbox):
        raise ValueError("No orthophoto coverage for this area.")

    OUTPUT_DIR.mkdir(exist_ok=True)
    image_path = export_image(bbox, OUTPUT_DIR / f"{name}.png", "png24")

    # Plots first, contracts on top
    contract_label = {id(i["feature"]): i["request"] for i in contracts}
    draw_outlines(
        image_path,
        [
            {"features": [i["feature"] for i in plots], "color": PLOT_COLOR,
             "label_for": _plot_label_for},
            {"features": [i["feature"] for i in contracts], "color": LINE_COLOR,
             "label_for": lambda f: contract_label[id(f)]},
        ],
        bbox,
    )

    attributes = {
        "contracts": [i["feature"].get("attributes", {}) for i in contracts],
        "plots": [i["feature"].get("attributes", {}) for i in plots],
    }
    (OUTPUT_DIR / f"{name}.json").write_text(
        json.dumps(attributes, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    return {
        "image_path": image_path,
        "contracts": list(dict.fromkeys(i["request"] for i in contracts)),
        "plots": list(dict.fromkeys(i["request"] for i in plots)),
    }


def get_combined_orthophotos(contract_ids: list[str], plots: list[dict]) -> dict:
    """Full pipeline. plots: [{"migrash": "12", "tochnit": "101-0123456" or None}, ...]

    Returns {"images": [{"image_path", "contracts", "plots"}], "failed": [...]}.
    """
    items, failed = collect_items(contract_ids, plots)
    if not items:
        return {"images": [], "failed": failed}

    run = f"combined_{datetime.now():%Y%m%d-%H%M%S}_{uuid.uuid4().hex[:6]}"
    images = []
    groups = group_by_distance(items)
    for n, group in enumerate(groups, start=1):
        name = run if len(groups) == 1 else f"{run}_{n}"
        try:
            images.append(make_group_image(group, name))
        except (requests.RequestException, RuntimeError, ValueError) as e:
            for request in dict.fromkeys((i["kind"], i["request"]) for i in group):
                failed.append({"type": request[0], "id": request[1], "error": _error_text(e)})

    return {"images": images, "failed": failed}


def main() -> None:
    contracts = input("Contract IDs (comma separated, optional): ").replace(",", " ").split()
    migrashim = input("Plot numbers MIGRASH (comma separated, optional): ").replace(",", " ").split()
    tochnit = input("Plan TOCHNIT for these plots (optional): ").strip() or None
    result = get_combined_orthophotos(
        contracts, [{"migrash": m, "tochnit": tochnit} for m in migrashim]
    )
    for image in result["images"]:
        print(f"Image: {image['image_path']}  contracts={image['contracts']}  plots={image['plots']}")
    for f in result["failed"]:
        print(f"FAILED {f['type']} {f['id']}: {f['error']}")


if __name__ == "__main__":
    main()
