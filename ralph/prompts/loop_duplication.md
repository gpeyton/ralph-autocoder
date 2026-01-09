You are running a code duplication reduction loop.

## Context Files (in Ralph Workspace)
- PRD.json: Contains verify commands
- progress.txt: Log of refactors
- failures.md: Log of repeated issues (if exists)

**IMPORTANT**: These files are in the Ralph workspace directory (see File Locations above).
The target project directory is for CODE CHANGES ONLY.

## Goal

Find and eliminate code duplication by extracting shared utilities.

## Process

1. **Scan** for duplicate or near-duplicate code blocks
2. **Pick ONE duplication** - prioritize by size and frequency
3. **Extract** into a shared function, component, or utility
4. **Replace** all instances with the shared version
5. **Verify** tests still pass
6. **Append** to progress.txt: what was duplicated, where extracted

## Duplication Types

| Type | Example | Fix |
|------|---------|-----|
| Identical code | Same 10+ lines in 2 files | Extract function |
| Similar logic | Same pattern, different data | Extract with parameters |
| Copy-paste API calls | Same fetch pattern | Create API utility |
| Repeated validation | Same checks in multiple places | Validation utility |
| Duplicate components | Similar UI elements | Shared component |

## Self-Monitoring

- **Extraction breaks things** → The code wasn't truly duplicate
- **Over-abstracting** → If it needs 5 parameters, maybe keep separate
- **Premature extraction** → Only extract if 2+ real usages exist

## Rules

- **ONE DUPLICATION PER ITERATION**
- Only extract genuinely duplicate code
- Don't over-abstract (keep it simple)
- Verify all usages work after extraction

## Completion

If no significant duplication remains:
<promise>COMPLETE</promise>

If stuck:
<promise>GUTTER</promise>
