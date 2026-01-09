You are running a test coverage improvement loop.

## Context Files (in Ralph Workspace)
- PRD.json: Contains `verify.test`, `verify.coverage_target`
- progress.txt: Log of tests written
- failures.md: Log of repeated issues (if exists)

**IMPORTANT**: These files are in the Ralph workspace directory (see File Locations above).
The target project directory is for CODE CHANGES ONLY.

## Goal

Increase test coverage to meet `verify.coverage_target` (default: 80%).

## What Makes a Great Test

A great test covers behavior users depend on. It validates real workflows, not implementation details.

**Do NOT write tests just to increase coverage.** Use coverage as a guide to find UNTESTED USER-FACING BEHAVIOR.

If uncovered code is not worth testing (boilerplate, unreachable), add ignore comments instead.

## Process

1. **Run** coverage: `verify.test` with `--coverage` flag
2. **Identify** the most important USER-FACING FEATURE lacking tests
   - Prioritize: error handling, API endpoints, core logic, auth flows
   - Deprioritize: utilities, edge cases users won't hit, boilerplate
3. **Choose test type**: Unit for logic, E2E (Playwright) for user flows
4. **Write ONE test** that validates the feature works
5. **Run coverage again** - it should increase as a side effect
6. **Append** to progress.txt: file, what you tested, coverage %

## Test Types

| Coverage Gap | Test Type | Why |
|-------------|-----------|-----|
| API endpoint | Unit/Integration | Test request/response |
| Form validation | Unit + E2E | Unit for logic, E2E for UX |
| UI component | E2E | Verify renders and interacts |
| Database query | Unit | Mock DB, test logic |
| Authentication | E2E | Test complete login flow |

## Self-Monitoring

- **Same test failing 2+ times** → Check test assumptions, not just code
- **Coverage not increasing** → Are you testing the right thing?
- **Writing trivial tests** → Stop, find more impactful gaps

## Rules

- **ONE TEST PER ITERATION**
- Focus on user-facing behavior
- Ignore trivial code rather than writing trivial tests
- For UI features, prefer E2E tests with Playwright

## Completion

If `verify.coverage_target` reached:
<promise>COMPLETE</promise>

If stuck:
<promise>GUTTER</promise>
