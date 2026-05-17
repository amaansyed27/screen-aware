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

For true live overlay replies, set an OpenRouter key as well:

```powershell
notepad .env
```

Use either `SCREEN_AWARE_LIVE_API_KEY` or `OPENROUTER_API_KEY`. The default live model
settings use OpenRouter's OpenAI-compatible `/chat/completions` endpoint:

```env
SCREEN_AWARE_LIVE_BASE_URL=https://openrouter.ai/api/v1
SCREEN_AWARE_LIVE_MODEL=google/gemini-3-flash-preview
SCREEN_AWARE_LIVE_FALLBACK_MODELS=google/gemini-3.1-flash-lite,google/gemini-3.1-flash-lite-preview
```

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
7. Reproduce the issue while speaking or typing what you expect.
8. The companion shrinks into a top recorder bar. Type in the live box for an immediate Screen-Aware reply in the overlay. If the WebView supports speech recognition, press the live mic button and speak a short question.
9. Use Pointer, Pen, or Highlighter from the bar when you need to point at a visible UI problem. Annotation mode expands to a transparent full-screen overlay and returns to the compact bar when the tool is turned off.
10. Ask Codex or another MCP client to use Screen-Aware when you want it to inspect the stored live messages, visual/audio context, and annotations before editing code.

## What Happens Internally

1. The companion calls `POST /api/sessions`.
2. Backend creates a VideoDB CaptureSession and returns a client token.
3. Full screen mode initializes the VideoDB capture binary with the token.
4. Full screen mode lists capture channels and starts recording selected channel IDs.
5. Window mode uses the native WebView window picker, records WebM segments locally, and uploads each segment to VideoDB.
6. VideoDB emits lifecycle events for RTStreams, while the backend records uploaded window segment events.
7. Pointer and annotation actions are posted as local client events with normalized screen coordinates.
8. Live overlay messages call `POST /api/live/messages`; the backend searches recent VideoDB/context events, calls the configured live model, pushes the reply through `/api/live`, and stores the exchange.
9. Backend starts `start_transcript`, `index_audio`, and `index_visuals` for RTStreams and uploaded window segments.
10. The MCP server searches those indexes, live chat messages, and recent annotation events when an agent calls a tool.

## Stop Capture

Press Stop in the companion. The backend keeps the local session state and events so agents can continue querying the most recent captured context.

## Troubleshooting

- Backend says key missing: make sure `.env` exists and contains `VIDEO_DB_API_KEY`.
- MCP client says key missing: pass `SCREEN_AWARE_ENV_FILE=C:\Users\Amaan\Downloads\screen-aware\.env`.
- Overlay says live replies need a model key: add `SCREEN_AWARE_LIVE_API_KEY` or `OPENROUTER_API_KEY` to `.env`, then restart `screen-aware-api`.
- Live mic button is disabled: your current WebView does not expose speech recognition. Type in the overlay; VideoDB still indexes microphone audio for MCP search.
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
