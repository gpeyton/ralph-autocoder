"""Command implementations for Ralph CLI."""

import asyncio
import os
import shutil
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from .utils import (
    Colors,
    get_templates_dir,
    resolve_project_path,
    prompt_choice,
    prompt_choice_async,
    prompt_confirm,
    prompt_input,
    prompt_input_async,
    ThinkingSpinner,
)
from .registry import (
    register_project,
    unregister_project,
    update_last_run,
    get_all_projects,
    is_registered,
    clear_registry,
    save_loop_state,
    get_loop_state,
    clear_loop_state,
    has_saved_loop_state,
    get_workspace_dir,
    get_spec_session_path,
    has_spec_session,
    get_active_project,
    set_active_project,
    list_workspace_projects,
    get_workspaces_root,
    generate_project_name,
    load_mcp_config,
    get_global_config_path,
)
from .config import load_project_config, save_project_config


# Fallback print functions for non-TUI contexts
def print_error(message: str):
    print(f"{Colors.RED}x {message}{Colors.NC}")

def print_success(message: str):
    print(f"{Colors.GREEN}v {message}{Colors.NC}")

def print_info(message: str):
    print(f"{Colors.CYAN}i {message}{Colors.NC}")

def print_step(step: int, total: int, message: str):
    print(f"{Colors.BOLD}[{step}/{total}]{Colors.NC} {message}")

def print_header(title: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}┌{'─' * 54}┐{Colors.NC}")
    print(f"{Colors.BOLD}{Colors.CYAN}│{Colors.NC}  {title:<52}{Colors.BOLD}{Colors.CYAN}│{Colors.NC}")
    print(f"{Colors.BOLD}{Colors.CYAN}└{'─' * 54}┘{Colors.NC}\n")


def _validate_mcp_servers(mcp_servers: dict) -> None:
    """Validate MCP server configuration and print status.
    
    Checks if the MCP server commands are available and warns if not.
    For npx-based servers, just validates npx is available.
    """
    import shutil
    
    for name, config in mcp_servers.items():
        command = config.get("command", "")
        args = config.get("args", [])
        if not command:
            continue
        
        # Check if command exists
        if shutil.which(command):
            # For npx commands, show what package will be used
            if command == "npx" and args:
                package = args[0] if args else "unknown"
                print_info(f"MCP server '{name}' will use: npx {package}")
            else:
                print_info(f"MCP server '{name}' available ({command})")
        else:
            print(f"{Colors.YELLOW}⚠ MCP server '{name}' command not found: {command}{Colors.NC}")
            if command == "npx":
                print(f"  Install Node.js/npm to enable npx")
            else:
                print(f"  This MCP server may not be available")


def cmd_start(args):
    """Interactive start flow - plain text + questionary (no Rich panels)."""
    print_header("Ralph - AI Coding Loop")
    
    # If path provided, work with that project
    if getattr(args, 'project', None):
        target_dir = resolve_project_path(args.project)
        if not target_dir.exists():
            print_error(f"Directory not found: {target_dir}")
            return 1
        project_name = getattr(args, 'project_name', None)
        
        # If -p specified, use that project (continue or create)
        if project_name:
            return _flow_existing_project(target_dir, project_name)
        
        # No -p specified - check if there are existing projects
        existing_projects = list_workspace_projects(target_dir)
        existing_with_prd = [p for p in existing_projects if p["has_prd"]]
        
        if existing_with_prd:
            # Ask: continue existing or start new?
            print_info(f"Found {len(existing_with_prd)} existing project(s) for {target_dir.name}")
            choice = prompt_choice(
                "What would you like to do?",
                ["Start NEW project", "CONTINUE existing project"]
            )
            if choice == 0:
                # New project
                new_project_name = generate_project_name(target_dir)
                return _flow_existing_project(target_dir, new_project_name, is_new_project=True)
            else:
                # Continue - pick which one
                if len(existing_with_prd) == 1:
                    proj = existing_with_prd[0]
                    set_active_project(target_dir, proj["name"])
                    return _flow_existing_project(target_dir, proj["name"])
                else:
                    # Multiple projects - let user pick
                    proj_choices = [f"{p['name']} ({p['done_tasks']}/{p['total_tasks']} tasks)" for p in existing_with_prd]
                    proj_choice = prompt_choice("Select project to continue:", proj_choices)
                    proj = existing_with_prd[proj_choice]
                    set_active_project(target_dir, proj["name"])
                    return _flow_existing_project(target_dir, proj["name"])
        else:
            # No existing projects - create new
            new_project_name = generate_project_name(target_dir)
            return _flow_existing_project(target_dir, new_project_name, is_new_project=True)
    
    choices = [
        "NEW PROJECT (create new directory)",
        "EXISTING PROJECT (work in existing directory)",
        "CONTINUE PROJECT (resume a Ralph project)",
    ]
    
    choice = prompt_choice("What would you like to do?", choices)
    
    if choice == 0:
        # New project from scratch
        return _flow_new_project()
    elif choice == 1:
        # Existing directory - ALWAYS create new project
        project_path = prompt_input("Target directory path", ".")
        target_dir = resolve_project_path(project_path)
        if not target_dir.exists():
            print_error(f"Directory not found: {target_dir}")
            return 1
        # Force new project by generating timestamped name
        new_project_name = generate_project_name(target_dir)
        return _flow_existing_project(target_dir, project_name=new_project_name, is_new_project=True)
    else:
        # Continue with an old Ralph project
        return _flow_continue_project()


def _prompt_for_requirements(project_dir: Path, default_topic: str = "") -> tuple[str, str]:
    """Prompt user for requirements - either a topic or a file.
    
    Returns:
        (topic, requirements_file) - one will be empty
    """
    input_choice = prompt_choice(
        "How do you want to provide requirements?",
        ["Describe what to build (interactive Q&A)", "Provide a requirements file"]
    )
    
    if input_choice == 0:
        topic = prompt_input("What do you want to build/change?", default_topic)
        return (topic, "")
    else:
        file_path = prompt_input("Path to requirements file")
        if not file_path:
            print_error("File path is required")
            return ("", "")
        
        # Resolve relative to project dir
        req_path = Path(file_path)
        if not req_path.is_absolute():
            req_path = project_dir / req_path
        
        if not req_path.exists():
            print_error(f"File not found: {req_path}")
            return ("", "")
        
        topic = f"Requirements from {req_path.name}"
        return (topic, str(req_path))


def _flow_new_project():
    """Flow for creating a new project."""
    print()
    print_step(1, 3, "Create New Project")
    
    project_path = prompt_input("Project path (relative or absolute)", "./my-project")
    if not project_path:
        print_error("Project path is required")
        return 1
    
    project_dir = resolve_project_path(project_path)
    project_name = project_dir.name
    
    if project_dir.exists():
        print_error(f"Directory already exists: {project_dir}")
        return 1
    
    print()
    print_info(f"Creating project at: {project_dir}")
    
    _create_project_structure(project_dir, project_name)
    print_success(f"Project created at {project_dir}")
    
    # Step 2: Spec discovery
    print()
    print_step(2, 3, "Requirements Discovery")
    
    if prompt_confirm("Run spec discovery to gather requirements?"):
        topic, req_file = _prompt_for_requirements(project_dir, default_topic=project_name)
        if topic:
            os.chdir(project_dir)
            return _run_spec_agent(project_dir, topic, existing=False, requirements_file=req_file)
    else:
        print_info("Skipping spec. Edit PRD.json manually.")
    
    # Step 3: Start loop
    print()
    print_step(3, 3, "Start Coding Loop")
    
    if prompt_confirm("Start the coding loop now?"):
        iterations = prompt_input("How many iterations?", "10")
        
        # Offer loop type selection
        type_choice = prompt_choice(
            "Loop type:",
            ["default (PRD tasks)", "test-coverage", "linting", "duplication", "entropy"]
        )
        loop_types = ["default", "test-coverage", "linting", "duplication", "entropy"]
        loop_type = loop_types[type_choice]
        
        os.chdir(project_dir)
        return _run_loop_agent(project_dir, int(iterations), loop_type=loop_type, start_iteration=1)
    else:
        print()
        print_info(f"To start later:")
        print(f"  cd {project_dir}")
        print(f"  ralph run . -n 10")
    
    return 0


