---
name: screen-aware
description: "Use Screen-Aware MCP when the user asks Codex to look at the screen, watch a live bug reproduction, inspect visible terminal/editor/browser state, or search captured workflow history."
---

# Screen-Aware

Use this skill when the user asks for visual or audio context from their local desktop, asks you to watch while they reproduce an issue, or asks what happened earlier in the captured workflow.

Screen-Aware is backed by a local companion app, FastAPI backend, and MCP server. The plugin exposes the MCP server as `screen-aware`.

## Tool Selection

- For "use Screen-Aware live", "watch while I show you", or similar prompts, call `screen_aware_watch_live_issue`.
- Use `mode="diagnose"` when the user wants observations before edits.
- Use `mode="live_edit"` when the user explicitly wants you to start fixing after the capture ends.
- For a quick current-state check, call `screen_aware_get_capture_status`.
- For recent non-semantic context, call `screen_aware_get_live_context`.
- For targeted current-session visual/audio search, call `screen_aware_analyze_screen_context`.
- For older indexed workflow history, call `screen_aware_query_workflow_history`.

## Operating Rules

- Treat captured visual/audio evidence as supporting evidence, not as a replacement for reading the repo.
- In diagnostic mode, summarize observations and likely causes, then ask before editing.
- In live-edit mode, use the returned evidence to inspect code, patch the smallest likely fix, and run relevant verification.
- If VideoDB semantic search is still indexing, use live events and local evidence frames first, then retry search if needed.
- Do not ask the user to paste API keys into chat. The server loads credentials from `SCREEN_AWARE_ENV_FILE`.

## Useful Prompts

```text
Use Screen-Aware live. Watch while I show the bug, then tell me what you saw and ask before editing.
```

```text
Use Screen-Aware live edit. Watch while I reproduce the bug, then start fixing it.
```
