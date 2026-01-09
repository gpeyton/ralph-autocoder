#!/usr/bin/env python3
"""Ralph CLI - AI Coding Loop Manager."""

import argparse
import sys

from .commands import (
    cmd_delete,
    cmd_init,
    cmd_list,
    cmd_projects,
    cmd_run,
    cmd_spec,
    cmd_start,
    cmd_status,
)


def main():
    """Main entry point for the CLI."""
    parser = argparse.ArgumentParser(
        prog="ralph",
        description="Ralph CLI - AI Coding Loop Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  ralph start                      Interactive flow (NEW or resume recent)
  ralph start ./my-project         Work on existing project
  ralph start . -p "new-feature"   Start new project in workspace
  ralph init ./new-project         Create new project
  ralph run ./project -n 10        Run 10 iterations
  ralph run . --once               Single iteration
  ralph run . --resume             Resume paused loop
  ralph run . -p "my-project"      Run specific project
  ralph run . --type test-coverage Run test coverage loop
  ralph spec . "auth system"       Gather requirements (plan mode)
  ralph spec . "fix bugs" -p bugs  Spec into named project
  ralph projects .                 List projects for target
  ralph list                       List recent targets
  ralph status .                   Show project status

Controls during loop:
  [p] pause                        Pause after current iteration (can resume)
  [s] stop                         Stop loop (state not saved)
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # start command
    start_parser = subparsers.add_parser("start", help="Interactive start flow")
    start_parser.add_argument("project", nargs="?", help="Target path (optional)")
    start_parser.add_argument("--project", "-p", dest="project_name", help="Named project within target")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize a new Ralph project")
    init_parser.add_argument("name", help="Project path (relative or absolute)")

    # list command
    subparsers.add_parser("list", help="List Ralph targets")

    # projects command (list projects within a target)
    projects_parser = subparsers.add_parser("projects", help="List projects for a target")
    projects_parser.add_argument("target", help="Target path (relative, absolute, or '.' for cwd)")

    # run command
    run_parser = subparsers.add_parser("run", help="Run Ralph loop on a project")
    run_parser.add_argument("project", help="Target path (relative, absolute, or '.' for cwd)")
    run_parser.add_argument("--project", "-p", dest="project_name", help="Named project within target")
    run_parser.add_argument("--once", "-1", action="store_true", help="Run single iteration")
    run_parser.add_argument("--iterations", "-n", type=int, help="Number of iterations (default: 10)")
    run_parser.add_argument("--docker", "-d", action="store_true", help="Run in Docker sandbox")
    run_parser.add_argument("--resume", "-r", action="store_true", help="Resume from paused state")
    run_parser.add_argument(
        "--type", "-t",
        choices=["default", "test-coverage", "linting", "duplication", "entropy"],
        default="default",
        help="Loop type (default: default)"
    )

    # spec command
    spec_parser = subparsers.add_parser("spec", help="Run spec discovery for requirements")
    spec_parser.add_argument("project", help="Target path (relative, absolute, or '.' for cwd)")
    spec_parser.add_argument("topic", nargs="?", help="Topic to specify (or use --file)")
    spec_parser.add_argument("--project", "-p", dest="project_name", help="Named project within target")
    spec_parser.add_argument("--file", "-f", help="Requirements file as context")
    spec_parser.add_argument("--max-iterations", "-n", type=int, help="Max iterations (default: 20)")
    spec_parser.add_argument("--existing", "-e", action="store_true", help="Analyze existing codebase first")

    # status command
    status_parser = subparsers.add_parser("status", help="Show project status")
    status_parser.add_argument("project", help="Target path (relative, absolute, or '.' for cwd)")
    status_parser.add_argument("--project", "-p", dest="project_name", help="Named project within target")

    # delete command
    delete_parser = subparsers.add_parser("delete", help="Remove project from registry")
    delete_parser.add_argument("project", nargs="?", help="Target path (or use --all)")
    delete_parser.add_argument("--project", "-p", dest="project_name", help="Named project to delete")
    delete_parser.add_argument("--all", "-a", action="store_true", help="Clear entire registry")
    delete_parser.add_argument("--files", action="store_true", help="Also delete project files")
    delete_parser.add_argument("--force", "-f", action="store_true", help="Skip confirmation")

    args = parser.parse_args()

    if not args.command:
        return cmd_start(args)

    commands = {
        "start": cmd_start,
        "init": cmd_init,
        "list": cmd_list,
        "projects": cmd_projects,
        "run": cmd_run,
        "spec": cmd_spec,
        "status": cmd_status,
        "delete": cmd_delete,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
