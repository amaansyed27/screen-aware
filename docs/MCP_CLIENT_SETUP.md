# MCP Client Setup

All configs below launch the same local stdio MCP server:

```powershell
C:\Users\Amaan\Downloads\screen-aware\.venv\Scripts\python.exe -m screen_aware.mcp_server
```

Use these paths:

```text
ROOT = C:\Users\Amaan\Downloads\screen-aware
PYTHON = C:\Users\Amaan\Downloads\screen-aware\.venv\Scripts\python.exe
DATA = C:\Users\Amaan\Downloads\screen-aware\.screen-aware
ENV = C:\Users\Amaan\Downloads\screen-aware\.env
```

Keep the VideoDB key in `ENV`, not in MCP config files.

Set `SCREEN_AWARE_AGENT_NAME` per client if you want the companion to show a friendly connected-agent name such as `Codex`, `Claude Code`, `Gemini CLI`, `Antigravity`, `OpenCode`, `VS Code Copilot`, or `Cline`.

## OpenAI Codex

CLI install:

```powershell
codex mcp add screen-aware --env SCREEN_AWARE_DATA_DIR=C:\Users\Amaan\Downloads\screen-aware\.screen-aware --env SCREEN_AWARE_ENV_FILE=C:\Users\Amaan\Downloads\screen-aware\.env -- C:\Users\Amaan\Downloads\screen-aware\.venv\Scripts\python.exe -m screen_aware.mcp_server
codex mcp list
```

Direct `~/.codex/config.toml` entry:

```toml
[mcp_servers.screen-aware]
command = "C:\\Users\\Amaan\\Downloads\\screen-aware\\.venv\\Scripts\\python.exe"
args = ["-m", "screen_aware.mcp_server"]
cwd = "C:\\Users\\Amaan\\Downloads\\screen-aware"
startup_timeout_sec = 30
tool_timeout_sec = 120
enabled = true

[mcp_servers.screen-aware.env]
SCREEN_AWARE_DATA_DIR = "C:\\Users\\Amaan\\Downloads\\screen-aware\\.screen-aware"
SCREEN_AWARE_ENV_FILE = "C:\\Users\\Amaan\\Downloads\\screen-aware\\.env"
```

In Codex, run `/mcp` or `codex mcp list` and confirm `screen-aware` is connected.

## Claude Code

```powershell
claude mcp add --transport stdio --scope user --env SCREEN_AWARE_DATA_DIR=C:\Users\Amaan\Downloads\screen-aware\.screen-aware --env SCREEN_AWARE_ENV_FILE=C:\Users\Amaan\Downloads\screen-aware\.env screen-aware -- C:\Users\Amaan\Downloads\screen-aware\.venv\Scripts\python.exe -m screen_aware.mcp_server
claude mcp list
```

Inside Claude Code, run `/mcp` to check connection status.

## Gemini CLI

Command form:

```powershell
gemini mcp add -s user -e SCREEN_AWARE_DATA_DIR=C:\Users\Amaan\Downloads\screen-aware\.screen-aware -e SCREEN_AWARE_ENV_FILE=C:\Users\Amaan\Downloads\screen-aware\.env screen-aware C:\Users\Amaan\Downloads\screen-aware\.venv\Scripts\python.exe -m screen_aware.mcp_server
gemini mcp list
```

Manual `~/.gemini/settings.json` or project `.gemini/settings.json`:

```json
{
  "mcpServers": {
    "screen-aware": {
      "command": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.venv\\Scripts\\python.exe",
      "args": ["-m", "screen_aware.mcp_server"],
      "cwd": "C:\\Users\\Amaan\\Downloads\\screen-aware",
      "env": {
        "SCREEN_AWARE_DATA_DIR": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.screen-aware",
        "SCREEN_AWARE_ENV_FILE": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.env"
      },
      "timeout": 120000,
      "trust": false
    }
  }
}
```

If Gemini reports disconnected, run `gemini trust` in the project folder and then `/mcp list`.

## Google Antigravity

Open Antigravity Agent pane, use the menu, open MCP Servers, Manage MCP Servers, View raw config. Edit:

