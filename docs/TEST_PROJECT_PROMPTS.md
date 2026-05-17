# Test Project Prompts

Use these prompts to create a realistic test app first, then use Screen-Aware to debug it.

## Initial App Prompt

Paste this into your coding agent before using Screen-Aware:

```text
Build a Vite React TypeScript mini-arcade called Bugfix Arcade.

Requirements:
- Use routes for /, /tic-tac-toe, /flappy, /stats, and /settings.
- The home page should show current saved stats, recent game history, and links to both games.
- Tic Tac Toe should support human vs bot, undo, restart, keyboard navigation, win and draw detection, and a persistent scoreboard.
- Flappy should use a canvas, keyboard and click controls, gravity, jump impulse, obstacle generation, collision detection, pause, restart, score, and difficulty settings.
- Stats should show cross-game history, filters by game, win/loss/draw counts, best flappy score, and reset history.
- Settings should persist sound, reduced motion, player name, bot difficulty, and flappy difficulty in localStorage.
- Add a compact responsive layout that works at mobile and desktop widths.
- Add unit tests for shared game logic where practical.
- Do not use a backend.
- Include clear run instructions.

Make it production-shaped, not a throwaway single page demo.
```

This is intentionally broad enough that coding agents often make visible mistakes: canvas sizing, stale localStorage state, route state resets, keyboard focus bugs, score desync, or incorrect win detection.

## Manual Test Script

After the app is generated:

1. Run the app.
2. Open `/flappy`.
3. Start the game and resize the browser.
4. Navigate to `/settings`, change difficulty, go back to `/flappy`, and restart.
5. Navigate to `/tic-tac-toe`, play until a win or draw, undo, then restart.
6. Navigate to `/stats` and check whether history and filters agree with what you did.

## Screen-Aware Repair Prompt

Start Screen-Aware capture, reproduce one visible issue, then paste:

```text
Use Screen-Aware live. Watch while I show the bug, then tell me what you saw and ask before editing.
```

For live edit mode:

```text
Use Screen-Aware live edit. Watch while I reproduce the bug, then start fixing it.
```

For a stricter diagnostic run:

```text
Use the Screen-Aware MCP tools before editing.

First call screen_aware_get_capture_status. Then call screen_aware_analyze_screen_context with this query:
"What visible app, browser, terminal, and spoken-context evidence explains the bug I just reproduced?"

Use that evidence to inspect the code. Fix only the smallest set of files needed. After the patch, run the relevant tests or build, then tell me what changed and what remains unverified.
```

## Example Spoken Issues

- `The Flappy route says the game is running but the canvas is blank after I press start.`
- `The score changes on the game page but the Stats page still shows zero.`
- `After changing difficulty in Settings, Flappy still behaves like easy mode.`
- `Tic Tac Toe shows a draw even when X clearly has three in a row.`
- `The mobile layout overlaps the canvas controls and I cannot press restart.`
