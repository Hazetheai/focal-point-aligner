# Windows / cross-platform setup

The supported GUI is **React + FastAPI** (`npm run dev`). On macOS you can also build an unsigned Tauri `.app` (`./build_macos.sh`). There is no PyQt desktop app.

## Requirements

- **Python 3.10+**
- **Node.js 18+** (npm)
- Git

## Setup

```bat
cd FocalPointAligner
python -m venv venv
venv\Scripts\pip install -r requirements.txt
npm install
npm --prefix web install
```

## Run the GUI

```bat
npm run dev
```

Opens the browser UI (Vite) and starts the API on port **8765**.

## CLI

```bat
venv\Scripts\python cli.py init --input C:\path\to\images --output C:\path\to\output
```

## Troubleshooting

- **API not reachable:** confirm nothing else is bound to `8765`, and that `venv\Scripts\python -m api.app` starts cleanly.
- **Missing packages:** `venv\Scripts\pip install -r requirements.txt`
- **Tauri desktop:** macOS-oriented in this repo (`npm run build` / `./build_macos.sh`). Windows Tauri packaging is possible later but not documented as the primary path here.
