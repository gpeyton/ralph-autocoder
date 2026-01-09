"""Prompt templates for Ralph agent.

Prompts are stored as .md files for easy editing.

IMPORTANT: All Ralph metadata files (PRD.json, progress.txt, etc.) are stored
in the Ralph workspace (~/.ralph/workspaces/<project>/), NOT in the target project.
The target project directory should ONLY contain actual code changes.
"""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent

# Available loop types
LOOP_TYPES = {
    "default": "loop",
    "test-coverage": "loop_test_coverage",
    "linting": "loop_linting",
    "duplication": "loop_duplication",
    "entropy": "loop_entropy",
}


def _load_prompt(name: str) -> str:
    """Load a prompt from a markdown file."""
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text().strip()


def get_once_prompt(workspace_dir: str, target_dir: str) -> str:
    """Get the single iteration prompt with file references.
    
    Args:
        workspace_dir: Path to Ralph workspace (contains PRD.json, progress.txt)
        target_dir: Path to target project (where code changes are made)
    """
    prompt = _load_prompt("once")
    
    prd_path = f"{workspace_dir}/PRD.json"
    progress_path = f"{workspace_dir}/progress.txt"
    failures_path = f"{workspace_dir}/failures.md"
    
    # Replace placeholders with full workspace paths
    prompt = prompt.replace("{prd_path}", prd_path)
    prompt = prompt.replace("{progress_path}", progress_path)
    prompt = prompt.replace("{failures_path}", failures_path)
    
    # Add workspace context to prompt
    workspace_context = f"""
## File Locations (CRITICAL - USE THESE EXACT PATHS)

- **Ralph Workspace**: {workspace_dir}
  - PRD: {prd_path}
  - Progress: {progress_path}
  - Failures: {failures_path}
  
- **Target Project**: {target_dir}
  - This is where you make CODE CHANGES ONLY
  - NEVER create PRD.json, progress.txt, or any Ralph files here
  - NEVER read PRD.json from this directory

**NEVER use relative paths like "PRD.json" - always use the full paths above.**
"""
    
    return f"@{prd_path} @{progress_path}\n\n{workspace_context}\n\n{prompt}"


def get_loop_prompt(
    loop_type: str = "default",
    workspace_dir: str = "",
    target_dir: str = "",
) -> str:
    """Get the loop prompt for a specific loop type.
    
    Args:
        loop_type: One of: default, test-coverage, linting, duplication, entropy
        workspace_dir: Path to Ralph workspace (contains PRD.json, progress.txt)
        target_dir: Path to target project (where code changes are made)
    """
    prompt_name = LOOP_TYPES.get(loop_type, "loop")
    prompt = _load_prompt(prompt_name)
    
    prd_path = f"{workspace_dir}/PRD.json"
    progress_path = f"{workspace_dir}/progress.txt"
    failures_path = f"{workspace_dir}/failures.md"
    
    # Replace placeholders with full workspace paths
    prompt = prompt.replace("{prd_path}", prd_path)
    prompt = prompt.replace("{progress_path}", progress_path)
    prompt = prompt.replace("{failures_path}", failures_path)
    
    # Add workspace context to prompt
    workspace_context = f"""
## File Locations (CRITICAL - USE THESE EXACT PATHS)

- **Ralph Workspace**: {workspace_dir}
  - PRD: {prd_path}
  - Progress: {progress_path}
  - Failures: {failures_path}
  
- **Target Project**: {target_dir}
  - This is where you make CODE CHANGES ONLY
  - NEVER create PRD.json, progress.txt, or any Ralph files here
  - NEVER read PRD.json from this directory

**NEVER use relative paths like "PRD.json" - always use the full paths above.**
"""
    
    return f"@{prd_path} @{progress_path}\n\n{workspace_context}\n\n{prompt}"


def get_spec_prompt(
    topic: str,
    existing: bool = False,
    has_requirements_file: bool = False,
    workspace_dir: str = "",
) -> str:
    """Get the spec discovery prompt with appropriate context.
    
    Args:
        topic: The subject being specified
        existing: Whether this is an existing codebase
        has_requirements_file: Whether a requirements file was provided
        workspace_dir: Path to Ralph workspace (where spec files are written)
    """
    context_parts = [f"**Topic**: {topic}"]
    
    if existing:
        context_parts.append(_load_prompt("spec_context_existing"))
    elif has_requirements_file:
        context_parts.append(_load_prompt("spec_context_file"))
    else:
        context_parts.append(_load_prompt("spec_context_new"))
    
    # Add critical write restriction notice
    prd_path = f"{workspace_dir}/PRD.json"
    spec_session_path = f"{workspace_dir}/spec-session.md"
    
    write_restriction = f"""
**IMPORTANT - WRITE RESTRICTIONS**:
During spec discovery, you are in READ-ONLY mode for the target project.
- You CAN read files from the target project to understand context
- You can ONLY write to the Ralph workspace: {workspace_dir}
- DO NOT create any files or directories in the target project
- DO NOT use Bash to create files, mkdir, or modify the target project

**Files you can write to:**
- {spec_session_path} - Update as you learn requirements
- {prd_path} - Write the final PRD.json here when complete

Focus on having a conversation with the user to understand requirements.
Do not start implementing or creating files - that happens in the coding loop phase.
"""
    context_parts.append(write_restriction)
    
    context_section = "\n\n".join(context_parts)
    
    # Use string replacement instead of .format() to avoid issues with JSON {} in prompt
    prompt = _load_prompt("spec").replace("{context_section}", context_section)
    
    # Replace explicit action instructions to use full workspace paths
    # These are the key lines where Claude needs to know WHERE to write
    prompt = prompt.replace("generate PRD.json", f"generate {prd_path}")
    prompt = prompt.replace("Write PRD.json", f"Write {prd_path}")
    
    # Reference the workspace spec file, not target project
    spec_file = spec_session_path
    
    return f"@{spec_file}\n\n{prompt}"


__all__ = [
    "LOOP_TYPES",
    "get_once_prompt",
    "get_loop_prompt",
    "get_spec_prompt",
]
