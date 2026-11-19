"""
Dataset images for YOLO: contracts at a fixed real scale (the orthophoto's
native 0.2 m/pixel), 1024×1024 per image, everything outside the contract
polygon black, no outlines or labels drawn.

- A small contract is enlarged to fill ~90% of the image, but never more than
  MAX_ZOOM× (4× = 0.05 m/pixel): the area is downloaded at full detail and
  enlarged locally with high-quality (Lanczos) resampling. Very small
  contracts keep some black border.
- A contract larger than 204.8 m (1024 px × 0.2 m) is split into a grid of
  full-detail 1024×1024 tiles; tiles that hold (almost) none of the contract
  are skipped.

Each image gets a metadata JSON (bbox in EPSG:2039, metres per pixel, the
contract polygon, attributes) so boxes/labels can be computed later.

Layout:
    dataset/images/<contractId>_<OBJECTID>[_r<row>c<col>].png
    dataset/meta/<same name>.json
    dataset/metadata.csv            one row per image

CLI:
    uv run scripts/dataset_export.py "מסחר ושרותים אחרים" --count 5
"""

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from category_sample import DEFAULT_COUNT, sample_items
from contract_orthophoto import features_bbox
from draw_outline import world_to_pixel
from orthophoto import OUTPUT_SIZE, PIXEL_SIZE, SPATIAL_REF, BBox, export_image, query_footprints

DATASET_DIR = Path(__file__).resolve().parent.parent / "dataset"
IMAGES_DIR = DATASET_DIR / "images"
META_DIR = DATASET_DIR / "meta"
METADATA_CSV = DATASET_DIR / "metadata.csv"

FIELD = "MataraDesc"
# One image covers this many metres at the native resolution: 1024 × 0.2 = 204.8 m
TILE_METERS = OUTPUT_SIZE * PIXEL_SIZE
# Small contracts: border around the contract (share of its size on each side) -> fills ~90%
MARGIN_RATIO = 0.05
# Small contracts are enlarged at most this much (4× = 0.05 m/pixel)
MAX_ZOOM = 4
# Skip tiles where less than this share of the pixels is inside the contract
MIN_TILE_FILL = 0.01
# Contracts needing more tiles than this (~1 km across) are skipped
MAX_TILES_PER_CONTRACT = 25

CSV_COLUMNS = [
    "file", "contract_id", "objectid", FIELD,
    "tile_row", "tile_col", "tiles_total", "contract_fill", "zoom",
    "xmin", "ymin", "xmax", "ymax", "epsg", "size_px", "meters_per_pixel",
]

SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]")


def contract_tiles(feature: dict) -> list[tuple[int, int, BBox, int]]:
    """Square image area(s) for the contract: [(row, col, bbox, download_px)].

    Small contract: one square, the contract filling ~90% of it (at most
    MAX_ZOOM× enlarged), downloaded at full detail (download_px < 1024) and
    enlarged afterwards. Large contract: a grid of TILE_METERS squares centered
    on it, each downloaded at 1024 px. Row 0 = north (top), col 0 = west (left).
    """
    xmin, ymin, xmax, ymax = features_bbox([feature], buffer=0)
    extent = max(xmax - xmin, ymax - ymin)
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2

    side = max(extent * (1 + 2 * MARGIN_RATIO), TILE_METERS / MAX_ZOOM)
    if side < TILE_METERS:
        half = side / 2
        native_px = max(1, math.ceil(side / PIXEL_SIZE))
        return [(0, 0, (cx - half, cy - half, cx + half, cy + half), native_px)]

    n_cols = max(1, math.ceil((xmax - xmin) / TILE_METERS))
    n_rows = max(1, math.ceil((ymax - ymin) / TILE_METERS))
    if n_cols * n_rows > MAX_TILES_PER_CONTRACT:
        raise ValueError(
            f"Contract too large: {n_cols}×{n_rows} tiles (max {MAX_TILES_PER_CONTRACT})"
        )

    # Center the grid on the contract
    grid_left = cx - n_cols * TILE_METERS / 2
    grid_top = cy + n_rows * TILE_METERS / 2

    tiles = []
    for row in range(n_rows):
        for col in range(n_cols):
            x0 = grid_left + col * TILE_METERS
            y1 = grid_top - row * TILE_METERS
            tiles.append((row, col, (x0, y1 - TILE_METERS, x0 + TILE_METERS, y1), OUTPUT_SIZE))
    return tiles


def _signed_area(ring: list) -> float:
    """Shoelace formula: > 0 counter-clockwise, < 0 clockwise (map coordinates)."""
    return sum(x1 * y2 - x2 * y1 for (x1, y1, *_), (x2, y2, *_) in zip(ring, ring[1:] + ring[:1])) / 2


