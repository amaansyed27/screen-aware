# Screen-Aware Copilot

Screen-Aware gives CLI coding agents visual and audio context from your local desktop. A Tauri/Rust companion controls VideoDB real-time capture, a FastAPI backend creates and indexes VideoDB CaptureSessions, and a stdio MCP server exposes the indexed workflow context to agents.

No API keys are committed. Put your VideoDB key in `.env` or in your user environment.

## Quick Start

```powershell
cd C:\Users\Amaan\Downloads\screen-aware
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
notepad .env
```

Set `VIDEO_DB_API_KEY` in `.env`.

```powershell
cd C:\Users\Amaan\Downloads\screen-aware\companion
npm install
```

Run the backend in one terminal:

```powershell
cd C:\Users\Amaan\Downloads\screen-aware
.\.venv\Scripts\Activate.ps1
screen-aware-api
```

Run the Tauri companion in a second terminal:

```powershell
cd C:\Users\Amaan\Downloads\screen-aware\companion
npm run tauri:dev
```

The dev launcher automatically scans from port `5173` upward if another Vite instance is already running. To choose a different starting port:

```powershell
$env:SCREEN_AWARE_DEV_PORT = "5300"
npm run tauri:dev
```

In the companion, choose Full screen or Window, choose Mic and optionally System sound, then press Start.
Window capture uses the native OS picker and uploads searchable segments to VideoDB.
During sharing, use the Pointer, Pen, and Highlighter controls in the floating toolbar to mark the screen. Annotation actions are recorded as live context for MCP agents.

## What It Builds

```text
screen-aware/
  src/screen_aware/
    api.py              FastAPI control plane and VideoDB webhook endpoint
    config.py           environment and .env settings
    event_store.py      shared JSON/JSONL state under .screen-aware/
    formatters.py       API and MCP response formatting
    mcp_server.py       FastMCP stdio server
    videodb_service.py  VideoDB CaptureSession, RTStream indexing, search
  companion/
    src/                React UI with monochrome neo-brutalist styling
    src-tauri/          Rust/Tauri shell and VideoDB recorder bridge
  scripts/              local run helpers
  tests/                backend unit tests
  docs/                 architecture, runbooks, MCP setup, examples
```

## MCP Tools

The MCP server command is:

```powershell
C:\Users\Amaan\Downloads\screen-aware\.venv\Scripts\python.exe -m screen_aware.mcp_server
```

Tools:

- `screen_aware_watch_live_issue`: keeps the MCP call open while you demonstrate a bug, then returns live visual/audio/user-note evidence. Use `diagnose` mode to ask before edits or `live_edit` mode to proceed into fixes.
- `screen_aware_analyze_screen_context`: semantic visual/audio search plus recent live events.
- `screen_aware_query_workflow_history`: semantic search over previous captured workflow context.
- `screen_aware_get_live_context`: recent transcript, visual, audio, and lifecycle events without semantic search.
- `screen_aware_get_capture_status`: current CaptureSession, RTStream, websocket, and indexing state.

Resources:

- `screen-aware://sessions/current`
- `screen-aware://events/recent`

## MCP Client Setup

Use [docs/MCP_CLIENT_SETUP.md](docs/MCP_CLIENT_SETUP.md) for Codex, Claude Code, Gemini CLI, Google Antigravity, OpenCode, VS Code Copilot, Cline, and generic MCP clients.

The safest shared environment block is:

```json
{
  "SCREEN_AWARE_DATA_DIR": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.screen-aware",
  "SCREEN_AWARE_ENV_FILE": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.env",
  "SCREEN_AWARE_AGENT_NAME": "Codex"
}
```

That lets MCP clients start the server without storing the VideoDB key in their config. `SCREEN_AWARE_AGENT_NAME` is what the companion shows as the connected coding agent.

Simple Codex prompts:

```text
Use Screen-Aware live. Watch while I show the bug, then tell me what you saw and ask before editing.
```

```text
Use Screen-Aware live edit. Watch while I reproduce the bug, then start fixing it.
```

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/TECH_STACK.md](docs/TECH_STACK.md)
- [docs/WORKING.md](docs/WORKING.md)
- [docs/MCP_CLIENT_SETUP.md](docs/MCP_CLIENT_SETUP.md)
- [docs/USE_CASE_EXAMPLES.md](docs/USE_CASE_EXAMPLES.md)
- [docs/TEST_PROJECT_PROMPTS.md](docs/TEST_PROJECT_PROMPTS.md)

## Validation

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

Compiled no-bundle executable:

```powershell
C:\Users\Amaan\Downloads\screen-aware\companion\src-tauri\target\release\screen-aware-companion.exe
```
