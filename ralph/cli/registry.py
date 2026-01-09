"""Project registry for tracking Ralph projects across locations."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_ralph_root() -> Path:
    """Get the root directory of the ralph-autocoder installation.
    
    Returns:
        Path to the ralph-autocoder package directory
    """
    # This file is at ralph/cli/registry.py, so go up 2 levels
    return Path(__file__).parent.parent.parent


def get_registry_path() -> Path:
    """Get the path to the project registry file.
    
    Returns:
        Path to <ralph-autocoder>/.ralph/projects.json
    """
    ralph_dir = get_ralph_root() / ".ralph"
    ralph_dir.mkdir(exist_ok=True)
    return ralph_dir / "projects.json"


def get_global_config_path() -> Path:
    """Get the path to the global settings.json file.
    
    Returns:
        Path to <ralph-autocoder>/.ralph/settings.json
    """
    ralph_dir = get_ralph_root() / ".ralph"
    ralph_dir.mkdir(exist_ok=True)
    return ralph_dir / "settings.json"


def load_registry() -> dict:
    """Load the project registry."""
    registry_path = get_registry_path()
    if registry_path.exists():
        try:
            return json.loads(registry_path.read_text())
        except json.JSONDecodeError:
            return {"projects": {}}
    return {"projects": {}}


def save_registry(registry: dict) -> None:
    """Save the project registry."""
    registry_path = get_registry_path()
    registry_path.write_text(json.dumps(registry, indent=2))


def register_project(project_path: Path, name: Optional[str] = None) -> None:
    """Register a project in the registry.
    
    Args:
        project_path: Absolute path to the project
        name: Optional project name (defaults to directory name)
    """
    registry = load_registry()
    
    project_path = project_path.resolve()
    path_str = str(project_path)
    
    registry["projects"][path_str] = {
        "name": name or project_path.name,
        "path": path_str,
        "registered": datetime.now().isoformat(),
        "last_run": None,
    }
    
    save_registry(registry)


def unregister_project(project_path: Path) -> bool:
    """Remove a project from the registry.
    
    Returns:
        True if project was found and removed
    """
    registry = load_registry()
    path_str = str(project_path.resolve())
    
    if path_str in registry["projects"]:
        del registry["projects"][path_str]
        save_registry(registry)
        return True
    return False


def update_last_run(project_path: Path) -> None:
    """Update the last run timestamp for a project."""
    registry = load_registry()
    path_str = str(project_path.resolve())
    
    if path_str in registry["projects"]:
        registry["projects"][path_str]["last_run"] = datetime.now().isoformat()
        save_registry(registry)


def get_all_projects() -> list[dict]:
    """Get all registered projects.
    
    Returns:
        List of project info dicts, sorted by last_run (most recent first)
    """
    registry = load_registry()
    projects = list(registry["projects"].values())
    
    # Filter out projects that no longer exist
    valid_projects = []
    for proj in projects:
        if Path(proj["path"]).exists():
            valid_projects.append(proj)
    
    # Sort by last_run (None values last)
    valid_projects.sort(
        key=lambda p: p.get("last_run") or "0000",
        reverse=True
    )
    
    return valid_projects


def get_project(project_path: Path) -> Optional[dict]:
    """Get info for a specific project.
    
    Returns:
        Project info dict or None if not registered
    """
    registry = load_registry()
    path_str = str(project_path.resolve())
    return registry["projects"].get(path_str)


def is_registered(project_path: Path) -> bool:
    """Check if a project is registered."""
    return get_project(project_path) is not None


def clear_registry() -> int:
    """Clear all projects from the registry.
    
    Returns:
        Number of projects cleared
    """
    registry = load_registry()
    count = len(registry["projects"])
    registry["projects"] = {}
    save_registry(registry)
    return count


# =============================================================================
# Loop State Management
# =============================================================================

def save_loop_state(
    project_path: Path,
    iteration: int,
    total_iterations: int,
    loop_type: str,
    status: str = "paused",
    current_task_id: str = "",
    current_task: str = "",
) -> None:
    """Save the current loop state for a project.
    
    Args:
        project_path: Path to the project
        iteration: Current iteration number
        total_iterations: Total planned iterations
        loop_type: Type of loop (default, test-coverage, etc.)
        status: Loop status (paused, stopped)
        current_task_id: Current task ID being worked on
        current_task: Current task description
    """
    registry = load_registry()
    path_str = str(project_path.resolve())
    
    if path_str not in registry["projects"]:
        return
    
    registry["projects"][path_str]["loop_state"] = {
        "iteration": iteration,
        "total_iterations": total_iterations,
        "loop_type": loop_type,
        "status": status,
        "current_task_id": current_task_id,
        "current_task": current_task,
        "saved_at": datetime.now().isoformat(),
    }
    
    save_registry(registry)


def get_loop_state(project_path: Path) -> Optional[dict]:
    """Get saved loop state for a project.
    
    Returns:
        Loop state dict or None if no saved state
    """
    registry = load_registry()
    path_str = str(project_path.resolve())
    
    if path_str not in registry["projects"]:
        return None
    
    return registry["projects"][path_str].get("loop_state")


def clear_loop_state(project_path: Path) -> bool:
    """Clear saved loop state for a project.
    
    Returns:
        True if state was cleared
    """
    registry = load_registry()
    path_str = str(project_path.resolve())
    
    if path_str not in registry["projects"]:
        return False
    
    if "loop_state" in registry["projects"][path_str]:
        del registry["projects"][path_str]["loop_state"]
        save_registry(registry)
        return True
    
    return False


def has_saved_loop_state(project_path: Path) -> bool:
    """Check if a project has saved loop state.
    
    Returns:
        True if there's a saved loop state
    """
    state = get_loop_state(project_path)
    return state is not None and state.get("status") == "paused"


# =============================================================================
# Workspace Management (Named Projects)
# =============================================================================

def get_workspaces_root(target_path: Path) -> Path:
    """Get the root workspace directory for a target.
    
    Args:
        target_path: The target project path
        
    Returns:
        Path to <ralph-autocoder>/.ralph/workspaces/<target-name>/
    """
    ralph_root = get_ralph_root()
    ralph_dir = ralph_root / ".ralph" / "workspaces"
    ralph_dir.mkdir(parents=True, exist_ok=True)
    
    target_name = target_path.resolve().name
    workspace_root = ralph_dir / target_name
    workspace_root.mkdir(exist_ok=True)
    
    return workspace_root


def generate_project_name(target_path: Path) -> str:
    """Generate a timestamped project name.
    
    Format: <target>_YYYY-MM-DD_HH-MM-SS
    Example: py_2026-01-08_14-30-45
    """
    target_name = target_path.resolve().name
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{target_name}_{timestamp}"


def get_workspace_dir(target_path: Path, project_name: Optional[str] = None) -> Path:
    """Get the Ralph workspace directory for a specific project.
    
    Structure: <ralph>/.ralph/workspaces/<target>/<project>/
    
    Args:
        target_path: The target project path (e.g., ~/code/my-app)
        project_name: Named project within this target (e.g., "add-auth")
                     If None, uses the active project or generates new timestamped name
        
    Returns:
        Path to the project's workspace directory
    """
    workspace_root = get_workspaces_root(target_path)
    
    # Get project name (explicit, active, or generate new)
    if project_name is None:
        project_name = get_active_project(target_path)
        if project_name is None:
            # Generate timestamped name for new projects
            project_name = generate_project_name(target_path)
            set_active_project(target_path, project_name)
    
    # Sanitize project name for filesystem
    safe_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in project_name)
    safe_name = safe_name.strip("-_") or generate_project_name(target_path)
    
    workspace = workspace_root / safe_name
    workspace.mkdir(exist_ok=True)
    
    return workspace


def get_active_project(target_path: Path) -> Optional[str]:
    """Get the currently active project name for a target.
    
    Returns:
        Project name or None if no active project set
    """
    workspace_root = get_workspaces_root(target_path)
    active_file = workspace_root / ".active"
    
    if active_file.exists():
        return active_file.read_text().strip() or None
    return None


def set_active_project(target_path: Path, project_name: str) -> None:
    """Set the active project for a target.
    
    Args:
        target_path: The target project path
        project_name: Project name to make active
    """
    workspace_root = get_workspaces_root(target_path)
    active_file = workspace_root / ".active"
    active_file.write_text(project_name)


def list_workspace_projects(target_path: Path) -> list[dict]:
    """List all projects for a target workspace.
    
    Returns:
        List of project info dicts with name, path, has_prd, has_progress
    """
    workspace_root = get_workspaces_root(target_path)
    active_project = get_active_project(target_path)
    
    projects = []
    for item in sorted(workspace_root.iterdir()):
        if item.is_dir() and not item.name.startswith("."):
            prd_path = item / "PRD.json"
            progress_path = item / "progress.txt"
            
            # Count tasks if PRD exists
            total_tasks = 0
            done_tasks = 0
            if prd_path.exists():
                try:
                    import json
                    prd = json.loads(prd_path.read_text())
                    tasks = prd.get("tasks", [])
                    total_tasks = len(tasks)
                    done_tasks = sum(1 for t in tasks if t.get("status") == "done")
                except Exception:
                    pass
            
            projects.append({
                "name": item.name,
                "path": str(item),
                "is_active": item.name == active_project,
                "has_prd": prd_path.exists(),
                "has_progress": progress_path.exists(),
                "total_tasks": total_tasks,
                "done_tasks": done_tasks,
            })
    
    return projects


def get_spec_session_path(target_path: Path, project_name: Optional[str] = None) -> Path:
    """Get the path to the spec session file for a project.
    
    Spec sessions are stored in Ralph's workspace, NOT in the target project.
    
    Returns:
        Path to <ralph>/.ralph/workspaces/<target>/<project>/spec-session.md
    """
    workspace = get_workspace_dir(target_path, project_name)
    return workspace / "spec-session.md"


def get_draft_prd_path(target_path: Path, project_name: Optional[str] = None) -> Path:
    """Get the path to the draft PRD file.
    
    Draft PRDs are stored in Ralph's workspace until approved.
    
    Returns:
        Path to <ralph>/.ralph/workspaces/<target>/<project>/PRD-draft.json
    """
    workspace = get_workspace_dir(target_path, project_name)
    return workspace / "PRD-draft.json"


def has_spec_session(target_path: Path, project_name: Optional[str] = None) -> bool:
    """Check if a spec session exists for the project."""
    return get_spec_session_path(target_path, project_name).exists()


def has_draft_prd(target_path: Path, project_name: Optional[str] = None) -> bool:
    """Check if a draft PRD exists for the project."""
    return get_draft_prd_path(target_path, project_name).exists()


def get_mcp_config_path() -> Path:
    """Get the path to the global MCP configuration file.
    
    Returns:
        Path to <ralph>/.ralph/mcp.json
    """
    ralph_dir = get_ralph_root() / ".ralph"
    ralph_dir.mkdir(exist_ok=True)
    return ralph_dir / "mcp.json"


def load_mcp_config(target_path: Optional[Path] = None) -> dict:
    """Load MCP server configuration.
    
    Searches for MCP config in order:
    1. Global Ralph config at <ralph>/.ralph/mcp.json
    2. Default Playwright MCP server config
    
    Args:
        target_path: Optional target project directory (ignored for now)
        
    Returns:
        Dict of MCP servers configuration for ClaudeAgentOptions
    """
    mcp_servers = {}
    
    # 1. Check global Ralph MCP config
    global_mcp = get_mcp_config_path()
    if global_mcp.exists():
        try:
            config = json.loads(global_mcp.read_text())
            mcp_servers.update(config.get("mcpServers", {}))
        except (json.JSONDecodeError, Exception):
            pass
    
    # 2. If no config found, use default Playwright MCP server via npx
    if not mcp_servers:
        mcp_servers = {
            "playwright": {
                "command": "npx",
                "args": ["@playwright/mcp@latest", "--viewport-size", "1280x720"],
            }
        }
    
    return mcp_servers


def get_usage_path() -> Path:
    """Get the path to the usage tracking file.
    
    Returns:
        Path to <ralph-autocoder>/.ralph/usage.json
    """
    ralph_dir = get_ralph_root() / ".ralph"
    ralph_dir.mkdir(exist_ok=True)
    return ralph_dir / "usage.json"


def track_usage(message_count: int = 1) -> None:
    """Track message usage per day in Ralph.
    
    Args:
        message_count: Number of messages to add to today's count
    """
    usage_path = get_usage_path()
    today = datetime.now().strftime("%Y-%m-%d")
    
    usage = {}
    if usage_path.exists():
        try:
            usage = json.loads(usage_path.read_text())
        except (json.JSONDecodeError, Exception):
            pass
            
    if today not in usage:
        usage[today] = 0
    usage[today] += message_count
    
    usage_path.write_text(json.dumps(usage, indent=2))


def get_today_usage() -> int:
    """Get total messages used today in Ralph.
    
    Returns:
        Number of messages used today
    """
    usage_path = get_usage_path()
    today = datetime.now().strftime("%Y-%m-%d")
    
    if usage_path.exists():
        try:
            usage = json.loads(usage_path.read_text())
            return usage.get(today, 0)
        except (json.JSONDecodeError, Exception):
            pass
    return 0


def create_default_mcp_config() -> None:
    """Create the default MCP configuration file if it doesn't exist."""
    mcp_path = get_mcp_config_path()
    if not mcp_path.exists():
        default_config = {
            "mcpServers": {
                "playwright": {
                    "command": "npx",
                    "args": ["@playwright/mcp@latest", "--viewport-size", "1280x720"],
                }
            }
        }
        mcp_path.write_text(json.dumps(default_config, indent=2))
