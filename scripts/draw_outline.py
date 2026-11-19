"""
Draw outlines on orthophoto images: contracts in red, plots in blue.

The contract geometry is in map coordinates (EPSG:2039, metres) and the image
covers a known bbox, so each map point is converted to an image pixel.

Install:  uv add pillow
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from arcgis_utils import BBox

LINE_COLOR = (255, 0, 0)  # red: contracts
PLOT_COLOR = (0, 112, 255)  # blue: plots


def world_to_pixel(
    x: float, y: float, bbox: BBox, image_size: tuple[int, int]
) -> tuple[float, float]:
    """Map coordinates (metres) -> image pixel (column, row).

    Image rows grow downward while map Y grows upward, so Y is flipped.
    """
    xmin, ymin, xmax, ymax = bbox
    width, height = image_size
    px = (x - xmin) / (xmax - xmin) * width
    py = (ymax - y) / (ymax - ymin) * height
    return px, py


def geometry_lines(geometry: dict) -> list[list[list[float]]]:
    """Polygon rings / polyline paths as lists of [x, y] points."""
    if "rings" in geometry:
        return geometry["rings"]
    if "paths" in geometry:
        return geometry["paths"]
    return []


def geometry_dots(geometry: dict) -> list[list[float]]:
    """Point / multipoint geometry as a list of [x, y] points."""
    if "points" in geometry:
        return geometry["points"]
    if "x" in geometry and "y" in geometry:
        return [[geometry["x"], geometry["y"]]]
    return []


def _label_position(pixels: list[tuple[float, float]]) -> tuple[float, float]:
    """Middle of the shape's bounding box, for its label."""
    xs = [p[0] for p in pixels]
    ys = [p[1] for p in pixels]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2


def _draw_features(draw, features, bbox, image_size, color, line_width, font, label_for):
    """Draw each feature's outline in `color`, with its own label in the middle."""
    for feature in features:
        geometry = feature.get("geometry") or {}
        pixels = []
        for line in geometry_lines(geometry):
            points = [world_to_pixel(x, y, bbox, image_size) for x, y, *_ in line]
            draw.line(points, fill=color, width=line_width, joint="curve")
            pixels.extend(points)
        for x, y, *_ in geometry_dots(geometry):
            px, py = world_to_pixel(x, y, bbox, image_size)
            r = line_width * 3
            draw.ellipse((px - r, py - r, px + r, py + r), outline=color, width=line_width)
            pixels.append((px, py))

        label = label_for(feature) if label_for else None
        if label and pixels:
            draw.text(
                _label_position(pixels), str(label), fill=color, font=font, anchor="mm",
                stroke_width=max(1, line_width // 2), stroke_fill="white",
            )


def draw_outlines(image_path: str | Path, layers: list[dict], bbox: BBox) -> Path:
    """Draw several groups of features on the image (in place), one color per group.

    layers: [{"features": [...], "color": (r, g, b), "label_for": feature -> str}, ...]
    Groups are drawn in order, so the last group ends up on top.
    """
    image_path = Path(image_path)
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Line width and text size scale with the image, so they stay visible
    line_width = max(2, round(min(img.size) / 300))
    font = ImageFont.load_default(size=max(12, round(min(img.size) / 40)))

    for layer in layers:
        _draw_features(
            draw, layer["features"], bbox, img.size,
            layer["color"], line_width, font, layer.get("label_for"),
        )

    img.save(image_path)
    print(f"Drew outlines on {image_path}")
    return image_path


def draw_contract_outline(
    image_path: str | Path,
    features: list[dict],
    bbox: BBox,
    label: str | None = None,
    color: tuple[int, int, int] = LINE_COLOR,
) -> Path:
    """Draw one contract's features in red (used by the per-contract flow)."""
    return draw_outlines(
        image_path,
        [{"features": features, "color": color, "label_for": lambda f: label}],
        bbox,
    )
