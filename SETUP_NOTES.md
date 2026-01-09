# System Setup and Troubleshooting Notes

This document records unique setup requirements and fixes discovered during the development of Ralph Autocoder to ensure smooth operation of the AI coding loop.

## 1. NPM Cache Permissions (EPERM Fix)

If you encounter `EPERM` errors or hangs when running `npx` commands (like Playwright MCP), it is likely due to root-owned files in your npm cache.

### The Problem
Running npm with `sudo` in the past can leave files in `~/.npm` that your user cannot modify, causing background processes to hang silently.

### The Fix
Run the following command to restore ownership to your user:

```bash
sudo chown -R $(id -u):$(id -g) ~/.npm
```

## 2. Playwright MCP Configuration

To prevent the agent from hanging on browser installation prompts or encountering permission issues in system directories, follow these configuration standards.

### Explicit Browser Selection
Always specify a portable browser (like `chromium`) instead of relying on system defaults (like `google-chrome`), which may trigger `sudo` installation prompts.

### Local User Data Directory
Configure the MCP server to use a local profile directory within the project to avoid `EPERM` issues in system cache folders.

### Working Configuration (`.ralph/mcp.json`)
```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": [
        "@playwright/mcp@latest",
        "--viewport-size",
        "1280x720",
        "--browser",
        "chromium",
        "--user-data-dir",
        "./.ralph/playwright-profile"
      ]
    }
  }
}
```

## 3. Environment Inheritance

The Claude Agent SDK must inherit the system `PATH` and other environment variables to correctly find system-installed tools like `node`, `npm`, and browser binaries.

Ensure your agent implementation merges `os.environ` into the MCP server configurations:

```python
# example in ralph/agent/client.py
if "env" not in mcp_servers[name]:
    mcp_servers[name]["env"] = {}
mcp_servers[name]["env"].update(os.environ)
```