def polygon_mask(geometry: dict, bbox: BBox, size: tuple[int, int]) -> Image.Image:
    """Mask image ("L"): 255 inside the polygon, 0 outside and in holes.

    ArcGIS polygons: exterior rings are clockwise, holes counter-clockwise.
    """
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)

    rings = geometry.get("rings") or []
    exteriors = [r for r in rings if _signed_area(r) <= 0]
    holes = [r for r in rings if _signed_area(r) > 0]
    if not exteriors:  # unusual orientation: treat every ring as an exterior
        exteriors, holes = rings, []

    for value, group in ((255, exteriors), (0, holes)):
        for ring in group:
            pixels = [world_to_pixel(x, y, bbox, size) for x, y, *_ in ring]
            if len(pixels) >= 3:
                draw.polygon(pixels, fill=value)
    return mask


def mask_fill(mask: Image.Image) -> float:
    """Share of the pixels inside the polygon (0..1)."""
    return mask.histogram()[255] / (mask.size[0] * mask.size[1])


def apply_mask(image_path: Path, mask: Image.Image) -> None:
    """Enlarge the image to the mask size if needed (Lanczos), then paint
    everything outside the mask black (in place)."""
    img = Image.open(image_path).convert("RGB")
    if img.size != mask.size:
        img = img.resize(mask.size, Image.Resampling.LANCZOS)
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


def make_dataset_images(feature: dict, label: str, index: int = 0) -> list[Path]:
    """Download, mask and save the image(s) of one contract + metadata. Returns the image paths."""
    geometry = feature.get("geometry") or {}
    if not geometry.get("rings"):
        raise ValueError("Contract has no polygon")

    attrs = feature.get("attributes") or {}
    objectid = attrs.get("OBJECTID")
    base_name = f"{SAFE_NAME.sub('', str(label))}_{objectid}"
    size = (OUTPUT_SIZE, OUTPUT_SIZE)

    # Decide which tiles to keep before downloading anything
    tiles = []
    for row, col, bbox, download_px in contract_tiles(feature):
        mask = polygon_mask(geometry, bbox, size)
        fill = mask_fill(mask)
        if fill >= MIN_TILE_FILL:
            tiles.append((row, col, bbox, download_px, mask, fill))
    if not tiles:
        raise ValueError("Contract is too small to show")

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    META_DIR.mkdir(parents=True, exist_ok=True)

    paths = []
    for row, col, bbox, download_px, mask, fill in tiles:
        if not query_footprints(bbox):
            continue  # this part of the contract has no orthophoto
        name = base_name if len(tiles) == 1 else f"{base_name}_r{row}c{col}"
        # Download at full detail (download_px), then enlarge to 1024 and mask
        image_path = export_image(bbox, IMAGES_DIR / f"{name}.png", "png24", size_px=download_px)
        apply_mask(image_path, mask)

        size_px = Image.open(image_path).size[0]
        meters_per_pixel = (bbox[2] - bbox[0]) / size_px
        common = {
            "file": image_path.name,
            "contract_id": label,
            "objectid": objectid,
            FIELD: attrs.get(FIELD),
            "tile_row": row,
            "tile_col": col,
            "tiles_total": len(tiles),
            "contract_fill": round(fill, 4),
            "zoom": round(PIXEL_SIZE / meters_per_pixel, 2),
            "epsg": SPATIAL_REF,
            "size_px": size_px,
            "meters_per_pixel": round(meters_per_pixel, 4),
        }
        meta = {
            **common,
            "bbox": {"xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3]},
            "geometry": geometry,
            "attributes": attrs,
        }
        (META_DIR / f"{name}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        _append_csv({**common, "xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[2], "ymax": bbox[3]})
        paths.append(image_path)

    if not paths:
        raise ValueError("No orthophoto coverage for this area.")
    return paths


def sample_dataset_images(value, count: int = DEFAULT_COUNT) -> dict:
    """`count` random contracts with MataraDesc == value that are not in the dataset yet."""
    result = sample_items(
        "contracts", FIELD, value, count,
        render=make_dataset_images,
        exclude_ids=already_saved_object_ids(),
    )
    result["contracts_added"] = len({img["attributes"].get("OBJECTID") for img in result["images"]})
    result["dataset_size"] = dataset_size()
    return result


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=f"Add random contracts by {FIELD} to the YOLO dataset")
    parser.add_argument("value", help=f"{FIELD} value")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    args = parser.parse_args()

    result = sample_dataset_images(args.value, args.count)
    print(
        f"{result['total_matches']} matching contracts; added {result['contracts_added']} contracts "
        f"({len(result['images'])} images); dataset now has {result['dataset_size']} images"
    )
    for image in result["images"]:
        print(f"  {image['label']}: {image['image_path']}")
    for f in result["failed"]:
        print(f"  SKIPPED {f['id']}: {f['error']}")


if __name__ == "__main__":
    main()
