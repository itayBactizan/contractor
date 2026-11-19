"""
Download orthophoto images from the OrtophotoArtzi_2025 ImageServer by extent.

The ImageServer has no contract ID field, so it is searched by location
(a bounding box in Israel TM Grid, EPSG:2039), not by contract ID.

Install:  uv add requests truststore
Run:      uv run orthophoto.py
"""

from pathlib import Path

import requests

from arcgis_utils import SR, BBox, get_json, query_layer

IMAGE_SERVER_URL = (
    "https://arcgisserverprod.mami.gov.il/arcgis/rest/services/"
    "OrtoPhoto/OrtophotoArtzi_2025/ImageServer"
)
SPATIAL_REF = SR  # Israel TM Grid, the service's native spatial reference
PIXEL_SIZE = 0.2    # meters per pixel (native resolution)
OUTPUT_SIZE = 1024  # output image width and height in pixels
TIMEOUT = 120


def get_service_info(url: str = IMAGE_SERVER_URL) -> dict:
    """Return service metadata (extent, pixel size, max image size, ...)."""
    return get_json(url)


def query_footprints(bbox: BBox, url: str = IMAGE_SERVER_URL) -> list[dict]:
    """Return catalog items (image tiles) whose footprint intersects the bbox."""
    features = query_layer(
        url,
        box=bbox,
        out_fields="OBJECTID,Name,Tag,GroupName,ProductName,Category,MinPS,MaxPS",
        return_geometry=False,
    )
    return [f["attributes"] for f in features]


def compute_image_size(
    bbox: BBox, pixel_size: float, max_width: int, max_height: int
) -> tuple[int, int]:
    """Image size in pixels for the bbox, scaled down to fit the server limits."""
    xmin, ymin, xmax, ymax = bbox
    width = max(1, round((xmax - xmin) / pixel_size))
    height = max(1, round((ymax - ymin) / pixel_size))
    scale = min(1.0, max_width / width, max_height / height)
    return max(1, int(width * scale)), max(1, int(height * scale))


def export_image(
    bbox: BBox,
    output_path: str | Path,
    image_format: str = "tiff",
    url: str = IMAGE_SERVER_URL,
) -> Path:
    """
    Download the orthophoto for the bbox and save it to output_path.

    image_format: "tiff" (GeoTIFF, georeferenced, for GIS), "jpg" or "png".
    The longer side is OUTPUT_SIZE pixels (1024×1024 for the square areas the app uses).
    """
    xmin, ymin, xmax, ymax = bbox
    # Keep the area's proportions: the longer side gets OUTPUT_SIZE pixels
    w, h = xmax - xmin, ymax - ymin
    scale = OUTPUT_SIZE / max(w, h)
    width, height = max(1, round(w * scale)), max(1, round(h * scale))

    params = {
        "bbox": f"{xmin},{ymin},{xmax},{ymax}",
        "bboxSR": SPATIAL_REF,
        "imageSR": SPATIAL_REF,
        "size": f"{width},{height}",
        "format": image_format,
        "f": "image",  # return the image bytes directly
    }
    resp = requests.get(f"{url}/exportImage", params=params, timeout=TIMEOUT)
    resp.raise_for_status()

    # On errors the server returns JSON instead of an image
    if "json" in resp.headers.get("Content-Type", "") or resp.content[:1] == b"{":
        raise RuntimeError(f"ArcGIS error: {resp.text[:500]}")

    output_path = Path(output_path)
    output_path.write_bytes(resp.content)
    print(f"Saved {output_path} ({width}x{height} px, {len(resp.content):,} bytes)")
    return output_path


def main() -> None:
    # Example: a 200m x 200m area (Israel TM Grid coordinates)
    raw = input("Enter bbox xmin,ymin,xmax,ymax (EPSG:2039): ").strip()
    try:
        bbox = tuple(float(v) for v in raw.split(","))
        if len(bbox) != 4:
            raise ValueError
    except ValueError:
        print("Invalid bbox. Example: 178000,663000,178200,663200")
        return

    try:
        tiles = query_footprints(bbox)
        print(f"{len(tiles)} image tile(s) cover this area")
        export_image(bbox, "orthophoto.tif")
    except (requests.RequestException, RuntimeError) as e:
        print(e)


if __name__ == "__main__":
    main()
