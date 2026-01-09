You are running a lint error fixing loop.

## Context Files (in Ralph Workspace)
- PRD.json: Contains `verify.lint` command
- progress.txt: Log of fixes
- failures.md: Log of repeated issues (if exists)

**IMPORTANT**: These files are in the Ralph workspace directory (see File Locations above).
The target project directory is for CODE CHANGES ONLY.

## Goal

Fix all lint errors reported by `verify.lint`.

## Process

1. **Run** `verify.lint` to get current errors
2. **Pick ONE error** - start with most severe or most common
3. **Fix** the error properly (not just suppressing)
4. **Verify** the fix doesn't break tests
5. **Append** to progress.txt: error type, how fixed

## Fix Priority

1. **Errors** - Breaking issues
2. **Warnings** - Potential problems
3. **Style** - Consistency issues

## Self-Monitoring

- **Same error recurring** → The fix isn't addressing root cause
- **Fix causes new errors** → Step back, understand the impact
- **Suppressing warnings** → Only if truly false positive, document why

## Rules

- **ONE ERROR PER ITERATION**
- Fix properly, don't just suppress
- Verify tests still pass after fix

## Adding Guardrails

If a lint error reveals a pattern:
- Add a guardrail to prevent it recurring
- Example: If you find missing type annotations, add "Always add explicit types"

## Completion

If `verify.lint` passes with no errors:
<promise>COMPLETE</promise>

If stuck:
<promise>GUTTER</promise>
