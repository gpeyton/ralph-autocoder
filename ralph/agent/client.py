"""Ralph Agent - ClaudeSDKClient wrapper with monitoring."""

import asyncio
import os
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

# Unix-only imports for keyboard handling
_HAS_TERMIOS = False
try:
    import select
    import termios
    import tty
    _HAS_TERMIOS = True
except ImportError:
    pass  # Windows - keyboard handling won't work

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    ToolResultBlock,
)

from .output import AgentDisplay
from .hooks import create_monitoring_hooks
from .permissions import (
    create_project_permission_handler,
    create_readonly_permission_handler,
    create_interactive_permission_handler,
)


class KeyboardHandler:
    """Non-blocking keyboard input handler for pause/stop controls.
    
    Note: Only works on Unix-like systems (Linux, macOS).
    On Windows, pause/stop controls are not available.
    """
    
    def __init__(self, display: AgentDisplay):
        self.display = display
        self._running = False
        self._old_settings = None
        self._supported = _HAS_TERMIOS and platform.system() != "Windows"
    
    def start(self) -> None:
        """Start listening for keyboard input."""
        if not self._supported or not sys.stdin.isatty():
            return
        
        self._running = True
        # Save terminal settings
        try:
            self._old_settings = termios.tcgetattr(sys.stdin)
            # Set terminal to raw mode for character-by-character input
            tty.setcbreak(sys.stdin.fileno())
        except Exception:
            self._old_settings = None
            self._running = False
    
    def stop(self) -> None:
        """Stop listening and restore terminal settings."""
        self._running = False
        if self._old_settings and self._supported:
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
            except Exception:
                pass
    
    def check_input(self) -> None:
        """Check for keyboard input (non-blocking).
        
        Call this periodically during the loop.
        """
        if not self._running or not self._supported or not sys.stdin.isatty():
            return
        
        try:
            # Check if input is available
            if select.select([sys.stdin], [], [], 0)[0]:
                char = sys.stdin.read(1).lower()
                if char == 'p':
                    self.display.request_pause()
                elif char == 'g':
                    self.display.request_gutter()
                elif char == 's' or char == 'q':
                    self.display.request_stop()
                elif char == 'i':
                    self.display.request_intervene()
        except Exception:
            pass
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False


async def keyboard_listener(display: AgentDisplay) -> None:
    """Async task that periodically checks for keyboard input."""
    handler = KeyboardHandler(display)
    handler.start()
    
    try:
        while True:
            handler.check_input()
            await asyncio.sleep(0.1)  # Check every 100ms
    finally:
        handler.stop()


@dataclass
class RunResult:
    """Result from a single agent run."""
    
    success: bool
    is_complete: bool  # PRD marked as complete
    is_gutter: bool  # Agent is stuck or gutter requested
    is_auto_gutter: bool  # Context limit reached automatically
    is_user_gutter: bool  # User requested gutter
    result_text: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    num_turns: int


