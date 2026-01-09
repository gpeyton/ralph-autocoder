You are implementing a project based on the PRD (human-in-the-loop mode).

## Your Task

1. **Read** {prd_path} to understand requirements.
2. **Read** {progress_path} to see what's done.
3. **Check** the `guardrails` array in {prd_path}.
4. **Find** the next task in {prd_path} where `"status": "pending"`.
5. **Implement** the task in TARGET project until ALL success criteria are satisfied.
6. **Verify** using the commands in `verify` section.
7. **Update** {prd_path}: change task `"status": "pending"` to `"status": "done"`.
8. **Append** to {progress_path} what you accomplished.

**CRITICAL RULES**:
- **NEVER** read or write PRD.json or progress.txt from the TARGET directory.
- **NEVER** copy PRD.json or any workspace files to the target directory.
- Always use the FULL ABSOLUTE PATHS shown in the File Locations section below.
- The target directory is for CODE CHANGES ONLY.

## Rules

- **ONE TASK** - Complete one task fully before stopping
- **ALL CRITERIA MUST PASS** - Every success criterion must be satisfied
- **RUN VERIFICATION** - Run `verify.test`, `verify.lint` before marking done
- **FOLLOW GUARDRAILS** - Check triggers, follow instructions

## Testing

Run verification commands before marking any task done:
1. `verify.lint` - Check code style
2. `verify.test` - Run tests
3. `verify.build` - Build (if applicable)

### Browser/Web UI Testing

For browser UI tasks, use **MCP Playwright tools** (NOT shell commands).

**Common tools:** `browser_navigate`, `browser_click`, `browser_type`, `browser_fill_form`, `browser_take_screenshot`, `browser_snapshot`, `browser_evaluate`

Example: `browser_navigate` → `browser_type`/`browser_fill_form` → `browser_click` → `browser_take_screenshot`

## Self-Monitoring

Watch for warning patterns:
- **Same file edited 3+ times** → Step back, reconsider approach
- **Same test failing 2+ times** → Check assumptions
- **Large changes (10+ files)** → Verify scope is correct

## Completion Signal

If stuck on the same issue 3+ times, output:
<promise>GUTTER</promise>

Then describe what's blocking you.