def _flow_continue_project():
    """Flow for continuing an existing Ralph project."""
    # Get all registered targets
    targets = get_all_projects()
    
    if not targets:
        print_info("No Ralph projects found yet.")
        print()
        choice = prompt_choice(
            "What would you like to do?",
            ["Create NEW PROJECT", "Work in EXISTING directory", "Cancel"]
        )
        if choice == 0:
            return _flow_new_project()
        elif choice == 1:
            project_path = prompt_input("Target directory path", ".")
            target_dir = resolve_project_path(project_path)
            if not target_dir.exists():
                print_error(f"Directory not found: {target_dir}")
                return 1
            new_project_name = generate_project_name(target_dir)
            return _flow_existing_project(target_dir, new_project_name, is_new_project=True)
        return 0
    
    # Build a list of all projects across all targets
    all_projects = []
    for target_info in targets:
        target_path = Path(target_info["path"])
        if not target_path.exists():
            continue
        
        # List projects for this target
        projects = list_workspace_projects(target_path)
        for proj in projects:
            if proj["has_prd"]:  # Only show projects with PRD
                all_projects.append({
                    "target": target_path,
                    "target_name": target_info["name"],
                    "project": proj,
                })
    
    if not all_projects:
        print_info("No Ralph projects with PRDs found yet.")
        print_info("(Projects need a PRD to be continuable)")
        print()
        choice = prompt_choice(
            "What would you like to do?",
            ["Create NEW PROJECT", "Work in EXISTING directory", "Cancel"]
        )
        if choice == 0:
            return _flow_new_project()
        elif choice == 1:
            project_path = prompt_input("Target directory path", ".")
            target_dir = resolve_project_path(project_path)
            if not target_dir.exists():
                print_error(f"Directory not found: {target_dir}")
                return 1
            new_project_name = generate_project_name(target_dir)
            return _flow_existing_project(target_dir, new_project_name, is_new_project=True)
        return 0
    
    # Build choices
    choices = []
    for item in all_projects:
        proj = item["project"]
        done = proj["done_tasks"]
        total = proj["total_tasks"]
        pct = int((done / total * 100)) if total > 0 else 0
        choices.append(f"{proj['name']} ({item['target_name']}) - {done}/{total} tasks ({pct}%)")
    
    choices.append("Cancel")
    
    choice = prompt_choice("Select a project to continue:", choices)
    
    if choice == len(choices) - 1:
        return 0  # Cancel
    
    selected = all_projects[choice]
    target_dir = selected["target"]
    project_name = selected["project"]["name"]
    
    # Set as active and flow into existing project
    set_active_project(target_dir, project_name)
    return _flow_existing_project(target_dir, project_name)


def _flow_existing_project(target_dir: Path, project_name: str = None, is_new_project: bool = False):
    """Flow for working with an existing project.
    
    Args:
        target_dir: Path to the target directory
        project_name: Named project (uses active or creates new if None)
        is_new_project: If True, this is a brand new project (skip checking for existing PRD)
    """
    is_ralph_target = is_registered(target_dir)
    
    # If project_name specified, set it as active
    if project_name:
        set_active_project(target_dir, project_name)
    
    # Get workspace (will create timestamped project if none exists)
    workspace_dir = get_workspace_dir(target_dir, project_name)
    active_project = get_active_project(target_dir)
    
    # For new projects, we don't check for existing PRD - start fresh
    if is_new_project:
        has_prd = False
        _has_spec_session = False
    else:
        has_prd = (workspace_dir / "PRD.json").exists() or (target_dir / "PRD.json").exists()
        _has_spec_session = has_spec_session(target_dir, project_name)
    
    # Step 1: Initialize Ralph if needed
    if is_ralph_target and has_prd and not is_new_project:
        print()
        print_info(f"Target: {target_dir}")
        print_info(f"Project: {active_project}")
        print_success("Continuing Ralph project")
        _show_quick_status(target_dir, project_name)
        
        # Ensure it's in registry
        if not is_registered(target_dir):
            register_project(target_dir)
    else:
        print()
        print_step(1, 3, "Initialize Ralph")
        print_info(f"Target: {target_dir}")
        print_info(f"Project: {active_project} (new)")
        print_info("Initializing Ralph...")
        _init_existing_project(target_dir)
        print_success("Ralph initialized")
    
    # Step 2: Spec Discovery (always offer this)
    print()
    print_step(2, 3, "Requirements Discovery")
    
    if _has_spec_session:
        # Existing spec session - ask what to do
        spec_file = get_spec_session_path(target_dir, project_name)
        print_info(f"Spec session found: {spec_file}")
        choice = prompt_choice(
            "Spec session already exists. What do you want to do?",
            [
                "Continue with existing spec (skip to coding loop)",
                "Start fresh spec discovery (overwrite existing)",
                "View/edit spec manually, then run loop"
            ]
        )
        
        if choice == 1:
            # Overwrite - run spec discovery
            topic, req_file = _prompt_for_requirements(target_dir)
            if topic:
                os.chdir(target_dir)
                return _run_spec_agent(target_dir, topic, existing=True, requirements_file=req_file, project_name=project_name)
        elif choice == 2:
            # Manual edit - spec is in workspace, not target project
            print_info(f"Edit spec at: {spec_file}")
            print_info("Then run: ralph run . -n 10")
            return 0
        # choice == 0: Continue to loop
    else:
        # No spec session - offer to create one
        if prompt_confirm("Run spec discovery to define requirements?"):
            topic, req_file = _prompt_for_requirements(target_dir)
            if topic:
                os.chdir(target_dir)
                return _run_spec_agent(target_dir, topic, existing=True, requirements_file=req_file, project_name=project_name)
        else:
            print_info("Skipping spec. Edit PRD.json manually to define tasks.")
    
    # Step 3: Run loop
    print()
    print_step(3, 3, "Start Coding Loop")
    
    # Check for saved loop state
    saved_state = get_loop_state(target_dir)
    start_iteration = 1
    default_iterations = "10"
    loop_type = "default"
    
    if saved_state and saved_state.get("status") == "paused":
        # Offer to resume
        print_info(f"Found paused loop at iteration {saved_state.get('iteration')}/{saved_state.get('total_iterations')}")
        if saved_state.get("current_task"):
            task_id = saved_state.get("current_task_id", "")
            task_desc = saved_state.get("current_task", "")
            if task_id:
                print_info(f"Last task: [{task_id}] {task_desc}")
        
        resume_choice = prompt_choice(
            "What would you like to do?",
            ["Resume from where you left off", "Start fresh (discard saved state)", "Skip for now"]
        )
        
        if resume_choice == 0:
            # Resume
            start_iteration = saved_state.get("iteration", 1)
            iterations = saved_state.get("total_iterations", 10)
            loop_type = saved_state.get("loop_type", "default")
            os.chdir(target_dir)
            return _run_loop_agent(target_dir, iterations, loop_type=loop_type, start_iteration=start_iteration, project_name=project_name)
        elif resume_choice == 1:
            # Start fresh
            clear_loop_state(target_dir)
            # Fall through to normal loop start
        else:
            # Skip
            print_info("To start later:")
            print(f"  ralph run {target_dir} -n 10")
            return 0
    
    if prompt_confirm("Start the coding loop?"):
        iterations = prompt_input("How many iterations?", default_iterations)
        
        # Offer loop type selection
        type_choice = prompt_choice(
            "Loop type:",
            ["default (PRD tasks)", "test-coverage", "linting", "duplication", "entropy"]
        )
        loop_types = ["default", "test-coverage", "linting", "duplication", "entropy"]
        loop_type = loop_types[type_choice]
        
        os.chdir(target_dir)
        return _run_loop_agent(target_dir, int(iterations), loop_type=loop_type, start_iteration=start_iteration, project_name=project_name)
    else:
        print()
        print_info("To start later:")
        print(f"  ralph run {target_dir} -n 10")
    
    return 0




