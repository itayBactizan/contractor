# Contract Orthophoto: Technical Documentation

A tool that takes **contract IDs** and **plot numbers**, finds their shapes on the map, downloads the 2025 national aerial photo (orthophoto) of that area, and draws contracts in **red** and plots in **blue** on it. It runs as a web app: a React page in the browser talks to a Python (FastAPI) server, which talks to the organization's ArcGIS servers.

Part 2 (frontend) is written for a Python / data-science reader and explains the web concepts from scratch.

---

## Contents

1. [Architecture](#1-architecture)
2. [Project layout](#2-project-layout)
3. [End-to-end flow of one request](#3-end-to-end-flow-of-one-request)
4. [Part 1: Backend (Python)](#4-part-1-backend-python)
5. [API reference](#5-api-reference)
6. [Part 2: Frontend (React), explained for Python developers](#6-part-2-frontend-react-explained-for-python-developers)
7. [Running the project](#7-running-the-project)
8. [Configuration knobs](#8-configuration-knobs)
9. [Troubleshooting](#9-troubleshooting)
10. [How to extend](#10-how-to-extend)
11. [Known limitations](#11-known-limitations)

---

## 1. Architecture

```
┌──────────────────────┐   HTTP (JSON)   ┌───────────────────────┐  HTTPS (ArcGIS REST)  ┌─────────────────────────────┐
│  Browser             │ ──────────────► │  FastAPI server       │ ────────────────────► │ arcgisserverprod.mami.gov.il │
│  React app           │                 │  scripts/api.py       │                       │  • Contract layer           │
│  (frontend/src)      │ ◄────────────── │  + pipeline modules   │ ◄──────────────────── │  • Plots layer              │
│  http://localhost:5173│  image URLs    │  http://localhost:8000│   shapes + image      │  • Orthophoto ImageServer   │
└──────────────────────┘                 └──────────┬────────────┘                       └─────────────────────────────┘
          ▲                                         │ writes PNG + JSON
          │  GET /images/combined_….png             ▼
          └──────────────────────────────────  output/  folder
```

Three ArcGIS services are used. They share **no common field**, so they are connected **by location** (a spatial join):

| Service | URL (under `/arcgis/rest/services/`) | What we take |
|---|---|---|
| Contracts | `EXB/Contract_EXB/MapServer/0` | contract polygon by contract ID |
| Plots | `EXB/TochniotRmi_EXB/MapServer/1` | plot polygon by `MIGRASH` (+ optional `TOCHNIT`) |
| Orthophoto 2025 | `OrtoPhoto/OrtophotoArtzi_2025/ImageServer` | the aerial image of a rectangle (0.2 m/pixel) |

All coordinates are in **EPSG:2039 (Israel TM Grid)**, in metres. That is the native system of the orthophoto, so no reprojection is needed on our side.

---

## 2. Project layout

```
itay-test/
├── pyproject.toml / uv.lock     Python dependencies (managed by uv)
├── .python-version              Python version
├── scripts/                     BACKEND (Python)
│   ├── arcgis_utils.py          shared HTTP + ArcGIS query helpers
│   ├── contract_query.py        contracts layer
│   ├── plot_query.py            plots layer
│   ├── orthophoto.py            orthophoto ImageServer
│   ├── draw_outline.py          draws outlines + labels on images
│   ├── contract_orthophoto.py   pipeline: one image per contract (+ CLI)
│   ├── combined_orthophoto.py   pipeline: contracts + plots, grouped images (+ CLI)
│   ├── category_sample.py       "By category": N random items with a field value (+ CLI)
│   ├── explore_field.py         CLI: distinct values + counts of any field
│   ├── dataset_export.py        "Dataset (YOLO)": masked 1024×1024 contract images (+ CLI)
│   └── api.py                   FastAPI web server (used by the UI)
├── frontend/                    FRONTEND (JavaScript / React)
│   ├── package.json             JS dependencies + commands   (≈ pyproject.toml)
│   ├── package-lock.json        exact versions               (≈ uv.lock)
│   ├── node_modules/            installed libraries          (≈ .venv, not in git)
│   ├── vite.config.js           dev server settings + proxy to the backend
│   ├── index.html               the single HTML page
│   └── src/
│       ├── main.jsx             entry point: mounts the app into the page
│       ├── App.jsx              title + tabs (By ID / By category)
│       ├── components/
│       │   ├── ByIdView.jsx     "By ID" tab: inputs, state, request, results
│       │   ├── CategoryView.jsx "By category" tab: the two sections
│       │   ├── CategorySection.jsx  field → value → N random images
│       │   ├── DatasetView.jsx  "Dataset (YOLO)" tab
│       │   ├── ChipList.jsx     list of chosen items with × buttons
│       │   └── ImageCard.jsx    one result image + Download button
│       ├── App.css              layout and component styles
│       └── index.css            colors, fonts, light/dark theme
├── output/                      generated images + JSON (not in git)
├── dataset/                     YOLO dataset: images/, meta/, metadata.csv (not in git)
├── Dockerfile, .dockerignore    container build (not wired to the UI yet)
└── certs/                       organization root certificate for Docker
```

---

## 3. End-to-end flow of one request

User adds contracts `900395618, 900058139` and plot `12` in plan `101-0123456`, then clicks **Create image**.

1. **Browser** (`App.jsx → createImage`) sends
   `POST /api/combined` with `{"contract_ids": ["900395618","900058139"], "plots": [{"migrash":"12","tochnit":"101-0123456"}]}`.
2. **Vite dev server** forwards `/api/...` to `http://localhost:8000` (`vite.config.js` proxy).
3. **FastAPI** (`api.py → create_combined`) validates the input and calls `get_combined_orthophotos`.
4. **Collect shapes** (`combined_orthophoto.collect_items`):
   - each contract → `contract_query.query_by_contract_id` → ArcGIS `.../MapServer/0/query?where=CONTRACTID='900395618'`
   - each plot → `plot_query.query_plots` → `.../MapServer/1/query?where=MIGRASH='12' AND TOCHNIT='101-0123456'`
   - not found / errors go to a `failed` list; the rest continue.
5. **Group by location** (`group_by_distance`): items whose combined square fits in 1.5 km share one image; far items get their own.
6. For **each group** (`make_group_image`):
   1. bounding box of all shapes + 20 m margin → expanded to a **square** (`features_bbox`, `make_square`)
   2. check that orthophoto tiles cover it (`orthophoto.query_footprints`)
   3. download the image of that square (`orthophoto.export_image` → `/ImageServer/exportImage`)
   4. draw plots blue, then contracts red on top (`draw_outline.draw_outlines`)
   5. save `output/combined_<time>.png` + `.json` (attributes)
7. **FastAPI** returns `{"images": [{"image_url": "/images/combined_….png?t=…", "contracts": [...], "plots": [...]}], "failed": [...]}`.
8. **Browser** shows one card per image; the `<img>` tag loads `/images/...`, which Vite forwards to FastAPI, which serves the file from `output/`.

---

## 4. Part 1: Backend (Python)

### Dependencies (`pyproject.toml`)

| Library | Used for |
|---|---|
| `requests` | HTTP calls to ArcGIS |
| `truststore` | makes Python trust the Windows certificate store (organization CA) |
| `pillow` | opening images and drawing lines/text |
| `fastapi` | the web API |
| `uvicorn[standard]` | the server process that runs FastAPI |

### `arcgis_utils.py`: shared ArcGIS helpers

Every network query goes through here, so SSL, timeouts, errors and paging are handled in one place.

- `truststore.inject_into_ssl()` runs on import: all HTTPS in the process uses the Windows certificate store.
- `SR = 2039`, `TIMEOUT = 60`, type alias `BBox = (xmin, ymin, xmax, ymax)`.
- `get_json(url, params)`: GET with `f=json`; raises on HTTP errors **and** on ArcGIS errors (ArcGIS returns HTTP 200 with `{"error": ...}` in the body).
- `query_layer(layer_url, where="1=1", box=None, out_fields="*", return_geometry=True, out_sr=SR)`: the generic **feature query**:
  - attribute filter (`where`, SQL-like) and/or spatial filter (`box` → `esriSpatialRelIntersects`)
  - **paging**: ArcGIS returns at most `maxRecordCount` rows per call and sets `exceededTransferLimit`; the loop continues with `resultOffset` until done.
  - returns a list of features: `{"attributes": {...}, "geometry": {"rings": [[[x, y], ...]]}}`

### `contract_query.py`: contracts layer

- `LAYER_URL`: contracts MapServer layer 0.
- `get_layer_fields()` / `find_contract_field()`: reads the layer's field list and finds the field named like `contractid` (case and `_` insensitive), so the code doesn't hard-code the exact field name.
- `build_where(field, type, value)`: quotes strings (`'…'`, doubling `'`) and casts numbers, based on the field type.
- `query_by_contract_id(contract_id, return_geometry=False, out_sr=4326)`: the main function. The pipelines call it with `return_geometry=True, out_sr=2039`.
- `main()`: CLI: `uv run scripts/contract_query.py` prints a contract's attributes.

### `plot_query.py`: plots layer

- `PLOTS_LAYER_URL`: plots MapServer layer 1.
- `query_plots(migrash, tochnit=None)`: `MIGRASH = 'x'` (and `AND TOCHNIT = 'y'` when given). Values are quoted with `sql_string` to prevent SQL injection.
- `MAX_PLOTS_PER_ID = 20`: a plot number alone is not unique across plans; if more than 20 plots match, it raises an error asking for the plan.
- `plot_label(plot)`: display name `"101-0123456 / 12"` or `"12"`.

### `orthophoto.py`: aerial image service

- `get_service_info()`: service metadata (max image width/height, extent).
- `query_footprints(bbox)`: which image **tiles** (catalog items) intersect the box; used only as a coverage check.
- `compute_image_size(bbox, pixel_size, max_w, max_h)`: pixel size of the output at native 0.2 m/pixel, scaled down uniformly if it exceeds the server limit.
- `export_image(bbox, path, image_format)`: calls `/exportImage` with `bbox`, `size`, `format` (`png24` default in pipelines; `tiff` gives a GeoTIFF) and `f=image` (returns raw bytes). If the server returns JSON instead of an image, that's an error.
- `main()`: CLI to download any bbox.

### `draw_outline.py`: drawing on the image

The key idea is **map → pixel** conversion. The image covers a known bbox, so:

```
px = (x - xmin) / (xmax - xmin) * width
py = (ymax - y) / (ymax - ymin) * height      # y flipped: map y grows up, image rows grow down
```

- `world_to_pixel(x, y, bbox, size)`: the formula above.
- `geometry_lines()` / `geometry_dots()`: extract polygon rings / polyline paths / points from an ArcGIS geometry.
- `draw_outlines(image_path, layers, bbox)`: draws several groups, each `{"features", "color", "label_for"}`, in order (later groups on top). Line width and font size scale with image size. Each feature gets its own label at the center of its bounding box, with a white outline for readability.
- `draw_contract_outline(...)`: a small wrapper used by the per-contract pipeline (single red group).
- Colors: `LINE_COLOR = (255, 0, 0)` contracts, `PLOT_COLOR = (0, 112, 255)` plots.

### `contract_orthophoto.py`: per-contract pipeline (original flow)

- `OUTPUT_DIR`: absolute `itay-test/output`, independent of the current folder.
- `geometry_points()`, `features_bbox(features, buffer=20)`, `make_square(bbox)`: geometry helpers reused by the combined pipeline.
- `get_contract_orthophoto(contract_id)`: query → square bbox → coverage check → download → red outline → `contract_<id>.png` + `.json`.
- `get_many_contract_orthophotos(ids)`: loops with per-ID error capture → `{"ok": {id: path}, "failed": {id: error}}`.
- `main()`: CLI: `uv run scripts/contract_orthophoto.py`.

### `combined_orthophoto.py`: contracts + plots pipeline (used by the UI)

- `collect_items(contract_ids, plots)`: queries everything; returns a flat list of items `{"kind": "contract"|"plot", "request": label, "feature": …}` plus `failed`. One input can yield several items (e.g. a plot number without a plan).
- `group_by_distance(items, max_side=1500)`: a greedy clustering. Items are sorted west→east; each item joins the first group whose merged bounding box (plus margins) still fits in `max_side`, otherwise it starts a new group. Simple and deterministic; it is not an optimal clustering (like k-means it can depend on order), but it guarantees every image stays at high resolution.
- `make_group_image(group, name)`: square bbox → coverage → `export_image` → draw (plots first, contracts on top) → PNG + JSON (`{"contracts": [...], "plots": [...]}` attributes).
- `get_combined_orthophotos(contract_ids, plots)`: the entry point; file names are `combined_<YYYYmmdd-HHMMSS>_<random>[_n].png`.
- `main()`: CLI: `uv run scripts/combined_orthophoto.py`.

### `category_sample.py`: browse by category

- `CATEGORY_FIELDS`: the whitelist of fields that can be browsed (`contracts: MataraDesc`, `plots: TARGUMYEUD, KVUZ_TRG`). Field names never come from the user, which keeps the SQL safe. Add a field here to make it browsable.
- `category_options(layer, field)`: `value_counts` from `arcgis_utils`, cached in memory for 10 minutes.
- `sample_images(layer, field, value, count=5)`:
  1. `object_ids(where)`: all matching OBJECTIDs in one call (`returnIdsOnly=true`), then `random.shuffle` (ArcGIS has no "ORDER BY random").
  2. Fetch features for the first IDs (`query_by_object_ids`) and make one image per item with `combined_orthophoto.make_group_image([item])`, so each image shows only that item.
  3. Items with no geometry or no orthophoto coverage are skipped and replaced by the next random IDs (up to 3 × count tried), so you usually still get `count` images.
- CLI: `uv run scripts/category_sample.py contracts MataraDesc "מסחר ושרותים אחרים"`.

### `dataset_export.py`: YOLO dataset images

- One contract per image, **1024×1024** (`orthophoto.OUTPUT_SIZE`), everything outside the contract polygon **black**, no outline or label.
- `contract_bbox(feature)`: tight square around the contract with a 3% margin (`MARGIN_RATIO`), so the contract fills the frame.
- `mask_outside(image, geometry, bbox)`: builds a Pillow mask from the polygon rings (same map→pixel formula as `draw_outline`); exterior rings (clockwise in ArcGIS) are white, holes (counter-clockwise) black; pixels outside the mask become black.
- `make_dataset_image(feature, label)`: export → mask → save `dataset/images/<contractId>_<OBJECTID>.png`, `dataset/meta/<name>.json` (bbox in EPSG:2039, metres per pixel, polygon, attributes) and a row in `dataset/metadata.csv`. The bbox + metres per pixel are what you need later to turn map coordinates into YOLO boxes: `px = (x - xmin) / meters_per_pixel`, `py = (ymax - y) / meters_per_pixel`.
- `sample_dataset_images(value, count)`: random contracts with `MataraDesc == value`, skipping OBJECTIDs already in `metadata.csv` (no duplicates). Uses `category_sample.sample_items`, the shared random-sampling loop.
- CLI: `uv run scripts/dataset_export.py "מגורים" --count 5`.

### `explore_field.py`: field values (CLI)

`uv run scripts/explore_field.py MataraDesc` or `... TARGUMYEUD --layer plots [--where "..."]`. Prints value counts and saves `output/<field>_values.csv` (UTF-8 with BOM for Excel).

### `api.py`: the web server

FastAPI turns Python functions into HTTP endpoints. Request bodies are described with **Pydantic** models (`BaseModel` classes, similar to dataclasses with validation), and FastAPI parses and validates the JSON automatically (returns HTTP 422 if the shape is wrong).

- `app.mount("/images", StaticFiles(directory=OUTPUT_DIR))`: serves files in `output/` as `/images/<name>`. Path traversal (`../`) is blocked by `StaticFiles`.
- Endpoints are plain `def` (not `async def`): FastAPI runs them in a thread pool, so slow blocking `requests` calls don't freeze the server.
- Input validation: contract IDs must match `^[A-Za-z0-9_-]{1,20}$` (they become file names); plot values are length-limited (they're only used inside quoted SQL).
- `image_url(path)` adds `?t=<file modified time>` so the browser doesn't show a cached old image after a re-run.
- Interactive API docs are generated automatically at **http://localhost:8000/docs** (try requests there without the UI).

---

## 5. API reference

### Browse by category

`GET /api/categories` → `{"contracts": ["MataraDesc"], "plots": ["TARGUMYEUD", "KVUZ_TRG"]}`

`GET /api/categories/{layer}/{field}/values` → `[{"value": "מגורים", "count": 900}, ...]` (most common first; `404` if the layer/field isn't allowed)

`POST /api/categories/sample`
```json
{"layer": "contracts", "field": "MataraDesc", "value": "מסחר ושרותים אחרים", "count": 5}
```
→
```json
{"total_matches": 1234,
 "images": [{"image_url": "/images/sample_contracts_…_1.png?t=…", "label": "900395618", "attributes": {...}}],
 "failed": [{"id": "900000006", "error": "No orthophoto coverage for this area."}]}
```
`count` is 1–10 (`422` otherwise). `value: null` selects items where the field is empty.

### YOLO dataset

`POST /api/dataset/sample` `{"value": "מגורים", "count": 5}` → `{"total_matches", "images": [{"image_url": "/dataset/images/…png?t=…", "label", "attributes"}], "failed", "dataset_size"}`. Values for the dropdown come from `GET /api/categories/contracts/MataraDesc/values`. `GET /dataset/...` serves the files.

### `GET /api/health`
→ `{"status": "ok"}`

### `POST /api/combined` (used by the UI)

Request:
```json
{
  "contract_ids": ["900395618", "900058139"],
  "plots": [{"migrash": "12", "tochnit": "101-0123456"}, {"migrash": "7", "tochnit": null}]
}
```
Response:
```json
{
  "images": [
    {"image_url": "/images/combined_20261118-095529_799cb5.png?t=1794995729",
     "contracts": ["900395618", "900058139"],
     "plots": ["101-0123456 / 12"]}
  ],
  "failed": [
    {"type": "plot", "id": "7", "error": "Found 25 plots with MIGRASH 7: too many. Add the plan number (TOCHNIT) to choose the right one."}
  ]
}
```

### `POST /api/orthophotos` (per-contract, older flow)
Request `{"contract_ids": ["900395618"]}` → `{"ok": [{"contract_id", "image_url"}], "failed": [{"contract_id", "error"}]}`

### `GET /images/<file>`
The generated PNG/JSON files from `output/`.

---

## 6. Part 2: Frontend (React), explained for Python developers

### 6.1 The tools, mapped to Python equivalents

| Web world | Python equivalent | In this project |
|---|---|---|
| **Node.js** | the Python interpreter | runs JavaScript outside the browser (`C:\Program Files\nvm\V22`) |
| **npm** | `uv` / `pip` | installs libraries, runs commands |
| `package.json` | `pyproject.toml` | dependencies + named commands (`scripts`) |
| `package-lock.json` | `uv.lock` | exact versions; commit it |
| `node_modules/` | `.venv/` | installed libraries; never commit |
| **Vite** | `uvicorn --reload` + a build tool | dev server with hot reload; `npm run build` makes the final static files in `dist/` |
| **React** | (no direct equivalent) | library for building the UI from components |
| **JSX** (`.jsx`) | f-strings / Jinja templates, but in code | HTML-like syntax inside JavaScript |
| `fetch()` | `requests.post()` | HTTP request from the browser |
| `async` / `await` | `asyncio` `async`/`await` | wait for the request without freezing the page |
| CSS | matplotlib style sheets | how things look (colors, spacing, layout) |

The browser only understands HTML, CSS and JavaScript. Vite translates the `.jsx` files into plain JavaScript on the fly (dev) or ahead of time (build).

### 6.2 React in five ideas

1. **A component is a function that returns UI.**
   ```jsx
   function Greeting({ name }) {          // props = function arguments
     return <h1>Hello {name}</h1>         // {…} = insert a JS value (like f"{name}")
   }
   ```
   Use it like an HTML tag: `<Greeting name="Itay" />`.

2. **State = variables that, when changed, redraw the screen.**
   ```jsx
   const [contracts, setContracts] = useState([])   // value + setter, initial value []
   setContracts([...contracts, "900395618"])        // new list → React re-runs the function and updates the page
   ```
   Never modify state in place (`contracts.push(...)` does nothing visible); always pass a **new** value to the setter. It's like treating state as immutable, similar to returning a new DataFrame instead of `inplace=True`.

3. **The function re-runs on every change.** Think of the component as `render(state) -> UI`. React compares the new output with the old and updates only what changed.

4. **Events call your functions.** `onClick={addContracts}` runs `addContracts()` when clicked; `onChange={(e) => setContractText(e.target.value)}` updates state on every keystroke ("controlled input": the input always shows the state value).

5. **Lists and conditions are plain JavaScript.**
   ```jsx
   {loading && <p>Loading…</p>}                              // if loading: show
   {items.map((item) => <li key={item}>{item}</li>)}          // like [f(x) for x in items]
   ```
   `key` must be unique per list item, so React can track which item is which.

Quick JavaScript ↔ Python:

| JavaScript | Python |
|---|---|
| `const x = 1` / `let y = 2` | `x = 1` (const = can't be reassigned) |
| `(a) => a * 2` | `lambda a: a * 2` |
| `[...list, item]` | `[*lst, item]` |
| `{...obj, k: v}` | `{**d, "k": v}` |
| `arr.map(f)` / `arr.filter(f)` | `[f(x) for x in arr]` / `[x for x in arr if f(x)]` |
| `` `Hello ${name}` `` | `f"Hello {name}"` |
| `a ? b : c` | `b if a else c` |
| `x && y` in JSX | "show y only if x is truthy" |
| `null` / `undefined` | `None` |
| `===` | `==` (strict, no type coercion) |
| `new Set(list)` | `set(lst)` |

### 6.3 File by file

#### `index.html`: the single page
```html
<div id="root"></div>
<script type="module" src="/src/main.jsx"></script>
```
An empty `div` and a script. React fills `#root` with the whole app. This is called a **single-page application**: the page never reloads; JavaScript updates it.

#### `src/main.jsx`: entry point
```jsx
createRoot(document.getElementById('root')).render(<StrictMode><App /></StrictMode>)
```
Finds `#root` and renders the `App` component into it (`if __name__ == "__main__": main()` of the frontend). `StrictMode` adds extra development-only checks. It also imports `index.css` (global styles).

#### `src/App.jsx`: the whole screen

**Helpers (plain functions, outside the component):**
- `splitIds(text)`: `"111, 222 333"` → `["111","222","333"]` (regex split on commas/whitespace).
- `plotLabel(plot)`: `"101-0123456 / 12"` or `"12"`.
- `fileName(url)`: `"/images/x.png?t=1"` → `"x.png"` (download file name).

**State (the screen's "model"):**

| State | Type | Meaning |
|---|---|---|
| `contractText`, `tochnitText`, `migrashText` | string | what's typed in each input right now |
| `contracts` | `string[]` | chosen contract IDs (red chips) |
| `plots` | `{migrash, tochnit}[]` | chosen plots (blue chips) |
| `loading` | bool | a request is running |
| `results` | `{images, failed}` or `null` | last server response |
| `error` | string | network/server error message |

**Event handlers:**
- `addContracts()`: split the input, skip IDs already chosen, append to `contracts`, clear the input.
- `addPlots()`: same for plots; the current plan field applies to all plot numbers added in that click. Duplicates are detected by label.
- `onEnter(action)`: returns a key handler, so Enter in an input clicks that box's Add button (a function returning a function, like a Python closure/decorator factory).
- `createImage()`: the network call:
  ```jsx
  setLoading(true)
  const response = await fetch('/api/combined', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ contract_ids: contracts, plots }),   // json.dumps
  })
  setResults(await response.json())                            // response.json() in requests
  ```
  wrapped in `try / catch / finally` (= `try / except / finally`): errors go to `error`; `loading` is reset at the end. The URL is relative (`/api/...`): the browser sends it to the same server that served the page (Vite), which forwards it to FastAPI.

**Rendered UI (the `return (...)` part), top to bottom:**
1. Title and subtitle.
2. Two boxes side by side (they stack on narrow screens): **Contracts** (input, Add button, `ChipList`) and **Plots** (plan input, plot input, Add button, `ChipList`). Add buttons are `disabled` while their input is empty.
3. **Create image** button (disabled while loading or nothing chosen) + legend (red = contract, blue = plot).
4. Status lines: loading message; "split into N images" when there is more than one image.
5. Result grid: one `ImageCard` per image, with the contracts/plots it contains.
6. **Failed** list with type, ID and reason.

#### `src/App.jsx` (shell) and the two tabs
`App.jsx` now only holds the title and a tab bar (`tab` state). Both tab views stay mounted and the inactive one is hidden with the HTML `hidden` attribute, so switching tabs keeps what you typed and the results. `ByIdView.jsx` is the screen described above.

#### `src/components/CategorySection.jsx` ("By category")
Used twice by `CategoryView.jsx` (contracts, plots). New React idea here: **`useEffect`**, code that runs *after* rendering when its dependencies change:
```jsx
useEffect(() => {
  fetch(`/api/categories/${layer}/${field}/values`) ... setOptions(data)
}, [layer, field])          // re-run when the field changes, like a cache key
```
It loads the dropdown values when the section first appears and again whenever the user picks another field. A `cancelled` flag ignores a late answer for a field that is no longer selected.
- State: `field`, `options` (`[{value, count}]`), `optionsState` (`loading`/`ready`/`error`), `selected`, `results`.
- A `<select>` needs string values, so an empty (null) category is stored as the key `__null__` and shown as "(empty)".
- **Get 5 random images** → `POST /api/categories/sample`; after the first run the button says **Get 5 more** (a new random sample).
- Results reuse `ImageCard`; skipped items are listed in a collapsible `<details>`.

#### `src/components/DatasetView.jsx` ("Dataset (YOLO)")
Reuses `CategorySection` with `sampleUrl="/api/dataset/sample"`, `idPrefix="dataset"` (HTML ids must be unique, and the By category tab also has a contracts section) and `onResults` to show the dataset size. `CategorySection` got these optional props; By category is unchanged.

#### `src/components/ChipList.jsx`
Props: `items`, `kind` (`"contract"`/`"plot"`, used for the CSS color class), `labelFor(item)`, `onRemove(index)`. Shows "None added yet." when empty; otherwise one rounded "chip" per item with a × button that calls `onRemove`. The parent owns the data; the child only displays it and reports clicks. This "data down, events up" pattern is the standard React way.

#### `src/components/ImageCard.jsx`
Props: `title`, `imageUrl`, `downloadName`, and `children` (whatever JSX is placed between the tags, here the contracts/plots lines). The image is a link that opens full size in a new tab. **Download** is a normal link with the HTML `download` attribute, which tells the browser to save the file instead of opening it. No JavaScript needed.

#### `src/index.css` and `src/App.css`: styling
- `index.css` defines **CSS variables** (`--accent`, `--contract`, `--plot`, …) on `:root`, and redefines them inside `@media (prefers-color-scheme: dark)`, so the app follows the system light/dark mode. Change a color in one place.
- `App.css` uses **class selectors** (`.card`, `.chip-plot`, …) that match `className="…"` in the JSX (`className`, because `class` is a reserved word in JavaScript).
- Layout uses **CSS Grid**: `grid-template-columns: repeat(auto-fill, minmax(300px, 1fr))` means "as many columns of at least 300 px as fit". That's why the page adapts to any screen width without extra code.

#### `vite.config.js`
```js
server: { proxy: { '/api': 'http://localhost:8000', '/images': 'http://localhost:8000' } }
```
In development the page comes from Vite (port 5173) and the API from FastAPI (port 8000). Browsers block calls between different ports by default (CORS). The proxy makes Vite forward those paths to FastAPI, so the browser only ever talks to one server.

#### `package.json`
- `dependencies`: `react`, `react-dom` (needed at runtime).
- `devDependencies`: `vite`, `@vitejs/plugin-react` (JSX support + hot reload), `oxlint` (a linter, like ruff), `@types/*` (editor autocomplete only).
- `scripts`: `npm run dev` (dev server), `npm run build` (production files in `dist/`), `npm run lint`, `npm run preview` (serve `dist/`).

---

## 7. Running the project

One-time setup:
```bash
uv sync                                  # Python dependencies
cd frontend && npm install               # JS dependencies (needs npm registry = Nexus npm-group)
```
Organization network settings (once per user): see [Troubleshooting](#9-troubleshooting) for `npm config set registry …` and `NODE_OPTIONS=--use-system-ca`.

The project lives on a network share. Tools started through `cmd.exe` (npm) don't accept `\\server\share` paths, so map a drive letter first:
```bash
net use Z: \\mami.gov.il\shares\QlikSenseData\SharedWorkFiles
```

Run (two terminals):
```bash
# Terminal 1, from Z:\AI_PROJECTS\Training\Itayb\itay-test
uv run uvicorn api:app --reload --app-dir scripts

# Terminal 2, from ...\itay-test\frontend
npm run dev
```
Open **http://localhost:5173**. Both servers reload automatically when you save a file.

CLI alternatives (no UI): `uv run scripts/contract_orthophoto.py`, `uv run scripts/combined_orthophoto.py`.

---

## 8. Configuration knobs

| Setting | File | Default | Effect |
|---|---|---|---|
| `BUFFER_METERS` | `contract_orthophoto.py` | 20 | margin around shapes |
| `MAX_SIDE_METERS` | `combined_orthophoto.py` | 1500 | largest square per image; farther items → another image |
| `MAX_PLOTS_PER_ID` | `plot_query.py` | 20 | max plots for one MIGRASH before asking for the plan |
| `PIXEL_SIZE` | `orthophoto.py` | 0.2 | metres per pixel requested |
| `TIMEOUT` | `arcgis_utils.py` / `orthophoto.py` | 60 / 120 s | query / image download timeouts |
| `LINE_COLOR`, `PLOT_COLOR` | `draw_outline.py` | red / blue | outline colors in the image |
| `--contract`, `--plot` | `frontend/src/index.css` | red / blue | colors in the UI (keep in sync with the above) |
| service URLs | `contract_query.py`, `plot_query.py`, `orthophoto.py` | — | ArcGIS endpoints |

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `CERTIFICATE_VERIFY_FAILED` (Python) | Python doesn't trust the organization CA | `truststore` (already in `arcgis_utils.py`); `uv add truststore` |
| `UNABLE_TO_VERIFY_LEAF_SIGNATURE` (npm) | Node doesn't trust the organization CA | `[Environment]::SetEnvironmentVariable("NODE_OPTIONS","--use-system-ca","User")` |
| `npm install` → `ETIMEDOUT` | public npm registry blocked | `npm config set registry https://nexus.mami.gov.il:8443/repository/npm-group/` |
| `EPERM ... C:\Windows\.vite` | npm started from a `\\…` network path | map `Z:` and run from `Z:\…` |
| `Failed to spawn: uvicorn` | backend libraries not installed | `uv add fastapi "uvicorn[standard]"` |
| `VIRTUAL_ENV ... does not match` warning | VS Code auto-activates the venv on a network path | harmless; set `"python.terminal.activateEnvironment": false` |
| UI: "Is the API server running?" | Terminal 1 stopped or crashed | check Terminal 1 for errors |
| `GET / 404` in Terminal 1 | someone opened `localhost:8000/` | normal: the API has no page at `/`; use `/docs` or `/api/health` |
| Plot "No plot found" but it exists | value format differs (spaces, plan format) | check the value in the layer's query page in the browser |

---

## 10. How to extend

**Add another layer (e.g. parcels in green):**
1. `scripts/parcel_query.py`: a `query_parcels(...)` built on `arcgis_utils.query_layer` (copy `plot_query.py`).
2. `combined_orthophoto.collect_items`: query it and add items with `kind: "parcel"`.
3. `make_group_image`: add a layer `{"features": ..., "color": (0, 160, 0), "label_for": ...}` to `draw_outlines`.
4. `api.py`: add a `parcels: list[...]` field to `CombinedRequest`.
5. `App.jsx`: copy the Plots box (state + `addX` + `ChipList`), add to the request body; add a `--parcel` color + `.chip-parcel` CSS.

**Change the request and see it without the UI:** open http://localhost:8000/docs, choose `/api/combined`, **Try it out**.

**Production (one server, no Vite):** `npm run build` creates `frontend/dist/`; FastAPI can serve it with another `StaticFiles` mount, and then the Docker image can run everything. Not implemented yet.

---

## 11. Known limitations

- Requests are synchronous: the UI waits for all contracts/plots before showing anything (no per-item progress).
- The PNG is not georeferenced; `export_image(..., "tiff")` gives a GeoTIFF for GIS use (without outlines).
- Images show the full square, not only the shapes (no masking).
- Very large single shapes (larger than the server's max image size × 0.2 m) come out at reduced resolution.
- `group_by_distance` is greedy, so the grouping can depend on input order in edge cases.
- Generated files accumulate in `output/`; there is no cleanup.
