# Ralph Autocoder

AI coding loop manager powered by **Claude Agent SDK**. Define requirements with testable success criteria, let Claude implement them one task at a time.

## Install

```bash
# Prerequisites: Claude Code CLI
curl -fsSL https://claude.ai/install.sh | bash
export ANTHROPIC_API_KEY=your-api-key

# System Setup: Fix npm permissions if needed (see SETUP_NOTES.md)
sudo chown -R $(id -u):$(id -g) ~/.npm

# Install Ralph
cd ralph-autocoder
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Optional: Playwright browsers for UI testing (see Appendix A)
npx playwright install
```

Detailed setup requirements and troubleshooting for Playwright MCP and terminal locking can be found in [SETUP_NOTES.md](./SETUP_NOTES.md).


## Quick Start

```bash
ralph start                    # Interactive: NEW or resume recent project
ralph start ./my-project       # Work on existing project at path
ralph init ./new-project       # Create new project (non-interactive)
ralph run . -n 10              # Run 10 iterations
ralph run . --docker           # Run in Docker sandbox (recommended for AFK)
```

## Commands

| Command | Description |
|---------|-------------|
| `ralph start` | Interactive: NEW or resume recent |
| `ralph start <path>` | Work on existing project |
| `ralph init <path>` | Create new project |
| `ralph spec <path> "topic"` | Gather requirements |
| `ralph run <path> -n N` | Run N iterations |
| `ralph run <path> --once` | Single iteration |
| `ralph run <path> --docker` | Run in Docker sandbox |
| `ralph run <path> --type X` | Run specific loop type |
| `ralph list` | List recent projects |
| `ralph status <path>` | Show status |
| `ralph delete <path>` | Remove from registry (keeps files) |
| `ralph delete <path> --files` | Remove from registry and delete files |
| `ralph delete --all` | Clear entire registry |

## Loop Types

| Type | Use When |
|------|----------|
| `default` | Building features from PRD tasks |
| `test-coverage` | Writing tests for untested user-facing behavior |
| `linting` | Fixing lint errors (one per iteration) |
| `duplication` | Extracting shared code from copy-paste patterns |
| `entropy` | Cleaning up code smells (long functions, magic numbers, dead code) |

```bash
ralph run . -n 10                       # default (PRD tasks)
ralph run . -n 10 --type test-coverage  # after features are built
ralph run . -n 10 --type linting        # quick cleanup pass
ralph run . -n 10 --type duplication    # refactoring phase
ralph run . -n 10 --type entropy        # deep quality pass
```

## PRD Format

Each task has **testable success criteria**:

```json
{
  "name": "my-project",
  "max_iterations": 50,
  "verify": {
    "test": "npm test",
    "lint": "npm run lint"
  },
  "phases": [
    {
      "name": "Foundation",
      "tasks": [
        {
          "id": "1.1",
          "description": "Set up project",
          "done": false,
          "criteria": [
            "package.json exists",
            "npm install succeeds",
            "npm test passes"
          ]
        }
      ]
    }
  ],
  "guardrails": [
    "Run tests before marking task done",
    "Commit after each task"
  ]
}
```

**Key fields:**
- `criteria`: Array of testable conditions (ALL must pass)
- `verify`: Commands to validate work
- `guardrails`: Rules the agent must follow (learned lessons)

## Completion Signals

| Signal | Meaning |
|--------|---------|
| `<promise>COMPLETE</promise>` | All tasks done |
| `<promise>GUTTER</promise>` | Agent is stuck |

When GUTTER occurs, check `progress.txt` for what's blocking.

## Docker Sandbox

For AFK mode, run in isolation:

```bash
ralph run . -n 20 --docker
```

Requires Docker Desktop 4.50+.

## How It Works

Each iteration:
1. Read `PRD.json` and `progress.txt`
2. Check `guardrails` and follow them
3. Find next task with `done: false`
4. Work until ALL `criteria` are satisfied
5. Run `verify` commands
6. Set `done: true`, update `progress.txt`
7. Commit changes
8. Output `COMPLETE` when all tasks done

## License

MIT

---

## Appendix A: Playwright MCP Setup

MCP Playwright enables Ralph to verify browser UI by navigating pages, clicking elements, and taking screenshots.

### Quick Setup

```bash
# Install Playwright browsers (one-time setup)
npx playwright install
```

That's it! Ralph uses `npx @playwright/mcp@latest` which runs the Playwright MCP server directly without requiring a global install.

### Configuration

**Ralph MCP config** (`.ralph/mcp.json`) - created automatically:
```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--viewport-size", "1280x720"]
    }
  }
}
```

**Claude Code MCP config** (`~/.config/claude/mcp.json`) - optional, for direct Claude Code usage:
```json
{
  "servers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--viewport-size", "1280x720"]
    }
  }
}
```

### Troubleshooting

**npx not found?** Ensure Node.js is installed:
```bash
node --version  # Should show v18+ 
npm --version   # Should show npm
```

**Browsers not installed?** Run:
```bash
npx playwright install
```

**Sanity test in Claude Code:**
> Use the Playwright MCP to open https://example.com and return the page title.

### Notes

- Uses `npx @playwright/mcp@latest` - always runs latest version
- No global npm install required
- Browsers cached in `~/Library/Caches/ms-playwright` (macOS) or `~/.cache/ms-playwright` (Linux)
- Restart Claude Code after config changes
