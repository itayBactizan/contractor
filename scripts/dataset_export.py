"""
Dataset images for YOLO: one contract per image, 1024×1024, everything outside
the contract polygon black, no outlines or labels drawn.

Each image gets a metadata JSON (bbox in EPSG:2039, metres per pixel, the
contract polygon, attributes) so boxes/labels can be computed later.

Layout:
    dataset/images/<contractId>_<OBJECTID>.png
    dataset/meta/<contractId>_<OBJECTID>.json
    dataset/metadata.csv            one row per image

CLI:
    uv run scripts/dataset_export.py "מסחר ושרותים אחרים" --count 5
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from category_sample import DEFAULT_COUNT, sample_items
from contract_orthophoto import features_bbox, make_square
from draw_outline import world_to_pixel
from orthophoto import OUTPUT_SIZE, SPATIAL_REF, BBox, export_image, query_footprints

DATASET_DIR = Path(__file__).resolve().parent.parent / "dataset"
IMAGES_DIR = DATASET_DIR / "images"
META_DIR = DATASET_DIR / "meta"
METADATA_CSV = DATASET_DIR / "metadata.csv"

FIELD = "MataraDesc"
# Margin around the contract, as a share of its size: the contract nearly fills the image
MARGIN_RATIO = 0.03
CSV_COLUMNS = [
    "file", "contract_id", "objectid", FIELD,
    "xmin", "ymin", "xmax", "ymax", "epsg", "size_px", "meters_per_pixel",
]

SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")


def contract_bbox(feature: dict) -> BBox:
    """Square around the contract with a small relative margin."""
    xmin, ymin, xmax, ymax = features_bbox([feature], buffer=0)
    margin = MARGIN_RATIO * max(xmax - xmin, ymax - ymin)
    return make_square((xmin - margin, ymin - margin, xmax + margin, ymax + margin))


def _signed_area(ring: list) -> float:
    """Shoelace formula: > 0 counter-clockwise, < 0 clockwise (map coordinates)."""
    return sum(x1 * y2 - x2 * y1 for (x1, y1, *_), (x2, y2, *_) in zip(ring, ring[1:] + ring[:1])) / 2


def mask_outside(image_path: Path, geometry: dict, bbox: BBox) -> None:
    """Paint everything outside the polygon black (in place). Holes stay black too.

    ArcGIS polygons: exterior rings are clockwise, holes counter-clockwise.
    """
    img = Image.open(image_path).convert("RGB")
    mask = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(mask)

    rings = geometry.get("rings") or []
    exteriors = [r for r in rings if _signed_area(r) <= 0]
    holes = [r for r in rings if _signed_area(r) > 0]
    if not exteriors:  # unusual orientation: treat every ring as an exterior
        exteriors, holes = rings, []

    for value, group in ((255, exteriors), (0, holes)):
        for ring in group:
            pixels = [world_to_pixel(x, y, bbox, img.size) for x, y, *_ in ring]
            if len(pixels) >= 3:
                draw.polygon(pixels, fill=value)

    black = Image.new("RGB", img.size, (0, 0, 0))
    Image.composite(img, black, mask).save(image_path)


def already_saved_object_ids() -> set[int]:
    """OBJECTIDs already in the dataset, so they are not picked again."""
    if not METADATA_CSV.exists():
        return set()
    with open(METADATA_CSV, encoding="utf-8-sig", newline="") as f:
        return {int(row["objectid"]) for row in csv.DictReader(f) if row.get("objectid")}


def dataset_size() -> int:
    return len(list(IMAGES_DIR.glob("*.png"))) if IMAGES_DIR.exists() else 0


def _append_csv(row: dict) -> None:
    new_file = not METADATA_CSV.exists()
    # utf-8-sig so Hebrew opens correctly in Excel
    with open(METADATA_CSV, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def make_dataset_image(feature: dict, label: str, index: int = 0) -> Path:
    """Download, mask and save one contract image + its metadata. Returns the image path."""
    geometry = feature.get("geometry") or {}
    if not geometry.get("rings"):
        raise ValueError("Contract has no polygon")

    bbox = contract_bbox(feature)
    if not query_footprints(bbox):
        raise ValueError("No orthophoto coverage for this area.")

    attrs = feature.get("attributes") or {}
    objectid = attrs.get("OBJECTID")
    name = f"{SAFE_NAME.sub('', str(label))}_{objectid}"

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)
    image_path = export_image(bbox, IMAGES_DIR / f"{name}.png", "png24")
    mask_outside(image_path, geometry, bbox)

    size_px = Image.open(image_path).size[0]
    meters_per_pixel = (bbox[2] - bbox[0]) / size_px
    meta = {
        "file": image_path.name,
        "contract_id": label,
        "objectid": objectid,
        FIELD: attrs.get(FIELD),
        "bbox": {"xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3]},
        "epsg": SPATIAL_REF,
        "size_px": size_px,
        "meters_per_pixel": meters_per_pixel,
        "geometry": geometry,
        "attributes": attrs,
    }
    (META_DIR / f"{name}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    _append_csv({
        "file": image_path.name, "contract_id": label, "objectid": objectid, FIELD: attrs.get(FIELD),
        "xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3],
        "epsg": SPATIAL_REF, "size_px": size_px, "meters_per_pixel": round(meters_per_pixel, 4),
    })
    return image_path


def sample_dataset_images(value, count: int = DEFAULT_COUNT) -> dict:
    """`count` random contracts with MataraDesc == value that are not in the dataset yet."""
    result = sample_items(
        "contracts", FIELD, value, count,
        render=make_dataset_image,
        exclude_ids=already_saved_object_ids(),
    )
    result["dataset_size"] = dataset_size()
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=f"Add random contracts by {FIELD} to the YOLO dataset")
    parser.add_argument("value", help=f"{FIELD} value")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    args = parser.parse_args()

    result = sample_dataset_images(args.value, args.count)
    print(f"{result['total_matches']} matching contracts; dataset now has {result['dataset_size']} images")
    for image in result["images"]:
        print(f"  {image['label']}: {image['image_path']}")
    for f in result["failed"]:
        print(f"  SKIPPED {f['id']}: {f['error']}")


if __name__ == "__main__":
    main()
