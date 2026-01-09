"""Monitoring hooks for Ralph agent."""

from typing import Any, Callable, Optional

from claude_agent_sdk import HookMatcher, HookContext


def create_monitoring_hooks(
    on_tool_start: Optional[Callable[[str, dict], None]] = None,
    on_tool_end: Optional[Callable[[str, dict, Any], None]] = None,
) -> dict[str, list[HookMatcher]]:
    """Create monitoring hooks for tracking agent activity.
    
    Args:
        on_tool_start: Callback when a tool starts (tool_name, tool_input)
        on_tool_end: Callback when a tool completes (tool_name, tool_input, result)
    
    Returns:
        Dictionary of hooks to pass to ClaudeAgentOptions
    """
    
    async def pre_tool_hook(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: HookContext,
    ) -> dict[str, Any]:
        """Hook called before tool execution."""
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        
        if on_tool_start:
            on_tool_start(tool_name, tool_input)
        
        return {}
    
    async def post_tool_hook(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: HookContext,
    ) -> dict[str, Any]:
        """Hook called after tool execution."""
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        tool_result = input_data.get("tool_result", {})
        
        if on_tool_end:
            on_tool_end(tool_name, tool_input, tool_result)
        
        return {}
    
    return {
        "PreToolUse": [HookMatcher(hooks=[pre_tool_hook])],
        "PostToolUse": [HookMatcher(hooks=[post_tool_hook])],
    }


def create_logging_hooks(log_func: Callable[[str], None]) -> dict[str, list[HookMatcher]]:
    """Create simple logging hooks.
    
    Args:
        log_func: Function to call with log messages
    
    Returns:
        Dictionary of hooks to pass to ClaudeAgentOptions
    """
    
    async def log_pre_tool(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: HookContext,
    ) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        
        # Format log message based on tool
        if tool_name == "Read":
            log_func(f"r Reading: {tool_input.get('file_path', '?')}")
        elif tool_name in ("Write", "Edit"):
            log_func(f"w Writing: {tool_input.get('file_path', '?')}")
        elif tool_name == "Bash":
            cmd = tool_input.get("command", "")
            cmd_short = cmd[:50] + "..." if len(cmd) > 50 else cmd
            log_func(f"$ Running: {cmd_short}")
        elif tool_name == "Glob":
            log_func(f"? Searching: {tool_input.get('pattern', '?')}")
        elif tool_name == "Grep":
            log_func(f"? Grep: {tool_input.get('pattern', '?')}")
        else:
            log_func(f"› Tool: {tool_name}")
        
        return {}
    
    async def log_post_tool(
        input_data: dict[str, Any],
        tool_use_id: str | None,
        context: HookContext,
    ) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "")
        tool_result = input_data.get("tool_result", {})
        
        # Check for errors
        if tool_result.get("is_error"):
            log_func(f"x {tool_name} failed")
        
        return {}
    
    return {
        "PreToolUse": [HookMatcher(hooks=[log_pre_tool])],
        "PostToolUse": [HookMatcher(hooks=[log_post_tool])],
    }
