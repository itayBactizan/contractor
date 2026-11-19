"""
Shared helpers for ArcGIS REST services (MapServer / ImageServer).

Install:  uv add requests truststore
"""

import json

import requests
import truststore

# Use the Windows certificate store, which trusts the organization's internal CA
truststore.inject_into_ssl()

SR = 2039  # Israel TM Grid, metres
TIMEOUT = 60

# box format: (xmin, ymin, xmax, ymax)
BBox = tuple[float, float, float, float]


def get_json(url: str, params: dict | None = None) -> dict:
    """GET an ArcGIS REST URL as JSON and raise on HTTP or ArcGIS errors."""
    r = requests.get(url, params={**(params or {}), "f": "json"}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"ArcGIS error: {data['error']}")
    return data


def query_layer(
    layer_url: str,
    where: str = "1=1",
    box: BBox | None = None,
    out_fields: str = "*",
    return_geometry: bool = True,
    out_sr: int = SR,
    extra_params: dict | None = None,
) -> list[dict]:
    """The features of a layer: by an attribute filter (where) and/or by a rectangle (box).

    Follows paging, so results larger than the server's maxRecordCount are complete.
    extra_params: any other ArcGIS query parameters (e.g. returnDistinctValues).
    """
    params = {
        "where": where,
        "outFields": out_fields,
        "returnGeometry": str(return_geometry).lower(),
        "outSR": out_sr,
    }
    if box:
        params.update({
            "geometry": "%f,%f,%f,%f" % box,
            "geometryType": "esriGeometryEnvelope",
            "inSR": SR,
            "spatialRel": "esriSpatialRelIntersects",
        })
    if extra_params:
        params.update(extra_params)

    features = []
    offset = 0
    while True:
        params["resultOffset"] = offset
        data = get_json(layer_url + "/query", params)
        batch = data.get("features", [])
        features.extend(batch)
        if not data.get("exceededTransferLimit") or not batch:
            break
        offset += len(batch)
    return features


def distinct_values(layer_url: str, field: str, where: str = "1=1") -> list:
    """SELECT DISTINCT field FROM layer WHERE ... ORDER BY field (computed on the server)."""
    features = query_layer(
        layer_url,
        where=where,
        out_fields=field,
        return_geometry=False,
        extra_params={"returnDistinctValues": "true", "orderByFields": field},
    )
    return [f["attributes"].get(field) for f in features]


def value_counts(layer_url: str, field: str, where: str = "1=1") -> list[tuple]:
    """SELECT field, COUNT(*) ... GROUP BY field, most common first (like pandas value_counts).

    Falls back to distinct values with count None if the server doesn't support statistics.
    """
    statistics = [{
        "statisticType": "count",
        "onStatisticField": "OBJECTID",
        "outStatisticFieldName": "cnt",
    }]
    try:
        data = get_json(layer_url + "/query", {
            "where": where,
            "groupByFieldsForStatistics": field,
            "outStatistics": json.dumps(statistics),
        })
    except RuntimeError:
        return [(value, None) for value in distinct_values(layer_url, field, where)]

    counts = [
        (f["attributes"].get(field), f["attributes"].get("cnt"))
        for f in data.get("features", [])
    ]
    return sorted(counts, key=lambda vc: -(vc[1] or 0))


def object_ids(layer_url: str, where: str = "1=1") -> list[int]:
    """OBJECTIDs of all features matching where (one call; not limited by maxRecordCount)."""
    data = get_json(layer_url + "/query", {"where": where, "returnIdsOnly": "true"})
    return data.get("objectIds") or []


def query_by_object_ids(layer_url: str, ids: list[int], out_sr: int = SR) -> list[dict]:
    """Full features (attributes + geometry) for the given OBJECTIDs."""
    if not ids:
        return []
    return query_layer(
        layer_url,
        out_sr=out_sr,
        extra_params={"objectIds": ",".join(str(int(i)) for i in ids)},
    )