class RalphAgent:
    """Ralph Agent with real-time monitoring display.
    
    Wraps ClaudeSDKClient to provide:
    - Real-time activity display
    - Token and cost tracking
    - Iteration management for loops
    - Raw output logging to file
    """
    
    COMPLETION_SIGNAL = "<promise>COMPLETE</promise>"
    SPEC_COMPLETE_SIGNAL = "<promise>SPEC_COMPLETE</promise>"
    GUTTER_SIGNAL = "<promise>GUTTER</promise>"
    
    # Default tools for different modes
    TOOLS_FULL = [
        "Read", "Write", "Edit", "Bash", 
        "Glob", "Grep", "TodoWrite"
    ]
    TOOLS_READONLY = ["Read", "Glob", "Grep"]
    TOOLS_SPEC = ["Read", "Glob", "Grep", "AskUserQuestion"]
    
    def __init__(
        self,
        cwd: Optional[Path] = None,
        display: Optional[AgentDisplay] = None,
        question_handler: Optional[Callable[[list[dict]], dict[str, str]]] = None,
        log_file: Optional[Path] = None,
        mcp_servers: Optional[dict] = None,
        model: str = "claude-3-5-sonnet-20241022",
        context_limit: int = 200000,
        rotate_threshold: float = 0.8,
        auto_gutter: bool = True,
    ):
        """Initialize Ralph agent.
        
        Args:
            cwd: Working directory for the agent
            display: Optional display manager (created if not provided)
            question_handler: Optional callback for HITL questions (for spec mode)
                - Input: list of question dicts with 'question', 'header', 'options', 'multiSelect'
                - Output: dict mapping question text to answer string
            log_file: Optional path to raw log file for all agent output
            mcp_servers: Optional dict of MCP server configurations
            model: Claude model to use
            context_limit: Maximum context tokens for this model
            rotate_threshold: Percentage (0.0-1.0) at which to rotate context
            auto_gutter: Whether to automatically rotate context when threshold reached
        """
        self.cwd = cwd or Path.cwd()
        self.display = display
        self.question_handler = question_handler
        self.log_file = log_file
        self.mcp_servers = mcp_servers
        self.model = model
        self.context_limit = context_limit
        self.rotate_threshold = rotate_threshold
        self.auto_gutter = auto_gutter
        self._client: Optional[ClaudeSDKClient] = None
        self._log_handle = None
    
    def _log(self, message: str, prefix: str = "") -> None:
        """Write a message to the raw log file."""
        if not self.log_file:
            return
        
        try:
            # Open file in append mode if not already open
            if self._log_handle is None:
                self._log_handle = open(self.log_file, "a", encoding="utf-8")
            
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            if prefix:
                self._log_handle.write(f"[{timestamp}] [{prefix}] {message}\n")
            else:
                self._log_handle.write(f"[{timestamp}] {message}\n")
            self._log_handle.flush()
        except Exception:
            pass  # Don't let logging errors break the agent
    
    def _close_log(self) -> None:
        """Close the log file handle."""
        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
    
    async def run_once(
        self,
        prompt: str,
        permission_mode: str = "acceptEdits",
    ) -> RunResult:
        """Run a single iteration.
        
        Args:
            prompt: The prompt to send
            permission_mode: Permission mode (acceptEdits, plan, etc.)
        
        Returns:
            RunResult with success status and stats
        """
        if self.display:
            self.display.set_status("running")
            self.display.set_iteration(1)
        
        result = await self._execute(
            prompt=prompt,
            permission_mode=permission_mode,
            allowed_tools=self.TOOLS_FULL,
        )
        
        if self.display:
            self.display.set_status("complete" if result.success else "error")
        
        return result
    
    async def run_loop(
        self,
        prompt: str,
        max_iterations: int = 10,
        permission_mode: str = "acceptEdits",
        start_iteration: int = 1,
        loop_type: str = "default",
        on_iteration_complete: Optional[Callable[[int, 'RunResult'], None]] = None,
    ) -> tuple[list['RunResult'], str]:
        """Run multiple iterations until complete or max reached.
        
        Args:
            prompt: The prompt template to use each iteration
            max_iterations: Maximum iterations to run
            permission_mode: Permission mode
            start_iteration: Starting iteration number (for resume)
            loop_type: Type of loop for state saving
            on_iteration_complete: Optional callback after each iteration
        
        Returns:
            Tuple of (List of RunResults, exit_reason) where exit_reason is one of:
            - "complete": PRD is done
            - "gutter": Agent is stuck
            - "paused": User requested pause
            - "stopped": User requested stop
            - "error": Iteration failed
            - "max_iterations": Reached max iterations
        """
        results = []
        exit_reason = "max_iterations"
        
        for i in range(start_iteration, max_iterations + 1):
            if self.display:
                self.display.set_iteration(i)
                self.display.set_status("running")
                self.display.log_activity("info", f"Starting iteration {i}/{max_iterations}")
            
            result = await self._execute(
                prompt=prompt,
                permission_mode=permission_mode,
                allowed_tools=self.TOOLS_FULL,
            )
            results.append(result)
            
            # Call iteration complete callback if provided
            if on_iteration_complete:
                on_iteration_complete(i, result)
            
            if self.display:
                self.display.set_status("complete" if result.success else "error")
            
            # Check for completion signal
            if result.is_complete:
                if self.display:
                    self.display.log_activity("complete", "PRD complete!")
                exit_reason = "complete"
                break
            
            # Check for gutter signal (agent is stuck or rotation needed)
            if result.is_gutter:
                if result.is_auto_gutter or result.is_user_gutter:
                    if self.display:
                        reason = "Context limit" if result.is_auto_gutter else "User requested"
                        self.display.log_activity("info", f"Rotating context ({reason})...")
                    continue  # Start next iteration with fresh context
                
                if self.display:
                    self.display.log_activity("warning", "GUTTER: Agent is stuck, stopping")
                exit_reason = "gutter"
                break
            
            if not result.success:
                if self.display:
                    self.display.log_activity("error", "Iteration failed, stopping")
                exit_reason = "error"
                break
            
            # Check for pause/stop requests from display
            if self.display:
                if self.display.is_stop_requested():
                    self.display.log_activity("stop", f"Stopped at iteration {i}")
                    exit_reason = "stopped"
                    break
                
                if self.display.is_pause_requested():
                    self.display.set_status("paused")
                    self.display.log_activity("pause", f"Paused at iteration {i}")
                    exit_reason = "paused"
                    break
        
        return results, exit_reason
    
    async def run_spec(
        self,
        prompt: str,
        max_iterations: int = 20,
    ) -> list[RunResult]:
        """Run spec discovery in plan mode with HITL support.
        
        Uses plan mode for read-only exploration. If a question_handler was
        provided to the agent, enables AskUserQuestion for human-in-the-loop.
        
        Args:
            prompt: The spec discovery prompt
            max_iterations: Maximum Q&A iterations
        
        Returns:
            List of RunResults for each iteration
        """
        results = []
        
        # Use interactive tools if we have a question handler
        tools = self.TOOLS_SPEC if self.question_handler else self.TOOLS_READONLY
        
        for i in range(1, max_iterations + 1):
            if self.display:
                self.display.set_iteration(i)
                self.display.set_status("running")
                self.display.log_activity("info", f"Spec iteration {i}/{max_iterations}")
            
            result = await self._execute(
                prompt=prompt,
                permission_mode="plan",  # Read-only mode
                allowed_tools=tools,
                interactive=bool(self.question_handler),
            )
            results.append(result)
            
            if self.display:
                self.display.set_status("complete" if result.success else "error")
            
            # Check for spec completion signal
            if self.SPEC_COMPLETE_SIGNAL in result.result_text:
                if self.display:
                    self.display.log_activity("complete", "Spec complete!")
                break
        
        return results
    
    async def _execute(
        self,
        prompt: str,
        permission_mode: str,
        allowed_tools: list[str],
        interactive: bool = False,
    ) -> RunResult:
        """Execute a single prompt and collect results.
        
        Args:
            prompt: The prompt to send
            permission_mode: Permission mode
            allowed_tools: List of allowed tool names
            interactive: Whether to use interactive mode with HITL support
        
        Returns:
            RunResult with execution details
        """
        # Find system Claude CLI to ensure same environment as user
        # This fixes issues where the bundled CLI can't find Node/npm or browsers
        system_cli = shutil.which("claude")
        
        # Build hooks for monitoring
        hooks = None
        if self.display:
            hooks = create_monitoring_hooks(
                on_tool_start=lambda name, inp: self.display.log_tool_use(name, inp),
            )
        
        # Create permission handler to restrict file access to project directory
        if interactive and self.question_handler:
            can_use_tool = create_interactive_permission_handler(
                self.cwd,
                self.question_handler,
            )
        elif permission_mode == "plan":
            can_use_tool = create_readonly_permission_handler(self.cwd)
        else:
            can_use_tool = create_project_permission_handler(self.cwd)
        
        # Build MCP servers config with environment inheritance
        # This ensures Playwright and other MCP servers can find system tools/browsers
        mcp_servers = None
        if self.mcp_servers:
            mcp_servers = {}
            for name, config in self.mcp_servers.items():
                mcp_servers[name] = config.copy()
                # Ensure each MCP server inherits the system environment (PATH, HOME, etc.)
                if "env" not in mcp_servers[name]:
                    mcp_servers[name]["env"] = {}
                
                # Merge current environment
                mcp_servers[name]["env"].update(os.environ)
        
        # Build options
        options_kwargs = {
            "model": self.model,
            "cwd": str(self.cwd.resolve()),
            "permission_mode": permission_mode,
            "allowed_tools": allowed_tools,
            "hooks": hooks,
            "can_use_tool": can_use_tool,
            "cli_path": system_cli,
            "setting_sources": ["project"],
            "max_buffer_size": 10 * 1024 * 1024,  # 10MB for large Playwright screenshots
        }
        
        if mcp_servers:
            options_kwargs["mcp_servers"] = mcp_servers
        
        options = ClaudeAgentOptions(**options_kwargs)
        
        # Execute with client
        result_text = ""
        input_tokens = 0
        output_tokens = 0
        cost_usd = 0.0
        duration_ms = 0
        num_turns = 0
        success = True
        
        try:
            # Log iteration start
            self._log("=" * 80, "")
            self._log("NEW ITERATION", "START")
            self._log(f"Permission mode: {permission_mode}", "CONFIG")
            self._log(f"Allowed tools: {allowed_tools}", "CONFIG")
            if self.mcp_servers:
                self._log(f"MCP servers: {list(self.mcp_servers.keys())}", "CONFIG")
            self._log("-" * 80, "")
            
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)
                
                # Process messages in a loop that supports intervention
                while True:
                    got_result = False
                    
                    async for message in client.receive_response():
                        # Check for intervention request (between messages)
                        if self.display and self.display.is_intervene_requested():
                            self.display.clear_intervene()
                            self._log("INTERVENTION requested by user", "INTERVENE")
                            
                            # Interrupt current execution
                            await client.interrupt()
                            
                            # Prompt user for intervention text
                            intervention_text = self.display.prompt_intervene()
                            
                            if intervention_text:
                                self._log(f"Intervention: {intervention_text}", "INTERVENE")
                                # Send the intervention as a new query continuing the conversation
                                await client.query(f"[USER INTERVENTION] {intervention_text}")
                                # Break to re-enter message processing loop
                                break
                            else:
                                self._log("Intervention cancelled", "INTERVENE")
                                # Resume normal processing - the break will exit and we'll continue
                                await client.query("Continue with what you were doing.")
                                break
                        
                        # Process different message types
                        if isinstance(message, AssistantMessage):
                            # A turn finished (Assistant replied)
                            from ..cli.registry import track_usage
                            track_usage(1)
                            
                            if self.display:
                                self.display.stats.session_turns += 1
                                
                                # Check if current message has usage info (SDK dependent)
                                # NOTE: Most SDK AssistantMessage objects don't have usage yet
                                usage = getattr(message, "usage", None)
                                if usage:
                                    def get_val(obj, key, default=0):
                                        if hasattr(obj, "get"):
                                            return obj.get(key, default)
                                        return getattr(obj, key, default)

                                    current_in = get_val(usage, "input_tokens")
                                    current_in += get_val(usage, "cache_read_input_tokens")
                                    current_in += get_val(usage, "cache_creation_input_tokens")
                                    current_out = get_val(usage, "output_tokens")
                                    
                                    self.display.update_stats(
                                        input_tokens=current_in,
                                        output_tokens=current_out,
                                        context_used_tokens=current_in,
                                        context_limit=self.context_limit,
                                    )
                                else:
                                    # Just update plan usage if no token info yet
                                    self.display._update_plan_usage()
                                    self.display.refresh()
                                    
                            for block in message.content:
                                if isinstance(block, TextBlock):
                                    result_text += block.text
                                    self._log(block.text, "TEXT")
                                    if self.display:
                                        self.display.log_text(block.text)
                                elif isinstance(block, ThinkingBlock):
                                    self._log(block.thinking, "THINKING")
                                    if self.display:
                                        self.display.log_thinking(block.thinking)
                                elif isinstance(block, ToolUseBlock):
                                    # Log tool use
                                    import json
                                    tool_input_str = json.dumps(block.input, indent=2) if block.input else ""
                                    self._log(f"{block.name}: {tool_input_str}", "TOOL_USE")
                                elif isinstance(block, ToolResultBlock):
                                    # Log tool result (full, non-truncated)
                                    content_str = str(block.content) if block.content else ""
                                    self._log(f"[{block.tool_use_id}] {content_str}", "TOOL_RESULT")
                        
                        elif isinstance(message, ResultMessage):
                            # Extract stats from result
                            success = not message.is_error
                            duration_ms = message.duration_ms
                            num_turns = message.num_turns
                            got_result = True
                            
                            if message.usage:
                                def get_val(obj, key, default=0):
                                    if hasattr(obj, "get"):
                                        return obj.get(key, default)
                                    return getattr(obj, key, default)

                                # Sum ALL input tokens (including cache)
                                input_tokens = get_val(message.usage, "input_tokens")
                                input_tokens += get_val(message.usage, "cache_read_input_tokens")
                                input_tokens += get_val(message.usage, "cache_creation_input_tokens")
                                output_tokens = get_val(message.usage, "output_tokens")
                            
                            if message.total_cost_usd:
                                cost_usd = message.total_cost_usd
                            
                            if message.result:
                                result_text = message.result
                            
                            # Log result summary
                            self._log(f"Success: {success}, Tokens: {input_tokens}/{output_tokens}, Cost: ${cost_usd:.2f}", "RESULT")
                            
                            # Update display stats with final iteration numbers
                            if self.display:
                                self.display.update_stats(
                                    input_tokens=input_tokens,
                                    output_tokens=output_tokens,
                                    cost_usd=cost_usd,
                                    duration_ms=duration_ms,
                                    num_turns=num_turns,
                                    context_used_tokens=input_tokens,
                                    context_limit=self.context_limit,
                                )
                                self.display.finish_iteration()
                    
                    # Exit the outer while loop if we got a result (iteration complete)
                    if got_result:
                        break
        
        except Exception as e:
            success = False
            result_text = str(e)
            self._log(f"Error: {e}", "ERROR")
            if self.display:
                self.display.log_activity("error", f"Error: {e}")
        
        # Check for completion signals
        is_complete = (
            self.COMPLETION_SIGNAL in result_text or
            self.SPEC_COMPLETE_SIGNAL in result_text
        )
        # Gutter if signal in text OR user requested it via keyboard
        is_gutter = self.GUTTER_SIGNAL in result_text
        is_user_gutter = False
        if self.display and self.display.is_gutter_requested():
            is_user_gutter = True
            is_gutter = True
            self.display.clear_gutter()
            
        # Auto-gutter if context usage exceeds threshold and auto_gutter is enabled
        is_auto_gutter = False
        if self.auto_gutter and input_tokens > (self.context_limit * self.rotate_threshold):
            is_auto_gutter = True
            is_gutter = True
            if self.display:
                self.display.log_activity("warning", f"Context usage ({input_tokens:,}) exceeds {self.rotate_threshold*100:.0f}% threshold")
        
        return RunResult(
            success=success,
            is_complete=is_complete,
            is_gutter=is_gutter,
            is_auto_gutter=is_auto_gutter,
            is_user_gutter=is_user_gutter,
            result_text=result_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            num_turns=num_turns,
        )


