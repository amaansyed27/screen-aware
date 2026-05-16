# Use Case Examples

## Visual Runtime Bug

1. Start the target web app.
2. Start Screen-Aware capture with Screen and Mic enabled.
3. Reproduce the visible issue.
4. Ask the coding agent:

```text
Use screen_aware_analyze_screen_context to inspect the visible app and terminal. The bug is that the game starts but the main play area is blank. Find the likely code cause, patch it, and run the build.
```

## Terminal Error Plus Spoken Context

Speak: `I just ran npm run build. The app says the stats route failed after I added localStorage history.`

Agent prompt:

```text
Use Screen-Aware to find the latest visible terminal error and the spoken issue. Then inspect the files that caused it and fix the build.
```

## Multi-Page UI Regression

Reproduce by navigating through several pages while capturing.

```text
Use screen_aware_query_workflow_history to reconstruct the route sequence I just tested. Identify which page first showed broken layout or incorrect state, then patch the app.
```

## Accessibility And Control Bugs

```text
Use Screen-Aware live context to inspect whether keyboard focus, buttons, and game controls are visible and behaving. Fix the smallest issue you can verify from the captured session.
```

## Suggested Tool Order

1. `screen_aware_get_capture_status`
2. `screen_aware_get_live_context`
3. `screen_aware_analyze_screen_context`
4. `screen_aware_query_workflow_history`

Use `screen_aware_get_live_context` for the latest raw events. Use semantic search tools when the agent needs evidence matching a question.