```json
{
  "mcpServers": {
    "screen-aware": {
      "command": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.venv\\Scripts\\python.exe",
      "args": ["-m", "screen_aware.mcp_server"],
      "cwd": "C:\\Users\\Amaan\\Downloads\\screen-aware",
      "env": {
        "SCREEN_AWARE_DATA_DIR": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.screen-aware",
        "SCREEN_AWARE_ENV_FILE": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.env",
        "SCREEN_AWARE_AGENT_NAME": "Your agent"
      }
    }
  }
}
```

The raw config path is `~/.gemini/antigravity/mcp_config.json`.

## OpenCode

Add to `opencode.json` in your project or `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "screen-aware": {
      "type": "local",
      "command": [
        "C:\\Users\\Amaan\\Downloads\\screen-aware\\.venv\\Scripts\\python.exe",
        "-m",
        "screen_aware.mcp_server"
      ],
      "enabled": true,
      "environment": {
        "SCREEN_AWARE_DATA_DIR": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.screen-aware",
        "SCREEN_AWARE_ENV_FILE": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.env"
      },
      "timeout": 120000
    }
  }
}
```

Prompt with `use screen-aware` if OpenCode does not pick it automatically.

## VS Code Copilot

Add `.vscode/mcp.json` in the target project or open the user MCP config through the Command Palette:

```json
{
  "servers": {
    "screenAware": {
      "type": "stdio",
      "command": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.venv\\Scripts\\python.exe",
      "args": ["-m", "screen_aware.mcp_server"],
      "envFile": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.env",
      "env": {
        "SCREEN_AWARE_DATA_DIR": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.screen-aware",
        "SCREEN_AWARE_ENV_FILE": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.env"
      }
    }
  }
}
```

Use Copilot Chat in Agent mode, enable the server in the tools picker, then ask it to use Screen-Aware context.

## VS Code Cline

Open Cline MCP settings from the MCP Servers icon or edit `cline_mcp_settings.json`:

```json
{
  "mcpServers": {
    "screen-aware": {
      "command": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.venv\\Scripts\\python.exe",
      "args": ["-m", "screen_aware.mcp_server"],
      "env": {
        "SCREEN_AWARE_DATA_DIR": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.screen-aware",
        "SCREEN_AWARE_ENV_FILE": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.env"
      },
      "disabled": false,
      "alwaysAllow": []
    }
  }
}
```

Cline CLI also supports:

```powershell
cline mcp add screen-aware -- C:\Users\Amaan\Downloads\screen-aware\.venv\Scripts\python.exe -m screen_aware.mcp_server
```

If you use the CLI command, edit the generated server entry and add `SCREEN_AWARE_DATA_DIR` and `SCREEN_AWARE_ENV_FILE`.

## Generic MCP Clients

Use this shape for clients that understand the common `mcpServers` JSON format:

```json
{
  "mcpServers": {
    "screen-aware": {
      "command": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.venv\\Scripts\\python.exe",
      "args": ["-m", "screen_aware.mcp_server"],
      "cwd": "C:\\Users\\Amaan\\Downloads\\screen-aware",
      "env": {
        "SCREEN_AWARE_DATA_DIR": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.screen-aware",
        "SCREEN_AWARE_ENV_FILE": "C:\\Users\\Amaan\\Downloads\\screen-aware\\.env"
      }
    }
  }
}
```

## Useful Agent Prompt

```text
Use the Screen-Aware MCP tools before changing code. First call screen_aware_get_capture_status. Then call screen_aware_analyze_screen_context with my visible issue. Use the visual/audio evidence to identify the bug, inspect the relevant files, patch the smallest fix, and run the app's tests or build.
```

## Reference Links

- OpenAI Codex MCP: https://developers.openai.com/learn/docs-mcp
- Claude Code MCP: https://code.claude.com/docs/en/mcp
- Gemini CLI MCP: https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md
- Antigravity MCP: https://antigravity.google/docs/mcp
- OpenCode MCP: https://dev.opencode.ai/docs/mcp-servers/
- VS Code MCP config: https://code.visualstudio.com/docs/copilot/reference/mcp-configuration
- Cline MCP: https://docs.cline.bot/mcp/adding-mcp-servers-from-github