async def run_ralph_once(
    cwd: Path,
    prompt: str,
    show_display: bool = True,
) -> RunResult:
    """Convenience function to run a single iteration.
    
    Args:
        cwd: Working directory
        prompt: The prompt to send
        show_display: Whether to show the live display
    
    Returns:
        RunResult
    """
    display = AgentDisplay(total_iterations=1, mode="once") if show_display else None
    agent = RalphAgent(cwd=cwd, display=display)
    
    if display:
        display.start()
    
    try:
        result = await agent.run_once(prompt)
    finally:
        if display:
            display.stop()
            display.print_summary()
    
    return result


async def run_ralph_loop(
    cwd: Path,
    prompt: str,
    max_iterations: int = 10,
    show_display: bool = True,
    start_iteration: int = 1,
    loop_type: str = "default",
    on_iteration_complete: Optional[Callable[[int, RunResult], None]] = None,
) -> tuple[list[RunResult], str]:
    """Convenience function to run the AFK loop.
    
    Args:
        cwd: Working directory
        prompt: The prompt template
        max_iterations: Maximum iterations
        show_display: Whether to show the live display
        start_iteration: Starting iteration (for resume)
        loop_type: Loop type for state tracking
        on_iteration_complete: Optional callback after each iteration
    
    Returns:
        Tuple of (List of RunResults, exit_reason)
    """
    display = AgentDisplay(total_iterations=max_iterations, mode="loop") if show_display else None
    agent = RalphAgent(cwd=cwd, display=display)
    
    if display:
        display.start()
    
    try:
        results, exit_reason = await agent.run_loop(
            prompt,
            max_iterations=max_iterations,
            start_iteration=start_iteration,
            loop_type=loop_type,
            on_iteration_complete=on_iteration_complete,
        )
    finally:
        if display:
            display.stop()
            display.print_summary()
    
    return results, exit_reason


async def run_ralph_spec(
    cwd: Path,
    prompt: str,
    max_iterations: int = 20,
    show_display: bool = True,
) -> list[RunResult]:
    """Convenience function to run spec discovery.
    
    Args:
        cwd: Working directory
        prompt: The spec prompt
        max_iterations: Maximum Q&A iterations
        show_display: Whether to show the live display
    
    Returns:
        List of RunResults
    """
    display = AgentDisplay(total_iterations=max_iterations, mode="spec") if show_display else None
    agent = RalphAgent(cwd=cwd, display=display)
    
    if display:
        display.start()
    
    try:
        results = await agent.run_spec(prompt, max_iterations=max_iterations)
    finally:
        if display:
            display.stop()
            display.print_summary()
    
    return results
