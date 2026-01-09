"""Permission handlers for restricting agent file access."""

import logging
from pathlib import Path
from typing import Callable, Union

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny

logger = logging.getLogger(__name__)


def create_project_permission_handler(project_path: Path):
    """Create a permission handler that restricts file access to project directory.
    
    Args:
        project_path: The project directory to allow access to
    
    Returns:
        Async permission handler function for can_use_tool
    """
    project_path = project_path.resolve()
    
    async def permission_handler(
        tool_name: str,
        input_data: dict,
        context: dict,
    ) -> Union[PermissionResultAllow, PermissionResultDeny]:
        """Check if tool access is within project bounds."""
        
        # Tools that access files
        file_tools = {"Read", "Write", "Edit", "Glob", "Grep"}
        
        if tool_name not in file_tools:
            # Allow non-file tools
            return PermissionResultAllow(updated_input=input_data)
        
        # Get the file path from input
        file_path = None
        if tool_name == "Read":
            file_path = input_data.get("file_path")
        elif tool_name in ("Write", "Edit"):
            file_path = input_data.get("file_path")
        elif tool_name == "Glob":
            file_path = input_data.get("path") or str(project_path)
        elif tool_name == "Grep":
            file_path = input_data.get("path") or str(project_path)
        
        if file_path:
            # Resolve the path
            target_path = Path(file_path)
            if not target_path.is_absolute():
                target_path = project_path / target_path
            target_path = target_path.resolve()
            
            # Check if path is within project
            try:
                target_path.relative_to(project_path)
            except ValueError:
                # Path is outside project directory
                return PermissionResultDeny(
                    message=f"Access denied: {file_path} is outside project directory ({project_path})",
                    interrupt=False,  # Don't stop the agent, just deny this action
                )
        
        return PermissionResultAllow(updated_input=input_data)
    
    return permission_handler


def create_readonly_permission_handler(project_path: Path):
    """Create a permission handler for read-only (plan) mode.
    
    Only allows Read, Glob, Grep within project directory.
    
    Args:
        project_path: The project directory to allow access to
    
    Returns:
        Async permission handler function for can_use_tool
    """
    project_path = project_path.resolve()
    
    async def permission_handler(
        tool_name: str,
        input_data: dict,
        context: dict,
    ) -> Union[PermissionResultAllow, PermissionResultDeny]:
        """Check if tool is read-only and within project bounds."""
        
        # Only allow read-only tools
        readonly_tools = {"Read", "Glob", "Grep"}
        
        if tool_name not in readonly_tools:
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' not allowed in read-only mode",
                interrupt=False,
            )
        
        # Get the file path from input
        file_path = None
        if tool_name == "Read":
            file_path = input_data.get("file_path")
        elif tool_name == "Glob":
            file_path = input_data.get("path") or str(project_path)
        elif tool_name == "Grep":
            file_path = input_data.get("path") or str(project_path)
        
        if file_path:
            target_path = Path(file_path)
            if not target_path.is_absolute():
                target_path = project_path / target_path
            target_path = target_path.resolve()
            
            try:
                target_path.relative_to(project_path)
            except ValueError:
                return PermissionResultDeny(
                    message=f"Access denied: {file_path} is outside project directory",
                    interrupt=False,
                )
        
        return PermissionResultAllow(updated_input=input_data)
    
    return permission_handler


def create_interactive_permission_handler(
    project_path: Path,
    question_handler: Callable[[list[dict]], dict[str, str]],
):
    """Create a permission handler for interactive spec mode with HITL support.
    
    Allows read-only tools plus AskUserQuestion for human-in-the-loop interaction.
    
    Args:
        project_path: The project directory to allow access to
        question_handler: Callback that receives questions and returns answers
            - Input: list of question dicts with 'question', 'header', 'options', 'multiSelect'
            - Output: dict mapping question text to answer string
    
    Returns:
        Async permission handler function for can_use_tool
    """
    project_path = project_path.resolve()
    
    async def permission_handler(
        tool_name: str,
        input_data: dict,
        context: dict,
    ) -> Union[PermissionResultAllow, PermissionResultDeny]:
        """Handle permissions for interactive spec mode."""
        
        # Handle AskUserQuestion - this is the HITL mechanism
        if tool_name == "AskUserQuestion":
            questions = input_data.get("questions", [])
            if questions:
                # Call the question handler to get user answers
                answers = question_handler(questions)
                # Return updated input with answers populated
                updated_input = {**input_data, "answers": answers}
                return PermissionResultAllow(updated_input=updated_input)
            return PermissionResultAllow(updated_input=input_data)
        
        # Only allow read-only tools (plus AskUserQuestion handled above)
        readonly_tools = {"Read", "Glob", "Grep"}
        
        if tool_name not in readonly_tools:
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' not allowed in spec mode",
                interrupt=False,
            )
        
        # Check file paths are within project
        file_path = None
        if tool_name == "Read":
            file_path = input_data.get("file_path")
        elif tool_name == "Glob":
            file_path = input_data.get("path") or str(project_path)
        elif tool_name == "Grep":
            file_path = input_data.get("path") or str(project_path)
        
        if file_path:
            target_path = Path(file_path)
            if not target_path.is_absolute():
                target_path = project_path / target_path
            target_path = target_path.resolve()
            
            try:
                target_path.relative_to(project_path)
            except ValueError:
                return PermissionResultDeny(
                    message=f"Access denied: {file_path} is outside project directory",
                    interrupt=False,
                )
        
        return PermissionResultAllow(updated_input=input_data)
    
    return permission_handler


