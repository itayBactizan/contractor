"""
Query the plots (מגרשים) layer by plot number (MIGRASH), optionally within a plan (TOCHNIT).

A plot number is usually unique only inside its plan, so the same MIGRASH can
match plots in several plans. Giving TOCHNIT narrows it to the exact plot.
"""

from arcgis_utils import SR, query_layer

PLOTS_LAYER_URL = (
    "https://arcgisserverprod.mami.gov.il/arcgis/rest/services/"
    "EXB/TochniotRmi_EXB/MapServer/1"
)

# More matches than this means the number is too general to be useful
MAX_PLOTS_PER_ID = 20


def sql_string(value: str) -> str:
    """Quote a value for a SQL where clause (doubling any single quotes)."""
    return "'" + str(value).replace("'", "''") + "'"


def query_plots(migrash: str, tochnit: str | None = None) -> list[dict]:
    """Return the plot features with this MIGRASH (and TOCHNIT, if given), in EPSG:2039."""
    where = f"MIGRASH = {sql_string(migrash)}"
    if tochnit:
        where += f" AND TOCHNIT = {sql_string(tochnit)}"

    features = query_layer(PLOTS_LAYER_URL, where=where, out_sr=SR)

    if len(features) > MAX_PLOTS_PER_ID:
        raise ValueError(
            f"Found {len(features)} plots with MIGRASH {migrash}: too many. "
            "Add the plan number (TOCHNIT) to choose the right one."
        )
    return features


def plot_label(plot: dict) -> str:
    """Display name for a plot request: '12' or 'plan 101-0123456 / 12'."""
    if plot.get("tochnit"):
        return f"{plot['tochnit']} / {plot['migrash']}"
    return plot["migrash"]
