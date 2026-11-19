"""
Web API for the React UI: contract IDs in, orthophoto image URLs out.

Install:  uv add fastapi "uvicorn[standard]"
Run (from the project root):
          uv run uvicorn api:app --reload --app-dir scripts
"""

import re

import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from category_sample import CATEGORY_FIELDS, MAX_COUNT, category_options, sample_images
from combined_orthophoto import get_combined_orthophotos
from contract_orthophoto import OUTPUT_DIR, get_many_contract_orthophotos
from dataset_export import DATASET_DIR, sample_dataset_images

# Contract IDs become part of file names, so allow only safe characters
CONTRACT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
# Plot fields are only used inside quoted SQL values (not file names); just limit length
MAX_MIGRASH_LENGTH = 10
MAX_TOCHNIT_LENGTH = 25

OUTPUT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Contract Orthophoto API")

# Serve the generated images: /images/contract_<id>.png -> output/contract_<id>.png
app.mount("/images", StaticFiles(directory=OUTPUT_DIR), name="images")
# Dataset images for YOLO: /dataset/images/<name>.png -> dataset/images/<name>.png
DATASET_DIR.mkdir(exist_ok=True)
app.mount("/dataset", StaticFiles(directory=DATASET_DIR), name="dataset")


class OrthophotoRequest(BaseModel):
    contract_ids: list[str]


class Plot(BaseModel):
    migrash: str
    tochnit: str | None = None


class CombinedRequest(BaseModel):
    contract_ids: list[str] = []
    plots: list[Plot] = []


class SampleRequest(BaseModel):
    layer: str
    field: str
    value: str | None = Field(default=None, max_length=200)
    count: int = Field(default=5, ge=1, le=MAX_COUNT)


class DatasetSampleRequest(BaseModel):
    value: str | None = Field(default=None, max_length=200)
    count: int = Field(default=5, ge=1, le=MAX_COUNT)


def image_url(path) -> str:
    """URL of a file in output/, with a version so the browser reloads re-runs."""
    return f"/images/{path.name}?t={int(path.stat().st_mtime)}"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/orthophotos")
def create_orthophotos(request: OrthophotoRequest) -> dict:
    """Run the pipeline for each contract ID and return image URLs and errors.

    A plain `def` (not async): FastAPI runs it in a thread pool, so the
    blocking network calls do not freeze the server.
    """
    ids = list(dict.fromkeys(cid.strip() for cid in request.contract_ids if cid.strip()))
    valid = [cid for cid in ids if CONTRACT_ID_PATTERN.match(cid)]
    failed = [
        {"contract_id": cid, "error": "Invalid contract ID (letters and digits only)"}
        for cid in ids
        if cid not in valid
    ]

    results = get_many_contract_orthophotos(valid) if valid else {"ok": {}, "failed": {}}

    ok = []
    for cid, path in results["ok"].items():
        ok.append({"contract_id": cid, "image_url": image_url(path)})
    failed += [{"contract_id": cid, "error": err} for cid, err in results["failed"].items()]

    return {"ok": ok, "failed": failed}


@app.post("/api/combined")
def create_combined(request: CombinedRequest) -> dict:
    """Contracts (red) and plots (blue) together; nearby items share one image."""
    failed = []

    contract_ids = [c.strip() for c in request.contract_ids if c.strip()]
    valid_contracts = [c for c in contract_ids if CONTRACT_ID_PATTERN.match(c)]
    failed += [
        {"type": "contract", "id": c, "error": "Invalid contract ID (letters and digits only)"}
        for c in contract_ids
        if c not in valid_contracts
    ]

    plots = []
    for p in request.plots:
        migrash, tochnit = p.migrash.strip(), (p.tochnit or "").strip() or None
        if not migrash:
            continue
        if len(migrash) > MAX_MIGRASH_LENGTH or (tochnit and len(tochnit) > MAX_TOCHNIT_LENGTH):
            failed.append({"type": "plot", "id": migrash, "error": "Plot or plan number too long"})
            continue
        plots.append({"migrash": migrash, "tochnit": tochnit})

    if not valid_contracts and not plots:
        return {"images": [], "failed": failed}

    result = get_combined_orthophotos(valid_contracts, plots)
    images = [
        {"image_url": image_url(img["image_path"]), "contracts": img["contracts"], "plots": img["plots"]}
        for img in result["images"]
    ]
    return {"images": images, "failed": failed + result["failed"]}


@app.get("/api/categories")
def categories() -> dict:
    """Which fields can be browsed, per layer."""
    return CATEGORY_FIELDS


def _check_category(layer: str, field: str) -> None:
    if field not in CATEGORY_FIELDS.get(layer, []):
        raise HTTPException(status_code=404, detail=f"Unknown layer/field: {layer}/{field}")


@app.get("/api/categories/{layer}/{field}/values")
def category_values(layer: str, field: str) -> list[dict]:
    """All values of a field with counts, most common first: [{"value", "count"}]."""
    _check_category(layer, field)
    try:
        return category_options(layer, field)
    except (requests.RequestException, RuntimeError) as e:
        raise HTTPException(status_code=502, detail=f"ArcGIS error: {e}") from e


@app.post("/api/categories/sample")
def category_sample(request: SampleRequest) -> dict:
    """Images of N random items with field == value, one image per item."""
    _check_category(request.layer, request.field)
    try:
        result = sample_images(request.layer, request.field, request.value, request.count)
    except (requests.RequestException, RuntimeError) as e:
        raise HTTPException(status_code=502, detail=f"ArcGIS error: {e}") from e
    images = [
        {"image_url": image_url(img["image_path"]), "label": img["label"], "attributes": img["attributes"]}
        for img in result["images"]
    ]
    return {"total_matches": result["total_matches"], "images": images, "failed": result["failed"]}


@app.post("/api/dataset/sample")
def dataset_sample(request: DatasetSampleRequest) -> dict:
    """Add N random contracts with MataraDesc == value to the YOLO dataset (masked, 1024×1024)."""
    try:
        result = sample_dataset_images(request.value, request.count)
    except (requests.RequestException, RuntimeError) as e:
        raise HTTPException(status_code=502, detail=f"ArcGIS error: {e}") from e
    images = [
        {
            "image_url": f"/dataset/images/{img['image_path'].name}?t={int(img['image_path'].stat().st_mtime)}",
            "label": img["label"],
            "attributes": img["attributes"],
        }
        for img in result["images"]
    ]
    return {
        "total_matches": result["total_matches"],
        "images": images,
        "failed": result["failed"],
        "dataset_size": result["dataset_size"],
    }
