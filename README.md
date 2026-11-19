# Contract Orthophoto

Orthophoto images of contracts and plots from the organization's ArcGIS services:
a FastAPI backend (`scripts/`) and a React UI (`frontend/`).

- **By ID**: contracts (red) and plots (blue) on combined images
- **By category**: 5 random contracts by `MataraDesc`, or plots by `TARGUMYEUD` / `KVUZ_TRG`
- **Dataset (YOLO)**: masked 1024×1024 contract images saved to `dataset/`

## Run

```bash
uv sync
uv run uvicorn api:app --reload --app-dir scripts
```

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. Full documentation: [docs/TECHNICAL.md](docs/TECHNICAL.md).