def create_spec_permission_handler(target_dir: Path, workspace_dir: Path):
    """Create a permission handler for spec discovery mode.
    
    During spec discovery:
    - READ operations allowed from target_dir (to understand the project)
    - WRITE/EDIT operations ONLY allowed to workspace_dir (spec files)
    - NO files should be created in the target project
    - Bash, TodoWrite, and other tools are NOT allowed
    
    Args:
        target_dir: The target project directory (read-only)
        workspace_dir: Ralph's workspace directory (write allowed)
    
    Returns:
        Async permission handler function for can_use_tool
    """
    target_dir = target_dir.resolve()
    workspace_dir = workspace_dir.resolve()
    
    async def permission_handler(
        tool_name: str,
        input_data: dict,
        context: dict,
    ) -> Union[PermissionResultAllow, PermissionResultDeny]:
        """Handle permissions for spec discovery mode."""
        
        # Read-only tools - allow from target directory
        read_tools = {"Read", "Glob", "Grep"}
        
        # Write tools - only allow to workspace
        write_tools = {"Write", "Edit"}
        
        # Handle read tools
        if tool_name in read_tools:
            file_path = None
            if tool_name == "Read":
                file_path = input_data.get("file_path")
            elif tool_name == "Glob":
                file_path = input_data.get("path") or str(target_dir)
            elif tool_name == "Grep":
                file_path = input_data.get("path") or str(target_dir)
            
            if file_path:
                path = Path(file_path)
                if not path.is_absolute():
                    path = target_dir / path
                path = path.resolve()
                
                # Allow reading from target_dir OR workspace_dir
                try:
                    path.relative_to(target_dir)
                    return PermissionResultAllow(updated_input=input_data)
                except ValueError:
                    pass
                
                try:
                    path.relative_to(workspace_dir)
                    return PermissionResultAllow(updated_input=input_data)
                except ValueError:
                    pass
                
                return PermissionResultDeny(
                    message=f"Read access denied: {file_path} is outside allowed directories",
                    interrupt=False,
                )
            
            return PermissionResultAllow(updated_input=input_data)
        
        # Handle write tools - ONLY allow to workspace
        if tool_name in write_tools:
            file_path = input_data.get("file_path")
            
            if file_path:
                path = Path(file_path)
                if not path.is_absolute():
                    # Default writes should go to workspace
                    path = workspace_dir / path
                path = path.resolve()
                
                # Only allow writes to workspace directory
                try:
                    path.relative_to(workspace_dir)
                    # Update input to use absolute workspace path
                    updated_input = {**input_data, "file_path": str(path)}
                    return PermissionResultAllow(updated_input=updated_input)
                except ValueError:
                    logger.warning(f"Blocked write to {file_path} - not in workspace")
                    return PermissionResultDeny(
                        message=f"Write denied: During spec discovery, files can only be written to the Ralph workspace. "
                               f"Target: {file_path}. Allowed: {workspace_dir}",
                        interrupt=False,
                    )
            
            return PermissionResultDeny(
                message="Write denied: No file path specified",
                interrupt=False,
            )
        
        # Deny other tools during spec discovery
        # (Bash, TodoWrite, etc. should not be used)
        return PermissionResultDeny(
            message=f"Tool '{tool_name}' is not allowed during spec discovery. "
                   f"Only Read, Glob, Grep, Write (to workspace), and Edit (workspace) are allowed.",
            interrupt=False,
        )
