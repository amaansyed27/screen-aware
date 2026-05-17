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
4. Decide whether to share a full screen or a single app window.
5. Choose Full screen or Window, choose the source, and select microphone/system-sound options.
   Window mode opens the native OS picker, the same style of picker used by video-call apps.
6. Press Start sharing and grant OS permissions.
7. Reproduce the issue while speaking, or click the note button in the top bar to send a short typed context note if mic is off.
8. The companion shrinks into a top recorder bar with capture, annotation, and typed-note controls. The note is stored for MCP context; it does not create a second AI chat.
9. Use Pointer, Pen, or Highlighter from the bar when you need to point at a visible UI problem. Annotation mode expands to a transparent full-screen overlay and returns to the compact bar when the tool is turned off.

## What Happens Internally

1. The companion calls `POST /api/sessions`.
2. Backend creates a VideoDB CaptureSession and returns a client token.
3. Full screen mode initializes the VideoDB capture binary with the token.
4. Full screen mode lists capture channels and starts recording selected channel IDs.
5. Window mode uses the native WebView window picker, records WebM segments locally, and uploads each segment to VideoDB.
6. VideoDB emits lifecycle events for RTStreams, while the backend records uploaded window segment events.
7. Pointer and annotation actions are posted as local client events with normalized screen coordinates.
8. Typed overlay notes are posted as `user.note` client events so MCP tools can read them during a live watch.
9. Backend starts `start_transcript`, `index_audio`, and `index_visuals` for RTStreams and uploaded window segments.
10. The MCP server searches those indexes and recent annotation/note events when an agent calls a tool.

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