def _show_quick_status(target_dir: Path, project_name: str = None):
    """Show quick status of a project from its workspace."""
    import json
    
    # Read from workspace, not target directory
    workspace_dir = get_workspace_dir(target_dir, project_name)
    
    prd_path = workspace_dir / "PRD.json"
    if prd_path.exists():
        try:
            prd = json.loads(prd_path.read_text())
            tasks = prd.get("tasks", [])
            total_tasks = len(tasks)
            done_tasks = sum(1 for t in tasks if t.get("status") == "done")
            print(f"  Tasks: {done_tasks}/{total_tasks} complete")
            
            # Show next pending task
            for task in sorted(tasks, key=lambda t: t.get("priority", 999)):
                if task.get("status") != "done":
                    print(f"  Next: [{task.get('id', '?')}] {task.get('name', 'Unknown')}")
                    break
        except Exception:
            pass
    
    progress_path = workspace_dir / "progress.txt"
    if progress_path.exists():
        entries = [l for l in progress_path.read_text().splitlines() if l.strip() and not l.startswith("#")]
        print(f"  Progress entries: {len(entries)}")


def _create_project_structure(project_dir: Path, project_name: str):
    """Create a new project with ONLY code-related files.
    
    IMPORTANT: PRD.json, progress.txt, etc. are created in the Ralph workspace
    (~/.ralph/workspaces/<project>/), NOT in the target project directory.
    The target project should only contain actual code.
    """
    import json
    
    project_dir.mkdir(parents=True)
    (project_dir / "src").mkdir()
    
    # Create .gitignore (no Ralph metadata files to ignore since they're in workspace)
    (project_dir / ".gitignore").write_text("""*.bak
.DS_Store
__pycache__/
*.pyc
.venv/
venv/
""")
    
    # Create Ralph files in WORKSPACE, not target directory
    workspace_dir = get_workspace_dir(project_dir)
    _ensure_workspace_files(workspace_dir, project_dir)
    
    # Init git
    subprocess.run(["git", "init", "-q"], cwd=project_dir, check=True)
    subprocess.run(["git", "add", "."], cwd=project_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"Initial setup for {project_name}"], cwd=project_dir, check=True)
    
    # Register project in global registry
    register_project(project_dir, project_name)


def _init_existing_project(cwd: Path):
    """Initialize Ralph in an existing directory.
    
    IMPORTANT: PRD.json, progress.txt, etc. are created in the Ralph workspace
    (~/.ralph/workspaces/<project>/), NOT in the target project directory.
    The target project should only contain actual code.
    """
    # Create Ralph files in WORKSPACE, not target directory
    workspace_dir = get_workspace_dir(cwd)
    _ensure_workspace_files(workspace_dir, cwd)
    
    # Register project in global registry
    register_project(cwd)


def _create_spec_session_file(workspace_dir: Path, topic: str, requirements_content: str = ""):
    """Create the spec session file in the Ralph workspace.
    
    Args:
        workspace_dir: Ralph workspace directory (~/.ralph/workspaces/<project>/)
        topic: The topic being specified
        requirements_content: Optional requirements file content
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)
    spec_file = workspace_dir / "spec-session.md"
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    content = f"""# Specification: {topic}

Started: {timestamp}

## Codebase Context

(Summary of existing codebase, if applicable)

## Input Requirements

{requirements_content if requirements_content else "(None provided)"}

## Questions Asked

## Answers Received

## Requirements

### Must Have
- 

### Should Have
- 

### Out of Scope
- 

## Technical Notes

