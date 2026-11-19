"""
Merge: contract ID -> contract geometry -> orthophoto image of that area.

1. contract_query.py  : get the contract's features + geometry (EPSG:2039)
2. orthophoto.py      : download the orthophoto for the contract's extent
3. draw_outline.py    : draw the contract polygon on the image in red

Install:  uv add requests truststore pillow
Run:      uv run contract_orthophoto.py
"""

import json
from pathlib import Path

import requests

from contract_query import query_by_contract_id
from draw_outline import draw_contract_outline
from orthophoto import SPATIAL_REF, BBox, export_image, query_footprints

BUFFER_METERS = 20  # margin around the contract area
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"  # itay-test/output


def geometry_points(geometry: dict) -> list[list[float]]:
    """Flatten any ArcGIS geometry (polygon / polyline / point / multipoint) to points."""
    if "rings" in geometry:
        return [pt for ring in geometry["rings"] for pt in ring]
    if "paths" in geometry:
        return [pt for path in geometry["paths"] for pt in path]
    if "points" in geometry:
        return geometry["points"]
    if "x" in geometry and "y" in geometry:
        return [[geometry["x"], geometry["y"]]]
    return []


def features_bbox(features: list[dict], buffer: float = BUFFER_METERS) -> BBox:
    """Bounding box of all features' geometries, with a buffer in meters."""
    points = [
        pt for f in features for pt in geometry_points(f.get("geometry") or {})
    ]
    if not points:
        raise ValueError("The contract features have no geometry.")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (
        min(xs) - buffer,
        min(ys) - buffer,
        max(xs) + buffer,
        max(ys) + buffer,
    )


def make_square(bbox: BBox) -> BBox:
    """Expand the shorter side of the bbox so all sides are equal, keeping the same center."""
    xmin, ymin, xmax, ymax = bbox
    side = max(xmax - xmin, ymax - ymin)
    cx = (xmin + xmax) / 2
    cy = (ymin + ymax) / 2
    half = side / 2
    return (cx - half, cy - half, cx + half, cy + half)


def save_attributes(features: list[dict], path: Path) -> None:
    """Save the contract attributes as JSON (Hebrew kept readable)."""
    attrs = [f.get("attributes", {}) for f in features]
    path.write_text(json.dumps(attrs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {path}")


def get_contract_orthophoto(contract_id, image_format: str = "png24") -> Path:
    """Full pipeline for one contract ID. Returns the image path.

    image_format: "png24" (full-colour PNG, default), "jpg", or "tiff" (GeoTIFF).
    """
    features = query_by_contract_id(
        contract_id, return_geometry=True, out_sr=SPATIAL_REF
    )
    if not features:
        raise ValueError(f"No contract found with ID {contract_id}")
    print(f"Found {len(features)} feature(s) for contract {contract_id}")

    bbox = make_square(features_bbox(features))
    print(f"Contract extent (EPSG:{SPATIAL_REF}): {bbox}")

    tiles = query_footprints(bbox)
    if not tiles:
        raise ValueError("No orthophoto coverage for this contract area.")
    print(f"{len(tiles)} orthophoto tile(s) cover the area")

    OUTPUT_DIR.mkdir(exist_ok=True)
    save_attributes(features, OUTPUT_DIR / f"contract_{contract_id}.json")
    if image_format == "tiff":
        ext = "tif"
    elif image_format.startswith("png"):
        ext = "png"
    else:
        ext = image_format
    image_path = export_image(
        bbox, OUTPUT_DIR / f"contract_{contract_id}.{ext}", image_format
    )

    # Drawing would drop the GeoTIFF's location data, so only PNG / JPG get the outline
    if ext != "tif":
        draw_contract_outline(image_path, features, bbox, label=str(contract_id))
    return image_path


def get_many_contract_orthophotos(
    contract_ids: list, image_format: str = "png24"
) -> dict:
    """Run the pipeline for each contract ID.

    One failing contract does not stop the others.
    Returns {"ok": {contract_id: image_path}, "failed": {contract_id: error}}.
    """
    ok, failed = {}, {}
    for i, contract_id in enumerate(contract_ids, start=1):
        print(f"\n=== [{i}/{len(contract_ids)}] Contract {contract_id} ===")
        try:
            ok[contract_id] = get_contract_orthophoto(contract_id, image_format)
        except requests.RequestException as e:
            failed[contract_id] = f"Network error: {e}"
        except (RuntimeError, ValueError) as e:
            failed[contract_id] = str(e)
        if contract_id in failed:
            print(f"FAILED: {failed[contract_id]}")
    return {"ok": ok, "failed": failed}


def parse_contract_ids(text: str) -> list[str]:
    """Split '111, 222 333' into ['111', '222', '333'], dropping duplicates."""
    ids = text.replace(",", " ").split()
    return list(dict.fromkeys(ids))


def print_summary(results: dict) -> None:
    """Print which contracts succeeded and which failed."""
    print("\n=== Summary ===")
    print(f"Succeeded: {len(results['ok'])}")
    for contract_id, path in results["ok"].items():
        print(f"  {contract_id}: {path}")
    print(f"Failed: {len(results['failed'])}")
    for contract_id, error in results["failed"].items():
        print(f"  {contract_id}: {error}")


def main() -> None:
    text = input("Enter contract IDs (separated by commas or spaces): ")
    contract_ids = parse_contract_ids(text)
    if not contract_ids:
        print("No contract IDs entered.")
        return
    results = get_many_contract_orthophotos(contract_ids)
    print_summary(results)


if __name__ == "__main__":
    main()
