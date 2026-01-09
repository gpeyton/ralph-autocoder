You are running a code quality improvement loop.

## Context Files (in Ralph Workspace)
- PRD.json: Contains verify commands
- progress.txt: Log of improvements
- failures.md: Log of repeated issues (if exists)

**IMPORTANT**: These files are in the Ralph workspace directory (see File Locations above).
The target project directory is for CODE CHANGES ONLY.

## Goal

Reduce code entropy - improve clarity, simplicity, maintainability.

## Process

1. **Scan** for code smells (see list below)
2. **Pick ONE issue** - prioritize by impact on maintainability
3. **Refactor** to improve clarity, simplicity, or correctness
4. **Verify** with tests - don't break anything
5. **Append** to progress.txt: what improved, why

## Code Smells to Target

| Smell | Detection | Fix |
|-------|-----------|-----|
| Long functions | >50 lines | Split into focused functions |
| Deep nesting | 3+ levels | Extract, early return |
| Magic values | Hardcoded numbers/strings | Named constants |
| Dead code | Unreachable, unused | Delete |
| Missing types | `any`, implicit types | Add explicit types |
| Unclear names | Abbreviations, vague | Rename descriptively |
| Outdated patterns | Old syntax, deprecated | Modernize |
| Duplicate code | Similar blocks | Extract shared function |

## Self-Monitoring

- **Same smell in multiple places** → Consider a systematic fix
- **Refactor breaks tests** → Stop, understand the coupling
- **Endless improvements** → Set a stopping point, not everything needs fixing

## Rules

- **ONE SMELL PER ITERATION**
- Don't refactor working code just for style
- Focus on clarity and maintainability
- Verify tests still pass

## Adding Guardrails

If a refactor reveals a pattern that caused the smell:
- Add a guardrail to PRD.json
- Example: If you find repeated dead code, add a guardrail "Delete unused code immediately"

## Completion

If codebase is reasonably clean (no high-impact smells):
<promise>COMPLETE</promise>

If stuck:
<promise>GUTTER</promise>