## Summary
"""
    spec_file.write_text(content)
    return spec_file


def _ensure_workspace_files(workspace_dir: Path, project_dir: Path):
    """Ensure PRD.json and progress.txt exist in the Ralph workspace.
    
    IMPORTANT: These files should NEVER be in the target project directory.
    All Ralph metadata lives in ~/.ralph/workspaces/<project>/
    
    Args:
        workspace_dir: Ralph workspace directory
        project_dir: Target project directory (for naming only)
    """
    import json
    
    workspace_dir.mkdir(parents=True, exist_ok=True)
    templates_dir = get_templates_dir()
    
    # Create PRD.json in workspace if not exists
    prd_path = workspace_dir / "PRD.json"
    if not prd_path.exists():
        prd_template = templates_dir / "PRD.json"
        prd_data = json.loads(prd_template.read_text())
        prd_data["name"] = project_dir.name
        prd_data["created"] = datetime.now().strftime("%Y-%m-%d")
        prd_data["updated"] = datetime.now().strftime("%Y-%m-%d")
        prd_path.write_text(json.dumps(prd_data, indent=2))
    
    # Create progress.txt in workspace if not exists
    progress_path = workspace_dir / "progress.txt"
    if not progress_path.exists():
        shutil.copy(templates_dir / "progress.txt", progress_path)
    
    # Create failures.md in workspace if not exists
    failures_path = workspace_dir / "failures.md"
    if not failures_path.exists():
        shutil.copy(templates_dir / "failures.md", failures_path)


def _run_once_agent(target_dir: Path, project_name: str = None) -> int:
    """Run a single iteration using the agent SDK (human-in-the-loop mode).
    
    IMPORTANT: All Ralph files (PRD.json, progress.txt) are in the workspace directory,
    NOT in the target project. The target project is for code changes only.
    
    Args:
        target_dir: Path to the target project (where code changes are made)
        project_name: Named project within workspace (uses active if None)
    """
    import json
    from ..agent import RalphAgent, AgentDisplay
    from ..prompts import get_once_prompt
    
    # Update last run timestamp
    update_last_run(target_dir)
    
    # Get workspace directory - this is where PRD.json and progress.txt live
    workspace_dir = get_workspace_dir(target_dir, project_name)
    
    # Ensure workspace has required files
    _ensure_workspace_files(workspace_dir, target_dir)
    
    # Load PRD to get task info for display
    prd_path = workspace_dir / "PRD.json"
    total_tasks = 0
    current_task_info = None
    
    if prd_path.exists():
        try:
            prd = json.loads(prd_path.read_text())
            tasks = prd.get("tasks", [])
            total_tasks = len(tasks)
            done_count = sum(1 for t in tasks if t.get("status") == "done")
            
            for task in sorted(tasks, key=lambda t: t.get("priority", 999)):
                if task.get("status") != "done":
                    current_task_info = {
                        "id": task.get("id", "?"),
                        "name": task.get("name", "Unknown"),
                        "done": done_count,
                        "total": total_tasks,
                    }
                    break
        except Exception:
            pass
    
    # Load project configuration first
    config = load_project_config()
    model = config.get("loop_model", "claude-3-5-sonnet-20241022")
    context_limit = config.get("context_limit", 200000)
    rotate_threshold = config.get("rotate_threshold", 0.8)
    auto_gutter = config.get("auto_gutter", True)
    plan_limit = config.get("plan_messages_limit", 225)
    
    display = AgentDisplay(total_iterations=1, mode="once", plan_limit=plan_limit)
    
    # Set task info in display
    if current_task_info:
        task_label = f"[{current_task_info['done'] + 1}/{current_task_info['total']}] {current_task_info['name']}"
        display.set_task(task_label, current_task_info['id'])
    
    # Create log file for raw output
    log_file = workspace_dir / "raw_output.log"
    
    # Load MCP server configuration
    mcp_servers = load_mcp_config(target_dir)
    if mcp_servers:
        _validate_mcp_servers(mcp_servers)
    
    agent = RalphAgent(
        cwd=target_dir, 
        display=display, 
        log_file=log_file, 
        mcp_servers=mcp_servers,
        model=model,
        context_limit=context_limit,
        rotate_threshold=rotate_threshold,
        auto_gutter=auto_gutter
    )
    prompt = get_once_prompt(
        workspace_dir=str(workspace_dir),
        target_dir=str(target_dir),
    )
    
    display.start()
    try:
        result = asyncio.run(agent.run_once(prompt))
    finally:
        agent._close_log()
        display.stop()
        display.print_summary()
    
    return 0 if result.success else 1


async def _run_loop_agent_async(
    target_dir: Path,
    iterations: int,
    loop_type: str = "default",
    start_iteration: int = 1,
    project_name: str = None,
) -> int:
    """Async implementation of the AFK loop using the agent SDK with pause/stop support.
    
    This is the core async implementation. Use _run_loop_agent() for sync contexts.
    
    IMPORTANT: All Ralph files (PRD.json, progress.txt) are in the workspace directory,
    NOT in the target project. The target project is for code changes only.
    
    Args:
        target_dir: Path to the target project (where code changes are made)
        iterations: Number of iterations to run
        loop_type: Type of loop (default, test-coverage, etc.)
        start_iteration: Starting iteration number (for resume)
        project_name: Named project within workspace (uses active if None)
    """
    import json
    from ..agent import RalphAgent, AgentDisplay, keyboard_listener
    from ..prompts import get_loop_prompt
    
    # Update last run timestamp
    update_last_run(target_dir)
    
    # Get workspace directory - this is where PRD.json and progress.txt live
    workspace_dir = get_workspace_dir(target_dir, project_name)
    
    # Ensure workspace has required files
    _ensure_workspace_files(workspace_dir, target_dir)
    
    # Update PRD with selected iterations
    if iterations:
        try:
            prd_path = workspace_dir / "PRD.json"
            if prd_path.exists():
                prd = json.loads(prd_path.read_text())
                prd["max_iterations"] = iterations
                prd_path.write_text(json.dumps(prd, indent=2))
        except Exception as e:
            print_error(f"Failed to update PRD.json: {e}")
    
    # Clear any previous saved state since we're starting fresh or resuming
    if start_iteration == 1:
        clear_loop_state(target_dir)
    
    # Load PRD to get task info for display
    prd_path = workspace_dir / "PRD.json"
    total_tasks = 0
    current_task_info = None
    
    if prd_path.exists():
        try:
            prd = json.loads(prd_path.read_text())
            tasks = prd.get("tasks", [])
            total_tasks = len(tasks)
            done_count = sum(1 for t in tasks if t.get("status") == "done")
            
            # Find next pending task (lowest priority number)
            for task in sorted(tasks, key=lambda t: t.get("priority", 999)):
                if task.get("status") != "done":
                    current_task_info = {
                        "id": task.get("id", "?"),
                        "name": task.get("name", "Unknown"),
                        "done": done_count,
                        "total": total_tasks,
                    }
                    break
        except Exception:
            pass
    
    # Load project configuration first
    config = load_project_config()
    model = config.get("loop_model", "claude-3-5-sonnet-20241022")
    context_limit = config.get("context_limit", 200000)
    rotate_threshold = config.get("rotate_threshold", 0.8)
    auto_gutter = config.get("auto_gutter", True)
    plan_limit = config.get("plan_messages_limit", 225)
    
    display = AgentDisplay(total_iterations=iterations, mode="loop", plan_limit=plan_limit)
    
    # Set initial task info in display
    if current_task_info:
        task_label = f"[{current_task_info['done'] + 1}/{current_task_info['total']}] {current_task_info['name']}"
        display.set_task(task_label, current_task_info['id'])
    
    # Create log file for raw output
    log_file = workspace_dir / "raw_output.log"
    
    # Load MCP server configuration
    mcp_servers = load_mcp_config(target_dir)
    if mcp_servers:
        _validate_mcp_servers(mcp_servers)
    
    agent = RalphAgent(
        cwd=target_dir, 
        display=display, 
        log_file=log_file, 
        mcp_servers=mcp_servers,
        model=model,
        context_limit=context_limit,
        rotate_threshold=rotate_threshold,
        auto_gutter=auto_gutter
    )
    prompt = get_loop_prompt(
        loop_type=loop_type,
        workspace_dir=str(workspace_dir),
        target_dir=str(target_dir),
    )
    
    # Callback to save state and update task info after each iteration
    def on_iteration_complete(iteration: int, result):
        # Re-read PRD to get updated task info
        try:
            if prd_path.exists():
                prd = json.loads(prd_path.read_text())
                tasks = prd.get("tasks", [])
                done_count = sum(1 for t in tasks if t.get("status") == "done")
                total = len(tasks)
                
                # Find next pending task
                for task in sorted(tasks, key=lambda t: t.get("priority", 999)):
                    if task.get("status") != "done":
                        task_label = f"[{done_count + 1}/{total}] {task.get('name', 'Unknown')}"
                        display.set_task(task_label, task.get("id", ""))
                        break
                else:
                    display.set_task(f"[{done_count}/{total}] All tasks complete!", "")
        except Exception:
            pass
    
    # Start keyboard listener as background task
    keyboard_task = asyncio.create_task(keyboard_listener(display))
    
    display.start()
    try:
        try:
            results, exit_reason = await agent.run_loop(
                prompt,
                max_iterations=iterations,
                start_iteration=start_iteration,
                loop_type=loop_type,
                on_iteration_complete=on_iteration_complete,
            )
        finally:
            keyboard_task.cancel()
            try:
                await keyboard_task
            except asyncio.CancelledError:
                pass
    finally:
        agent._close_log()
        display.stop()
        display.print_summary()
    
    # Handle exit reason
    if exit_reason == "paused":
        # Save state for resume
        current_iteration = start_iteration + len(results) - 1
        save_loop_state(
            target_dir,
            iteration=current_iteration + 1,  # Next iteration to run
            total_iterations=iterations,
            loop_type=loop_type,
            status="paused",
            current_task_id=display.stats.current_task_id,
            current_task=display.stats.current_task,
        )
        print()
        print_info(f"Paused at iteration {current_iteration}/{iterations}")
        print_info(f"Resume with: ralph run {target_dir} --resume")
        return 0
    
    elif exit_reason == "stopped":
        # Clear state - user doesn't want to continue
        clear_loop_state(target_dir)
        print()
        print_info(f"Stopped after {len(results)} iterations")
        return 0
    
    elif exit_reason == "complete":
        clear_loop_state(target_dir)
        print_success(f"PRD complete after {len(results)} iterations!")
        return 0
    
    elif exit_reason == "gutter":
        clear_loop_state(target_dir)
        print_error(f"GUTTER after {len(results)} iterations - agent is stuck")
        print_info("Check progress.txt for details on what's blocking")
        return 1
    
    elif exit_reason == "error":
        # Save state in case user wants to resume
        current_iteration = start_iteration + len(results) - 1
        save_loop_state(
            target_dir,
            iteration=current_iteration + 1,
            total_iterations=iterations,
            loop_type=loop_type,
            status="paused",  # Allow resume after error
            current_task_id=display.stats.current_task_id,
            current_task=display.stats.current_task,
        )
        print()
        print_error(f"Error at iteration {current_iteration}")
        print_info(f"Resume with: ralph run {target_dir} --resume")
        return 1
    
    else:  # max_iterations
        clear_loop_state(target_dir)
        print_info(f"Completed {len(results)} iterations. PRD may not be fully complete.")
        return 0


def _run_loop_agent(
    target_dir: Path,
    iterations: int,
    loop_type: str = "default",
    start_iteration: int = 1,
    project_name: str = None,
) -> int:
    """Run the AFK loop using the agent SDK with pause/stop support.
    
    This is a sync wrapper around _run_loop_agent_async for use in sync contexts.
    For async contexts, use _run_loop_agent_async directly.
    """
    return asyncio.run(_run_loop_agent_async(
        target_dir, iterations, loop_type, start_iteration, project_name
    ))


def _run_spec_agent(
    target_dir: Path,
    topic: str,
    existing: bool = False,
    requirements_file: str = "",
    max_iterations: int = 20,  # Kept for API compatibility, not used in conversation mode
    project_name: str = None,
) -> int:
    """Run spec discovery as an interactive conversation with Claude.
    
    This uses a continuous conversation model (not iterations):
    1. Claude reads from target project (read-only)
    2. Claude asks questions
    3. User responds
    4. Claude writes spec to Ralph workspace (NOT target project)
    5. Repeat until spec is complete
    6. Ask user for approval before moving to coding loop
    
    IMPORTANT: No files are created in the target project during spec discovery.
    All spec files are stored in ~/.ralph/workspaces/<target>/<project>/
    """
    from ..prompts import get_spec_prompt
    
    # Update last run timestamp
    update_last_run(target_dir)
    
    # If project_name specified, set it as active
    if project_name:
        set_active_project(target_dir, project_name)
    
    # Get workspace directory - this is where spec files are stored
    workspace_dir = get_workspace_dir(target_dir, project_name)
    
    # Create spec session file in WORKSPACE (not target project)
    requirements_content = ""
    if requirements_file:
        req_path = Path(requirements_file)
        if req_path.exists():
            requirements_content = req_path.read_text()
    
    _create_spec_session_file(workspace_dir, topic, requirements_content)
    
    # Update PRD with max iterations if specified
    if max_iterations:
        try:
            prd_path = workspace_dir / "PRD.json"
            if prd_path.exists():
                prd = json.loads(prd_path.read_text())
                prd["max_iterations"] = max_iterations
                prd_path.write_text(json.dumps(prd, indent=2))
        except Exception:
            pass
    
    # Get the spec prompt - tell Claude about the workspace restriction
    prompt = get_spec_prompt(
        topic=topic,
        existing=existing,
        has_requirements_file=bool(requirements_content),
        workspace_dir=str(workspace_dir),
    )
    
    # Run the conversation
    return asyncio.run(_run_spec_conversation_async(target_dir, workspace_dir, prompt, topic, project_name))


async def _run_spec_conversation_async(
    target_dir: Path,
    workspace_dir: Path,
    prompt: str,
    topic: str,
    project_name: str = None,
) -> int:
    """Async implementation of spec conversation with streaming output like Claude CLI.
    
    Args:
        target_dir: Target project (read-only during spec discovery)
        workspace_dir: Ralph workspace (spec files written here)
        prompt: The spec prompt
        topic: The topic being discussed
        project_name: Named project within workspace (for display)
    """
    from ..agent import SpecSession
    
    # Load project configuration
    config = load_project_config()
    model = config.get("spec_model", "claude-opus-4-5-20251101")
    context_limit = config.get("context_limit", 200000)
    
    # Pure streaming session - no Rich panels
    # Target project is read-only, workspace is for spec files
    session = SpecSession(target_dir, workspace_dir, display=None, model=model, context_limit=context_limit)
    
    active_project = project_name or get_active_project(target_dir) or "default"
    
    print()
    print(f"{Colors.DIM}Starting spec discovery for: {topic}{Colors.NC}")
    print(f"{Colors.DIM}Project: {active_project}{Colors.NC}")
    print(f"{Colors.DIM}Workspace: {workspace_dir}{Colors.NC}")
    print(f"{Colors.DIM}Target (read-only): {target_dir}{Colors.NC}")
    print(f"{Colors.DIM}─" * 60 + f"{Colors.NC}")
    print()
    
    # Track last output type for formatting (no newlines between consecutive tools)
    last_was_tool = False
    spinner = ThinkingSpinner("Claude is thinking")
    first_chunk_received = False
    
    def print_text(text: str):
        """Print text, adding newline before if last output was a tool."""
        nonlocal last_was_tool, first_chunk_received
        if not first_chunk_received:
            spinner.stop()
            first_chunk_received = True
        if last_was_tool:
            print()  # Add newline after tool block before text
        print(text, end="", flush=True)
        last_was_tool = False
    
    def print_tool(name: str, input_str: str):
        """Print tool use, adding newline before if last output was text."""
        nonlocal last_was_tool, first_chunk_received
        if not first_chunk_received:
            spinner.stop()
            first_chunk_received = True
        if not last_was_tool:
            print()  # Add newline before first tool in a block
        print(f"{Colors.DIM}[{name}] {input_str}{Colors.NC}", flush=True)
        last_was_tool = True
    
    def on_chunk(chunk: dict):
        """Handle incoming chunk - stop spinner and dispatch to printer."""
        if chunk["type"] == "text":
            print_text(chunk["content"])
        elif chunk["type"] == "tool":
            print_tool(chunk.get("name", "Tool"), chunk.get("input", ""))
        elif chunk["type"] == "response_done":
            # Response complete
            pass
    
    try:
        # Start the conversation - stream Claude's initial response
        try:
            spinner.start()
            first_chunk_received = False
            async for chunk in session.start(prompt):
                if chunk["type"] == "error":
                    spinner.stop()
                    print_error(chunk["content"])
                    return 1
                on_chunk(chunk)
            spinner.stop()
        except Exception as e:
            spinner.stop()
            print_error(f"Error starting session: {e}")
            traceback.print_exc()
            return 1
        
        # Main conversation loop
        while not session.is_complete():
            # Print separator and prompt for input
            print()
            print(f"{Colors.DIM}─" * 60 + f"{Colors.NC}")
            print(f"{Colors.DIM}Type 'done' or 'quit' to finish early.{Colors.NC}")
            print()
            
            try:
                user_input = await prompt_input_async("Your response")
            except (KeyboardInterrupt, EOFError):
                print("\n\nSpec discovery interrupted.")
                break
            
            # Reset tracking for new response
            last_was_tool = False
            first_chunk_received = False
            
            # Check for exit signals
            if user_input.lower() in ("quit", "exit", "done", "q", ""):
                print()
                spinner.start()
                async for chunk in session.send_message("I'm done. Please summarize what we have and complete the spec."):
                    on_chunk(chunk)
                spinner.stop()
                break
            
            print()
            print(f"{Colors.DIM}─" * 60 + f"{Colors.NC}")
            print()
            
            # Send user's response and stream Claude's reply
            try:
                spinner.start()
                async for chunk in session.send_message(user_input):
                    if chunk["type"] == "error":
                        spinner.stop()
                        print_error(chunk["content"])
                        return 1
                    on_chunk(chunk)
                spinner.stop()
            except Exception as e:
                spinner.stop()
                print_error(f"Error sending message: {e}")
                traceback.print_exc()
                return 1
        
        # Print summary
        stats = session.get_stats()
        print()
        print(f"{Colors.DIM}─" * 60 + f"{Colors.NC}")
        print()
        print(f"{Colors.BOLD}{Colors.GREEN}Spec Discovery Complete{Colors.NC}")
        print(f"  Exchanges: {stats['num_exchanges']}")
        print(f"  Tokens: {stats['input_tokens']:,} in / {stats['output_tokens']:,} out")
        print(f"  Cost: ${stats['cost_usd']:.4f}")
        
        spec_file = workspace_dir / "spec-session.md"
        print()
        print_success(f"Spec saved to: {spec_file}")
        print()
        
        # Ask user what to do next
        print(f"{Colors.DIM}─" * 60 + f"{Colors.NC}")
        print()
        next_choice = await prompt_choice_async(
            "What would you like to do next?",
            [
                "Continue refining the spec (more Q&A)",
                "View/edit the spec file manually",
                "Start the coding loop",
                "Exit (save spec for later)"
            ]
        )
        
        if next_choice == 0:
            # Continue refining - recursive call
            print()
            print(f"{Colors.CYAN}Continuing spec refinement...{Colors.NC}")
            # Re-run conversation with existing context
            return await _continue_spec_refinement(session, workspace_dir, target_dir)
        
        elif next_choice == 1:
            # View/edit manually
            print()
            print_info(f"Spec file: {spec_file}")
            print_info("Edit the file, then run: ralph run <project> -n 10")
            return 0
        
        elif next_choice == 2:
            # Start coding loop
            print()
            iterations = await prompt_input_async("How many iterations?", "10")
            type_choice = await prompt_choice_async(
                "Loop type:",
                ["default (PRD tasks)", "test-coverage", "linting", "duplication", "entropy"]
            )
            loop_types = ["default", "test-coverage", "linting", "duplication", "entropy"]
            loop_type = loop_types[type_choice]
            
            # Now we can write to the target project
            os.chdir(target_dir)
            # Use async version since we're already in an event loop
            return await _run_loop_agent_async(target_dir, int(iterations), loop_type=loop_type, start_iteration=1, project_name=project_name)
        
        else:
            # Exit
            print()
            print_info(f"Spec saved to: {spec_file}")
            print_info("To continue later: ralph start")
            return 0
        
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        traceback.print_exc()
        return 1
        
    finally:
        await session.close()


async def _continue_spec_refinement(session, workspace_dir: Path, project_dir: Path = None) -> int:
    """Continue refining an existing spec session.
    
    Args:
        session: The SpecSession instance
        workspace_dir: Ralph workspace directory
        project_dir: Target project directory (needed if user wants to start loop)
    """
    # Track last output type for formatting
    last_was_tool = False
    
    def print_text(text: str):
        nonlocal last_was_tool
        if last_was_tool:
            print()
        print(text, end="", flush=True)
        last_was_tool = False
    
    def print_tool(name: str, input_str: str):
        nonlocal last_was_tool
        if not last_was_tool:
            print()
        print(f"{Colors.DIM}[{name}] {input_str}{Colors.NC}", flush=True)
        last_was_tool = True
    
    try:
        while not session.is_complete():
            print()
            print(f"{Colors.DIM}─" * 60 + f"{Colors.NC}")
            print(f"{Colors.DIM}Type 'done' to finish spec discovery.{Colors.NC}")
            print()
            
            try:
                user_input = await prompt_input_async("Your response")
            except (KeyboardInterrupt, EOFError):
                print("\n\nSpec refinement interrupted.")
                break
            
            last_was_tool = False
            
            if user_input.lower() in ("quit", "exit", "done", "q", ""):
                print()
                print(f"{Colors.CYAN}Finalizing spec...{Colors.NC}")
                async for chunk in session.send_message("I'm done. Please summarize the final spec."):
                    if chunk["type"] == "text":
                        print_text(chunk["content"])
                    elif chunk["type"] == "tool":
                        print_tool(chunk.get("name", "Tool"), chunk.get("input", ""))
                break
            
            print()
            print(f"{Colors.DIM}─" * 60 + f"{Colors.NC}")
            print()
            
            async for chunk in session.send_message(user_input):
                if chunk["type"] == "error":
                    print_error(chunk["content"])
                    return 1
                elif chunk["type"] == "text":
                    print_text(chunk["content"])
                elif chunk["type"] == "tool":
                    print_tool(chunk.get("name", "Tool"), chunk.get("input", ""))
        
        # Ask what to do next (recursive choice)
        print()
        print(f"{Colors.DIM}─" * 60 + f"{Colors.NC}")
        print()
        
        # Use async prompt since we're in async context
        next_choice = await prompt_choice_async(
            "What would you like to do next?",
            [
                "Continue refining",
                "Start the coding loop",
                "Exit (save for later)"
            ]
        )
        
        if next_choice == 0:
            return await _continue_spec_refinement(session, workspace_dir, project_dir)
        elif next_choice == 1:
            iterations = await prompt_input_async("How many iterations?", "10")
            if project_dir:
                os.chdir(project_dir)
                # Use async version since we're already in an event loop
                return await _run_loop_agent_async(project_dir, int(iterations), loop_type="default", start_iteration=1)
            else:
                print_info("To start loop: ralph run <project> -n " + iterations)
                return 0
        else:
            spec_file = workspace_dir / "spec-session.md"
            print_info(f"Spec saved to: {spec_file}")
            return 0
            
    except Exception as e:
        print_error(f"Error during refinement: {e}")
        traceback.print_exc()
        return 1


def cmd_init(args):
    """Initialize a new Ralph project (non-interactive)."""
    project_dir = resolve_project_path(args.name)
    project_name = project_dir.name

    if project_dir.exists():
        print_error(f"Directory already exists: {project_dir}")
        return 1

    print_header(f"Creating Project: {project_name}")
    print()

    _create_project_structure(project_dir, project_name)

    print_success("Project created successfully!")
    print()
    print("Next steps:")
    print(f"  1. {Colors.CYAN}cd {project_dir}{Colors.NC}")
    print(f"  2. Edit {Colors.CYAN}PRD.json{Colors.NC} with your requirements")
    print(f"     Or run: {Colors.CYAN}ralph spec . \"your topic\"{Colors.NC}")
    print(f"  3. Run {Colors.CYAN}ralph run . --once{Colors.NC} to start iterating")
    print()

    return 0


def cmd_list(args):
    """List all registered Ralph projects."""
    projects = get_all_projects()

    if not projects:
        print_info("No Ralph projects registered.")
        print_info("Create one with: ralph init <path>")
        print_info("Or register an existing project: ralph start (in project dir)")
        return 0

    print_header("Ralph Projects")
    print()

    for proj in projects:
        project_path = Path(proj["path"])
        project_name = proj["name"]
        
        # Check if project still exists
        if not project_path.exists():
            print(f"  {Colors.DIM}{project_name} (missing){Colors.NC}")
            print(f"    {Colors.DIM}Path: {project_path}{Colors.NC}")
            print()
            continue
        
        config_path = project_path / ".ralph-config"
        progress_path = project_path / "progress.txt"

        created = proj.get("registered", "Unknown")[:10]  # Just date part
        last_run = proj.get("last_run")
        if last_run:
            last_run = last_run[:10]  # Just date part

        progress_count = 0
        if progress_path.exists():
            progress_count = len(
                [l for l in progress_path.read_text().splitlines() if l.strip() and not l.startswith("#")]
            )

        print(f"  {Colors.BOLD}{project_name}{Colors.NC}")
        print(f"    Path: {Colors.CYAN}{project_path}{Colors.NC}")
        print(f"    Created: {created}")
        if last_run:
            print(f"    Last run: {last_run}")
        print(f"    Progress entries: {progress_count}")
        print()

    return 0


def cmd_projects(args):
    """List all projects for a target workspace."""
    target_dir = resolve_project_path(args.target)
    
    if not target_dir.exists():
        print_error(f"Directory not found: {target_dir}")
        return 1
    
    projects = list_workspace_projects(target_dir)
    active = get_active_project(target_dir)
    
    print_header(f"Projects for: {target_dir.name}")
    
    if not projects:
        print_info("No projects yet.")
        print_info(f"Create one with: ralph spec {args.target} \"topic\" -p project-name")
        return 0
    
    print()
    for proj in projects:
        marker = "* " if proj["is_active"] else "  "
        status_color = Colors.GREEN if proj["is_active"] else Colors.NC
        
        print(f"{marker}{status_color}{Colors.BOLD}{proj['name']}{Colors.NC}")
        
        if proj["has_prd"]:
            done = proj["done_tasks"]
            total = proj["total_tasks"]
            pct = int((done / total * 100)) if total > 0 else 0
            print(f"    Tasks: {done}/{total} ({pct}%)")
        else:
            print(f"    {Colors.DIM}(no PRD){Colors.NC}")
        
        if proj["is_active"]:
            print(f"    {Colors.GREEN}(active){Colors.NC}")
        print()
    
    print(f"{Colors.DIM}Switch project: ralph run {args.target} -p <project-name>{Colors.NC}")
    print()
    
    return 0


def cmd_run(args):
    """Run a Ralph loop on a project."""
    target_dir = resolve_project_path(args.project)
    project_name = getattr(args, 'project_name', None)

    if not target_dir.exists():
        print_error(f"Directory not found: {target_dir}")
        return 1

    # If project_name specified, set it as active
    if project_name:
        set_active_project(target_dir, project_name)
    
    # Check for PRD in workspace (correct location)
    workspace_dir = get_workspace_dir(target_dir, project_name)
    if not (workspace_dir / "PRD.json").exists():
        # Also check target for backwards compatibility
        if not (target_dir / "PRD.json").exists() and not (target_dir / "PRD.md").exists():
            print_error(f"No PRD.json found. Run 'ralph spec' or 'ralph start' to create one.")
            print_info(f"Expected location: {workspace_dir / 'PRD.json'}")
            if project_name:
                print_info(f"Project: {project_name}")
            return 1
        else:
            # Migrate old PRD from target to workspace
            print_info("Migrating PRD.json to Ralph workspace...")
            workspace_dir.mkdir(parents=True, exist_ok=True)
            if (target_dir / "PRD.json").exists():
                shutil.copy(target_dir / "PRD.json", workspace_dir / "PRD.json")
            if (target_dir / "progress.txt").exists():
                shutil.copy(target_dir / "progress.txt", workspace_dir / "progress.txt")

    # Docker sandbox mode
    if getattr(args, 'docker', False):
        return _run_in_docker(target_dir, args)

    os.chdir(target_dir)
    loop_type = getattr(args, 'type', 'default')
    
    # Show which project we're running
    active_project = get_active_project(target_dir) or "default"
    print_info(f"Project: {active_project}")
    
    # Check for --resume flag
    resume = getattr(args, 'resume', False)

    if args.once:
        print_header("Single Iteration")
        return _run_once_agent(target_dir, project_name)
    
    # Check for saved state
    saved_state = get_loop_state(target_dir)
    start_iteration = 1
    
    if resume and saved_state and saved_state.get("status") == "paused":
        # Resume from saved state
        start_iteration = saved_state.get("iteration", 1)
        iterations = saved_state.get("total_iterations", args.iterations or 10)
        loop_type = saved_state.get("loop_type", loop_type)
        
        print_header(f"Resuming AFK Loop")
        print_info(f"Resuming from iteration {start_iteration}/{iterations}")
        if saved_state.get("current_task"):
            task_id = saved_state.get("current_task_id", "")
            task_desc = saved_state.get("current_task", "")
            if task_id:
                print_info(f"Last task: [{task_id}] {task_desc}")
            else:
                print_info(f"Last task: {task_desc}")
        print()
        
    elif saved_state and saved_state.get("status") == "paused" and not resume:
        # Has saved state but --resume not specified
        print_info(f"Found paused loop at iteration {saved_state.get('iteration')}/{saved_state.get('total_iterations')}")
        if prompt_confirm("Resume from where you left off?"):
            start_iteration = saved_state.get("iteration", 1)
            iterations = saved_state.get("total_iterations", args.iterations or 10)
            loop_type = saved_state.get("loop_type", loop_type)
            print_header(f"Resuming AFK Loop")
        else:
            # Clear saved state and start fresh
            clear_loop_state(target_dir)
            iterations = args.iterations or 10
            type_label = f" [{loop_type}]" if loop_type != "default" else ""
            print_header(f"AFK Loop ({iterations} iterations){type_label}")
    else:
        iterations = args.iterations or 10
        type_label = f" [{loop_type}]" if loop_type != "default" else ""
        print_header(f"AFK Loop ({iterations} iterations){type_label}")
    
    return _run_loop_agent(
        target_dir,
        iterations,
        loop_type=loop_type,
        start_iteration=start_iteration,
        project_name=project_name,
    )


def _run_in_docker(project_dir: Path, args) -> int:
    """Run Ralph inside a Docker sandbox."""
    iterations = args.iterations or 10
    loop_type = getattr(args, 'type', 'default')
    
    # Build the ralph command to run inside docker
    ralph_cmd = f"ralph run . -n {iterations}"
    if args.once:
        ralph_cmd = "ralph run . --once"
    if loop_type != "default":
        ralph_cmd += f" --type {loop_type}"
    
    print_header("Docker Sandbox Mode")
    print_info(f"Project: {project_dir}")
    print_info(f"Command: {ralph_cmd}")
    print()
    
    # Run in docker sandbox
    docker_cmd = ["docker", "sandbox", "run", "claude", ralph_cmd]
    
    try:
        result = subprocess.run(docker_cmd, cwd=project_dir)
        return result.returncode
    except FileNotFoundError:
        print_error("Docker not found. Install Docker Desktop 4.50+")
        print_info("https://docs.docker.com/desktop/")
        return 1
    except Exception as e:
        print_error(f"Docker error: {e}")
        return 1


def cmd_spec(args):
    """Run spec discovery for a project."""
    target_dir = resolve_project_path(args.project)
    project_name = getattr(args, 'project_name', None)

    if not target_dir.exists():
        print_error(f"Directory not found: {target_dir}")
        return 1

    os.chdir(target_dir)

    # If project_name specified, set it as active
    if project_name:
        set_active_project(target_dir, project_name)
        print_info(f"Project: {project_name}")

    if not args.topic and not args.file:
        print_error("Provide either a topic or --file <requirements.md>")
        return 1

    topic = args.topic or f"Requirements from {args.file}"
    requirements_file = args.file or ""
    existing = args.existing
    max_iterations = getattr(args, 'max_iterations', None) or 20

    print_header(f"Spec Discovery: {topic}")
    return _run_spec_agent(
        target_dir,
        topic=topic,
        existing=existing,
        requirements_file=requirements_file,
        max_iterations=max_iterations,
        project_name=project_name,
    )


def cmd_status(args):
    """Show status of a project from its workspace."""
    import json
    
    target_dir = resolve_project_path(args.project)
    project_name = getattr(args, 'project_name', None)
    target_name = target_dir.name

    if not target_dir.exists():
        print_error(f"Directory not found: {target_dir}")
        return 1

    # Get workspace directory
    workspace_dir = get_workspace_dir(target_dir, project_name)
    active_project = get_active_project(target_dir) or "default"
    
    print_header(f"Status: {target_name}")
    print(f"{Colors.BOLD}Target:{Colors.NC} {target_dir}")
    print(f"{Colors.BOLD}Project:{Colors.NC} {project_name or active_project}")
    print(f"{Colors.BOLD}Workspace:{Colors.NC} {workspace_dir}")
    print()

    # PRD status from workspace
    prd_path = workspace_dir / "PRD.json"
    if prd_path.exists():
        try:
            prd = json.loads(prd_path.read_text())
            tasks = prd.get("tasks", [])
            total_tasks = len(tasks)
            done_tasks = sum(1 for t in tasks if t.get("status") == "done")
            
            print(f"{Colors.BOLD}PRD Tasks:{Colors.NC}")
            print(f"  {done_tasks}/{total_tasks} complete")
            
            # Show next incomplete task
            for task in sorted(tasks, key=lambda t: t.get("priority", 999)):
                if task.get("status") != "done":
                    print(f"  Next: [{task.get('id', '?')}] {task.get('name', 'Unknown')}")
                    break
            print()
        except Exception:
            pass
    else:
        print(f"{Colors.DIM}No PRD.json found in workspace{Colors.NC}")
        print()

    # Global config info
    config_path = get_global_config_path()
    if config_path.exists():
        print(f"{Colors.BOLD}Global Config (settings.json):{Colors.NC}")
        try:
            config_data = json.loads(config_path.read_text())
            # Just show some key settings
            for key in ["spec_model", "loop_model", "context_limit"]:
                if key in config_data:
                    print(f"  {key}: {config_data[key]}")
        except Exception:
            print(f"  {Colors.RED}(invalid JSON){Colors.NC}")
        print()

    progress_path = workspace_dir / "progress.txt"
    if progress_path.exists():
        entries = [l for l in progress_path.read_text().splitlines() if l.strip() and not l.startswith("#")]
        print(f"{Colors.BOLD}Progress ({len(entries)} entries):{Colors.NC}")
        for entry in entries[-5:]:
            print(f"  {entry}")
        if len(entries) > 5:
            print(f"  ... and {len(entries) - 5} more")
        print()

    spec_path = workspace_dir / "spec-session.md"
    if spec_path.exists():
        print(f"{Colors.BOLD}Spec Session:{Colors.NC}")
        print(f"  File: {spec_path}")
        print(f"  Size: {spec_path.stat().st_size} bytes")
        print()

    result = subprocess.run(
        ["git", "log", "--oneline", "-5"], cwd=target_dir, capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"{Colors.BOLD}Recent Commits:{Colors.NC}")
        for line in result.stdout.strip().splitlines():
            print(f"  {line}")
        print()

    return 0


def cmd_delete(args):
    """Remove project from registry and clean up Ralph workspace data."""
    # Handle --all flag
    if getattr(args, 'all', False):
        if not args.force:
            confirm = input("Clear ALL projects from registry and workspace data? [y/N] ")
            if confirm.lower() != "y":
                print("Cancelled.")
                return 0
        
        # Get all projects before clearing to clean up workspaces
        projects = get_all_projects()
        cleaned_roots = set()
        for proj in projects:
            # Clean up entire workspace root (includes .active and all projects)
            workspace_root = get_workspaces_root(Path(proj["path"]))
            if workspace_root.exists() and str(workspace_root) not in cleaned_roots:
                shutil.rmtree(workspace_root)
                cleaned_roots.add(str(workspace_root))
        
        count = clear_registry()
        print_success(f"Cleared {count} project(s) from registry and workspace data.")
        return 0
    
    # Require project path if not --all
    if not args.project:
        print_error("Provide a project path or use --all")
        return 1
    
    target_dir = resolve_project_path(args.project)
    target_name = target_dir.name
    ralph_project_name = getattr(args, 'project_name', None)  # Named project within workspace
    delete_files = getattr(args, 'files', False)
    
    # Check if registered
    if not is_registered(target_dir):
        print_error(f"Project not in registry: {target_dir}")
        return 1
    
    # Confirmation
    if not args.force:
        if ralph_project_name:
            confirm = input(f"Remove Ralph project '{ralph_project_name}' from '{target_name}'? [y/N] ")
        elif delete_files:
            confirm = input(f"Delete '{target_dir}' and all Ralph data? This cannot be undone. [y/N] ")
        else:
            confirm = input(f"Remove '{target_name}' from registry and clean up Ralph data? [y/N] ")
        if confirm.lower() != "y":
            print("Cancelled.")
            return 0
    
    # Clean up Ralph workspace (spec sessions, drafts, loop state)
    workspace_root = get_workspaces_root(target_dir)
    
    if ralph_project_name:
        # Delete specific named project
        workspace = get_workspace_dir(target_dir, ralph_project_name)
        if workspace.exists():
            shutil.rmtree(workspace)
            print_info(f"Cleaned up Ralph project: {ralph_project_name}")
        
        # If workspace root is now empty (except .active), clean it up too
        if workspace_root.exists():
            remaining = [f for f in workspace_root.iterdir() if f.name != ".active"]
            if not remaining:
                shutil.rmtree(workspace_root)
                print_info(f"Cleaned up workspace root (no projects left)")
        
        print_success(f"Removed project '{ralph_project_name}' from '{target_name}'.")
        return 0
    else:
        # Delete entire workspace root for this target
        if workspace_root.exists():
            shutil.rmtree(workspace_root)
            print_info(f"Cleaned up all Ralph workspace data for {target_name}")
    
    # Unregister from registry
    unregister_project(target_dir)
    
    # Optionally delete project files
    if delete_files:
        if target_dir.exists():
            shutil.rmtree(target_dir)
            print_success(f"Deleted '{target_name}' (registry + workspace + project files).")
        else:
            print_success(f"Removed '{target_name}' from registry (files already gone).")
    else:
        print_success(f"Removed '{target_name}' from registry and workspace.")
    
    return 0
