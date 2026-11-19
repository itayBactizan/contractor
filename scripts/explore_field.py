"""
Explore the values of one field in a layer: distinct values with their counts.

Examples:
    uv run scripts/explore_field.py MataraDesc
    uv run scripts/explore_field.py MataraDesc --where "MataraDesc LIKE '%מסחר%'"
    uv run scripts/explore_field.py TARGUMYEUD --layer plots

Prints the table and saves output/<field>_values.csv (opens with Hebrew in Excel).
"""

import argparse
import csv
import sys

import requests

from arcgis_utils import get_json, value_counts
from contract_orthophoto import OUTPUT_DIR
from contract_query import LAYER_URL as CONTRACTS_LAYER_URL
from plot_query import PLOTS_LAYER_URL

LAYERS = {"contracts": CONTRACTS_LAYER_URL, "plots": PLOTS_LAYER_URL}


def layer_field_names(layer_url: str) -> list[str]:
    """All field names of a layer (to help when a field name is wrong)."""
    return [f["name"] for f in get_json(layer_url).get("fields", [])]


def save_csv(rows: list[tuple], field: str) -> str:
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{field}_values.csv"
    # utf-8-sig adds a BOM so Excel shows Hebrew correctly
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([field, "count"])
        writer.writerows(rows)
    return str(path)


def main() -> None:
    # Print Hebrew correctly in PowerShell / cmd
    sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Distinct values (with counts) of a layer field")
    parser.add_argument("field", help="Field name, e.g. MataraDesc")
    parser.add_argument("--layer", choices=LAYERS, default="contracts")
    parser.add_argument("--where", default="1=1", help="Optional SQL filter")
    args = parser.parse_args()
    layer_url = LAYERS[args.layer]

    try:
        rows = value_counts(layer_url, args.field, args.where)
    except requests.RequestException as e:
        print(f"Network error: {e}")
        return
    except RuntimeError as e:
        print(e)
        print(f"Fields in this layer: {layer_field_names(layer_url)}")
        return

    print(f"{len(rows)} distinct values of {args.field} ({args.layer}):\n")
    for value, count in rows:
        print(f"{count if count is not None else '?':>8}  {value}")
    print(f"\nSaved {save_csv(rows, args.field)}")


if __name__ == "__main__":
    main()
