# Tech Stack

## Backend

- Python 3.11+
- FastAPI for the local HTTP control plane.
- FastMCP from the Python MCP SDK for stdio MCP server support.
- Pydantic settings and validation for environment-driven config.
- `httpx` for optional OpenAI-compatible live overlay replies.
- VideoDB Python SDK with capture support for CaptureSession, RTStream indexing, transcript, and semantic search.
- JSON/JSONL local state for simple inspection and multi-client sharing.

## Desktop Companion

- Tauri 2 for a small native desktop shell.
- Rust for process control, recorder protocol I/O, and long-running capture commands.
- React + TypeScript + Vite for the UI.
- The `videodb` npm package is installed so the native VideoDB capture binary is available locally. The app does not depend on Electron at runtime.

## MCP

- Local stdio transport. This is the most portable option for CLI coding agents and editor integrations.
- Read-only tools with descriptive names and Pydantic input models.
- Markdown output by default, JSON output when an agent asks for structured data.

## Live Overlay Replies

- `POST /api/live/messages` accepts typed overlay messages and speech-recognition transcripts.
- Replies are pushed back over the existing `/api/live` WebSocket.
- The model API is configured with `SCREEN_AWARE_LIVE_BASE_URL`, `SCREEN_AWARE_LIVE_MODEL`, and `SCREEN_AWARE_LIVE_API_KEY` or `OPENAI_API_KEY`.
- Live replies explain what Screen-Aware sees and suggest fix targets; code edits still happen through the connected MCP coding agent.

## Frontend Design System

- Monochrome only.
- Stark paper background.
- High-contrast text and borders.
- No gradients.
- No drop shadows.
- Sharp, dense controls intended for repeated debugging sessions.

## Runtime Ports And Paths

- Backend: `http://127.0.0.1:8787`
- Companion dev server: `http://127.0.0.1:5173`
- Runtime state: `C:\Users\Amaan\Downloads\screen-aware\.screen-aware`
- Env file: `C:\Users\Amaan\Downloads\screen-aware\.env`
- MCP command: `C:\Users\Amaan\Downloads\screen-aware\.venv\Scripts\python.exe -m screen_aware.mcp_server`
