# Working Runbook

## One-Time Setup

```powershell
cd C:\Users\Amaan\Downloads\screen-aware
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
notepad .env
```

Set `VIDEO_DB_API_KEY` in `.env`. Do not commit `.env`.

```powershell
cd C:\Users\Amaan\Downloads\screen-aware\companion
npm install
```

If the VideoDB capture binary is somewhere else, set:

```powershell
$env:VIDEODB_CAPTURE_BINARY = "C:\absolute\path\to\capture.exe"
```

## Start The Backend

```powershell
cd C:\Users\Amaan\Downloads\screen-aware
.\.venv\Scripts\Activate.ps1
screen-aware-api
```

Check:

```powershell
Invoke-RestMethod http://127.0.0.1:8787/health
```

## Start The Companion

Development:

```powershell
cd C:\Users\Amaan\Downloads\screen-aware\companion
npm run tauri:dev
```

The launcher automatically cycles through available Vite ports starting at `5173` and injects the selected port into Tauri's `devUrl`. If you want a different starting point:

```powershell
$env:SCREEN_AWARE_DEV_PORT = "5300"
npm run tauri:dev
```

Compiled no-bundle build:

```powershell
C:\Users\Amaan\Downloads\screen-aware\companion\src-tauri\target\release\screen-aware-companion.exe
```

## Capture A Debug Session

1. Open your target app in a browser or desktop window.
2. Start the Screen-Aware backend.
3. Open the Tauri companion.
4. Enter the issue in the Issue field. Example: `The Flappy page is running but the canvas is blank after I press Start.`
5. Enable Screen and Mic. Enable System if you want app audio.
6. Press Start and grant OS permissions.
7. Reproduce the issue while speaking or typing what you expect.
8. Ask your CLI agent to use the Screen-Aware MCP tools.

## What Happens Internally

1. The companion calls `POST /api/sessions`.
2. Backend creates a VideoDB CaptureSession and returns a client token.
3. Rust initializes the VideoDB capture binary with the token.
4. Rust lists capture channels and starts recording selected channel IDs.
5. VideoDB emits lifecycle events.
6. Backend starts `start_transcript`, `index_audio`, and `index_visuals` for RTStreams.
7. The MCP server searches those indexes when an agent calls a tool.

## Stop Capture

Press Stop in the companion. The backend keeps the local session state and events so agents can continue querying the most recent captured context.

## Troubleshooting

- Backend says key missing: make sure `.env` exists and contains `VIDEO_DB_API_KEY`.
- MCP client says key missing: pass `SCREEN_AWARE_ENV_FILE=C:\Users\Amaan\Downloads\screen-aware\.env`.
- MCP client sees no events: start the backend and companion first, then run `screen_aware_get_capture_status`.
- Tauri cannot find capture binary: run `npm install` inside `companion/` or set `VIDEODB_CAPTURE_BINARY`.
- VS Code/Cline launched before setting a user environment variable: restart the editor.

## Local Validation

```powershell
cd C:\Users\Amaan\Downloads\screen-aware
.\.venv\Scripts\Activate.ps1
python -m compileall -q src tests
python -m pytest -q

cd C:\Users\Amaan\Downloads\screen-aware\companion
npm run typecheck
npm run build
cargo fmt --check --manifest-path .\src-tauri\Cargo.toml
cargo check --manifest-path .\src-tauri\Cargo.toml
npm run tauri -- build --no-bundle
```
