"""
Query an ArcGIS REST MapServer layer for a specific contract ID.

Install:  uv add requests truststore
Run:      uv run contract_query.py
"""

import json

import requests

from arcgis_utils import get_json, query_layer

LAYER_URL = (
    "https://arcgisserverprod.mami.gov.il/arcgis/rest/services/"
    "EXB/Contract_EXB/MapServer/0"
)


def get_layer_fields(layer_url: str = LAYER_URL) -> list[dict]:
    """Return the layer's field list (name, alias, type)."""
    return get_json(layer_url).get("fields", [])


def find_contract_field(fields: list[dict]) -> str:
    """Find the field whose name looks like 'contractid' (case-insensitive)."""
    for field in fields:
        name = field["name"]
        if name.lower().replace("_", "") == "contractid":
            return name
    names = [f["name"] for f in fields]
    raise ValueError(f"No 'contractid' field found. Available fields: {names}")


def build_where(field_name: str, field_type: str, value) -> str:
    """Build a SQL where clause; quote the value for string fields."""
    if field_type == "esriFieldTypeString":
        safe = str(value).replace("'", "''")
        return f"{field_name} = '{safe}'"
    return f"{field_name} = {int(value)}"


def query_by_contract_id(
    contract_id,
    layer_url: str = LAYER_URL,
    return_geometry: bool = False,
    out_sr: int = 4326,
) -> list[dict]:
    """Return all features (attributes, plus geometry if requested) for one contract ID."""
    fields = get_layer_fields(layer_url)
    field_name = find_contract_field(fields)
    field_type = next(f["type"] for f in fields if f["name"] == field_name)

    return query_layer(
        layer_url,
        where=build_where(field_name, field_type, contract_id),
        return_geometry=return_geometry,
        out_sr=out_sr,  # 4326 = WGS84 lat/lon, 2039 = Israel TM Grid
    )


def print_features(features: list[dict]) -> None:
    """Print features in a readable format."""
    if not features:
        print("No results found.")
        return
    print(f"Found {len(features)} result(s):\n")
    for i, feature in enumerate(features, start=1):
        print(f"--- Result {i} ---")
        for key, value in feature.get("attributes", {}).items():
            print(f"{key}: {value}")
        if "geometry" in feature:
            print("geometry:", json.dumps(feature["geometry"])[:200], "...")
        print()


def main() -> None:
    contract_id = input("Enter contract ID: ").strip()
    try:
        features = query_by_contract_id(contract_id)
    except requests.RequestException as e:
        print(f"Network error: {e}")
        return
    except (RuntimeError, ValueError) as e:
        print(e)
        return
    print_features(features)


if __name__ == "__main__":
    main()
