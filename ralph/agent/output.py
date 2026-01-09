"""Real-time display formatting for Ralph agent output."""

import os
import platform
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.box import ROUNDED

# Check if keyboard controls are supported (Unix only)
_KEYBOARD_SUPPORTED = platform.system() != "Windows"


def get_terminal_width() -> int:
    """Get terminal width with a sensible default."""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 120  # Default fallback


@dataclass
class AgentStats:
    """Statistics for current agent run."""
    
    iteration: int = 0
    total_iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    current_task: str = ""
    current_task_id: str = ""  # Task ID (e.g., "1.2")
    status: str = "idle"
    
    # Real-time elapsed time tracking
    iteration_start_time: datetime | None = None
    
    # Context usage tracking
    context_limit: int = 200000
    context_used_tokens: int = 0
    context_used_pct: float = 0.0
    
    # Cumulative stats across iterations
    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    cumulative_cost_usd: float = 0.0
    cumulative_duration_ms: int = 0
    
    # Plan usage tracking (rolling 5-hour window)
    plan_usage_pct: float = 0.0
    plan_messages_used: int = 0
    plan_messages_limit: int = 225  # MAX 5x default, 900 for MAX 20x
    plan_reset_time: datetime | None = None
    
    # Track turns in current session for plan usage
    session_turns: int = 0


@dataclass
class ActivityLog:
    """Single activity entry."""
    
    timestamp: datetime
    icon: str
    message: str
    detail: str = ""


class AgentDisplay:
    """Real-time display manager for agent activity."""
    
    ICONS = {
        "thinking": "·",
        "tool": "›",
        "tool_result": "«",
        "success": "v",
        "error": "x",
        "warning": "!",
        "info": "i",
        "task": "»",
        "file_read": "r",
        "file_write": "w",
        "bash": "$",
        "search": "?",
        "commit": "c",
        "complete": "★",
        "pause": "||",
        "stop": "x",
    }
    
    # Fixed dimensions for activity panel
    ACTIVITY_PANEL_HEIGHT = 14
    MIN_PANEL_WIDTH = 100
    MAX_PANEL_WIDTH = 140
    
    def __init__(self, total_iterations: int = 1, mode: str = "loop", plan_limit: int = 225):
        self.console = Console()
        self.stats = AgentStats(total_iterations=total_iterations, plan_messages_limit=plan_limit)
        self.activities: list[ActivityLog] = []
        self.mode = mode
        self.max_activities = 20
        self._live: Optional[Live] = None
        self._paused = False
        self._stop_requested = False
        self._gutter_requested = False
        
        # Capture baseline usage at start to avoid double-counting current session
        from ..cli.registry import get_today_usage
        self.initial_ralph_usage = get_today_usage()
        
        # Calculate panel width based on terminal
        term_width = get_terminal_width()
        self.panel_width = max(
            self.MIN_PANEL_WIDTH,
            min(term_width - 4, self.MAX_PANEL_WIDTH)
        )
        
        # Load initial plan usage
        self._update_plan_usage()
    
    def start(self) -> None:
        """Start the live display."""
        self.console.clear()
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=4,
            transient=True,  # Replace content instead of stacking
        )
        self._live.start()
    
    def stop(self) -> None:
        """Stop the live display."""
        if self._live:
            self._live.stop()
            # Print final state so it persists after stopping
            self.console.print(self._render())
            self._live = None
    
    def refresh(self) -> None:
        """Refresh the display."""
        if self._live:
            self._live.update(self._render())
    
    def set_iteration(self, iteration: int) -> None:
        """Set current iteration number and start timer."""
        self.stats.iteration = iteration
        self.stats.iteration_start_time = datetime.now()
        # Reset per-iteration stats
        self.stats.input_tokens = 0
        self.stats.output_tokens = 0
        self.stats.total_cost_usd = 0.0
        self.stats.duration_ms = 0
        
        # Update plan usage at start of iteration so it's live
        self._update_plan_usage()
        
        self.refresh()
    
    def set_task(self, task: str, task_id: str = "") -> None:
        """Set current task description and ID."""
        self.stats.current_task = task
        self.stats.current_task_id = task_id
        self.refresh()
    
    def set_status(self, status: str) -> None:
        """Set current status."""
        self.stats.status = status
        self.refresh()
    
    def request_pause(self) -> None:
        """Request the loop to pause after current iteration."""
        self._paused = True
        self.log_activity("pause", "Pause requested - will pause after current iteration")
    
    def request_stop(self) -> None:
        """Request the loop to stop after current iteration."""
        self._stop_requested = True
        self.log_activity("stop", "Stop requested - will stop after current iteration")
    
    def request_gutter(self) -> None:
        """Request a fresh context (gutter) after current iteration."""
        self._gutter_requested = True
        self.log_activity("warning", "GUTTER requested - will start fresh iteration")
    
    def is_pause_requested(self) -> bool:
        """Check if pause was requested."""
        return self._paused
    
    def is_stop_requested(self) -> bool:
        """Check if stop was requested."""
        return self._stop_requested
    
    def is_gutter_requested(self) -> bool:
        """Check if gutter was requested."""
        return self._gutter_requested
    
    def clear_pause(self) -> None:
        """Clear the pause flag."""
        self._paused = False
    
    def clear_stop(self) -> None:
        """Clear the stop flag."""
        self._stop_requested = False
    
    def clear_gutter(self) -> None:
        """Clear the gutter flag."""
        self._gutter_requested = False
    
    def update_stats(
        self,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        duration_ms: Optional[int] = None,
        num_turns: Optional[int] = None,
        context_used_tokens: Optional[int] = None,
        context_limit: Optional[int] = None,
    ) -> None:
        """Update statistics for the CURRENT iteration.
        
        Args:
            input_tokens: Total input tokens used in this iteration so far
            output_tokens: Total output tokens used in this iteration so far
            cost_usd: Total cost for this iteration so far
            duration_ms: Total duration for this iteration so far
            num_turns: Total turns in this iteration so far
            context_used_tokens: Current context size estimate
            context_limit: Model context limit
        """
        if input_tokens is not None:
            self.stats.input_tokens = input_tokens
        if output_tokens is not None:
            self.stats.output_tokens = output_tokens
        if cost_usd is not None:
            self.stats.total_cost_usd = cost_usd
        if duration_ms is not None:
            self.stats.duration_ms = duration_ms
        if num_turns is not None:
            self.stats.num_turns = num_turns
        
        if context_used_tokens is not None:
            self.stats.context_used_tokens = context_used_tokens
        elif input_tokens is not None:
            # Fallback: current iteration's input tokens represent current context
            self.stats.context_used_tokens = input_tokens
            
        if context_limit is not None:
            self.stats.context_limit = context_limit
            
        if self.stats.context_limit > 0:
            self.stats.context_used_pct = (self.stats.context_used_tokens / self.stats.context_limit) * 100
        
        # Update plan usage
        self._update_plan_usage()
        
        self.refresh()

    def finish_iteration(self) -> None:
        """Finalize stats for the current iteration and add to cumulative totals."""
        self.stats.cumulative_input_tokens += self.stats.input_tokens
        self.stats.cumulative_output_tokens += self.stats.output_tokens
        self.stats.cumulative_cost_usd += self.stats.total_cost_usd
        self.stats.cumulative_duration_ms += self.stats.duration_ms
        self.refresh()
    
    def _update_plan_usage(self) -> None:
        """Update plan usage based on combined Claude Code and Ralph activity."""
        # Use session turns as a proxy for messages used in this session
        # Each iteration start counts as 1 turn, plus any additional turns during execution
        session_messages = max(self.stats.iteration, self.stats.session_turns)
        
        # Get baseline from Claude Code's official stats-cache
        claude_code_messages = 0
        try:
            import json
            from pathlib import Path
            
            stats_path = Path.home() / ".claude" / "stats-cache.json"
            if stats_path.exists():
                stats = json.loads(stats_path.read_text())
                daily_activity = stats.get("dailyActivity", [])
                today = datetime.now().strftime("%Y-%m-%d")
                
                for day in daily_activity:
                    if day.get("date") == today:
                        claude_code_messages = day.get("messageCount", 0)
                        break
        except Exception:
            pass
            
        # Get baseline from Ralph's persistent usage tracking
        from ..cli.registry import get_today_usage
        ralph_persistent_messages = get_today_usage()
        
        # Total = Official Claude Code + Ralph Persistent + Current Session
        total_messages = claude_code_messages + ralph_persistent_messages + session_messages
        self.stats.plan_messages_used = total_messages
        
        if self.stats.plan_messages_limit > 0:
            self.stats.plan_usage_pct = min(100.0, (total_messages / self.stats.plan_messages_limit) * 100)
        
        # Estimate reset time (5-hour rolling window from first session start)
        if not self.stats.plan_reset_time and self.stats.iteration_start_time:
            from datetime import timedelta
            self.stats.plan_reset_time = self.stats.iteration_start_time + timedelta(hours=5)
    
    def log_activity(
        self,
        icon_key: str,
        message: str,
        detail: str = "",
    ) -> None:
        """Log an activity entry."""
        icon = self.ICONS.get(icon_key, "•")
        self.activities.append(ActivityLog(
            timestamp=datetime.now(),
            icon=icon,
            message=message,
            detail=detail,
        ))
        
        # Trim old activities
        if len(self.activities) > self.max_activities:
            self.activities = self.activities[-self.max_activities:]
        
        self.refresh()
    
    def log_tool_use(self, tool_name: str, tool_input: dict) -> None:
        """Log a tool use event."""
        icon_key = self._get_tool_icon(tool_name)
        detail = self._format_tool_input(tool_name, tool_input)
        self.log_activity(icon_key, tool_name, detail)
    
    def log_thinking(self, text: str) -> None:
        """Log agent thinking/reasoning."""
        # Clean up the text - remove extra whitespace and newlines
        cleaned = " ".join(text.split())
        truncated = cleaned[:120] + "..." if len(cleaned) > 120 else cleaned
        self.log_activity("thinking", truncated)
    
    def log_text(self, text: str) -> None:
        """Log agent text output."""
        # Clean up the text - remove extra whitespace and newlines
        cleaned = " ".join(text.split())
        truncated = cleaned[:150] + "..." if len(cleaned) > 150 else cleaned
        self.log_activity("info", truncated)
    
    def _get_tool_icon(self, tool_name: str) -> str:
        """Get icon key for a tool."""
        tool_icons = {
            "Read": "file_read",
            "Write": "file_write",
            "Edit": "file_write",
            "Bash": "bash",
            "Glob": "search",
            "Grep": "search",
            "TodoWrite": "task",
        }
        return tool_icons.get(tool_name, "tool")
    
    def _format_tool_input(self, tool_name: str, tool_input: Optional[dict]) -> str:
        """Format tool input for display."""
        if not tool_input:
            return ""
        
        # Calculate max detail length based on panel width
        max_len = int(self.panel_width * 0.4)
            
        if tool_name == "Read":
            path = tool_input.get("file_path", "")
            return self._truncate_path(path, max_len)
        elif tool_name in ("Write", "Edit"):
            path = tool_input.get("file_path", "")
            return self._truncate_path(path, max_len)
        elif tool_name == "Bash":
            cmd = tool_input.get("command", "")
            # Clean up command - remove newlines
            cmd = " ".join(cmd.split())
            return cmd[:max_len] + "..." if len(cmd) > max_len else cmd
        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            return pattern[:max_len] if len(pattern) <= max_len else pattern[:max_len-3] + "..."
        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            return f'"{pattern[:max_len-4]}..."' if len(pattern) > max_len-2 else f'"{pattern}"'
        elif tool_name == "TodoWrite":
            return "(updating task list)"
        return ""
    
    def _truncate_path(self, path: str, max_len: int) -> str:
        """Truncate a file path intelligently, keeping the filename visible."""
        if len(path) <= max_len:
            return path
        
        # Try to show .../<last_two_components>
        parts = path.split("/")
        if len(parts) >= 2:
            suffix = "/".join(parts[-2:])
            if len(suffix) + 4 <= max_len:
                return ".../" + suffix
        
        # Just truncate from the beginning
        return "..." + path[-(max_len-3):]
    
    def _render(self) -> Panel:
        """Render the full display."""
        # Header
        mode_label = {
            "loop": "AFK Loop",
            "once": "Single Iteration",
            "spec": "Spec Discovery",
        }.get(self.mode, self.mode)
        
        # Build title
        title = f" Ralph Agent - {mode_label} "
        
        # Build content - single column layout for simplicity
        content = Table.grid(padding=(0, 1), expand=True)
        content.add_column(ratio=1)  # Full width single column
        
        # Header row with iteration and status
        header = Table.grid(expand=True)
        header.add_column(justify="left", ratio=1)
        header.add_column(justify="right", ratio=1)
        
        if self.stats.total_iterations > 0:
            iter_text = Text()
            iter_text.append("ITERATION ", style="bold white")
            iter_text.append(f"{self.stats.iteration}", style="bold cyan")
            if self.stats.total_iterations > 1:
                iter_text.append(f" / {self.stats.total_iterations}", style="dim")
            
            status_text = Text()
            status_color = {
                "idle": "dim",
                "running": "green",
                "paused": "magenta",
                "complete": "green",
                "error": "red",
            }.get(self.stats.status, "white")
            status_text.append("STATUS ", style="bold white")
            status_text.append(self.stats.status.upper(), style=f"bold {status_color}")
            
            header.add_row(iter_text, status_text)
        else:
            # Hide iteration counter for spec mode/conversations
            status_text = Text()
            status_color = {
                "idle": "dim",
                "running": "green",
                "complete": "green",
                "error": "red",
            }.get(self.stats.status, "white")
            status_text.append("STATUS ", style="bold white")
            status_text.append(self.stats.status.upper(), style=f"bold {status_color}")
            
            if self.mode == "spec":
                exchange_text = Text()
                exchange_text.append("EXCHANGES ", style="bold white")
                display_iter = max(1, self.stats.iteration) if self.stats.status != "idle" else 0
                exchange_text.append(f"{display_iter}", style="bold cyan")
                header.add_row(exchange_text, status_text)
            else:
                header.add_row(Text(), status_text)
        
        content.add_row(header)
        content.add_row()
        
        # Task row (full width)
        task_text = Text()
        label = "TOPIC " if self.mode == "spec" else "TASK "
        task_text.append(label, style="bold white")
        if self.stats.current_task_id:
            task_text.append(f"[{self.stats.current_task_id}] ", style="bold yellow")
        
        default_msg = "(analyzing...)" if self.mode == "spec" else "(reading requirements...)"
        task_text.append(
            self.stats.current_task or default_msg,
            style="cyan" if self.stats.current_task else "dim"
        )
        content.add_row(task_text)
        content.add_row()
        
        # Activity log (full width, no nested panel)
        activity_table = self._render_activities()
        content.add_row(activity_table)
        content.add_row()
        
        # Stats footer
        stats_text = self._render_stats()
        content.add_row(stats_text)
        
        # Controls hint if in loop mode (only on Unix where keyboard handling works)
        if self.mode == "loop" and self.stats.total_iterations > 1 and _KEYBOARD_SUPPORTED:
            content.add_row()
            hint_text = Text()
            hint_text.append("CONTROLS ", style="bold white")
            hint_text.append("[p]", style="bold cyan")
            hint_text.append(" pause  ", style="dim")
            hint_text.append("[g]", style="bold yellow")
            hint_text.append(" gutter  ", style="dim")
            hint_text.append("[s]", style="bold red")
            hint_text.append(" stop", style="dim")
            content.add_row(hint_text)
        
        return Panel(
            content,
            title=title,
            border_style="cyan",
            box=ROUNDED,
            width=self.panel_width,
        )
    
    def _render_activities(self) -> Table:
        """Render the activity log section - FULL width, no nested panel."""
        # Single column table for clean layout - will expand to fill parent
        table = Table.grid(padding=0, expand=True)
        # Allow wrapping for thinking messages
        table.add_column(ratio=1)
        
        # Activity header - Minimalist separator
        header = Text()
        header.append("─" * 4 + " ", style="blue")
        header.append("ACTIVITY", style="bold blue")
        header.append(" " + "─" * (self.panel_width - 16), style="blue")
        table.add_row(header)
        
        max_lines = self.ACTIVITY_PANEL_HEIGHT
        
        # Add placeholder if no activities
        if not self.activities:
            table.add_row(Text("  Waiting for agent activity...", style="dim italic"))
            line_count = 1
        else:
            line_count = 0
            
            # Show most recent activities that fit
            displayed_activities = self.activities[-max_lines:]
            
            for activity in displayed_activities:
                # Tool activities (with detail) - single line, truncate if needed
                if activity.detail:
                    line = Text(overflow="ellipsis", no_wrap=True)
                    line.append(f"{activity.icon} ", style="white")
                    line.append(activity.message, style="white")
                    line.append(":  ", style="dim")
                    line.append(activity.detail, style="dim")
                    table.add_row(line)
                    line_count += 1
                else:
                    # Thinking/reasoning messages - allow full display, no truncation
                    line = Text()
                    line.append(f"{activity.icon} ", style="white")
                    line.append(activity.message, style="italic dim white")
                    table.add_row(line)
                    line_count += 1
        
        # Fill remaining rows with empty content to maintain consistent height
        while line_count < self.ACTIVITY_PANEL_HEIGHT:
            table.add_row(Text(" "))
            line_count += 1
        
        return table
    
    def _render_stats(self) -> Text:
        """Render the statistics line."""
        text = Text()
        
        # Plan usage progress bar (first, most important)
        plan_pct = self.stats.plan_usage_pct
        plan_color = "green"
        if plan_pct > 80:
            plan_color = "red"
        elif plan_pct > 60:
            plan_color = "yellow"
        
        # Build progress bar with elegant minimalist block
        bar_width = 20
        filled = int(bar_width * plan_pct / 100)
        empty = bar_width - filled
        bar = "█" * filled + "░" * empty
        
        text.append("PLAN ", style="bold white")
        text.append(f"[{bar}]", style=f"{plan_color}")
        text.append(f" {plan_pct:.0f}%", style=f"bold {plan_color}")
        text.append(f" ({self.stats.plan_messages_used}/{self.stats.plan_messages_limit})", style="dim")
        
        # Show reset time if available
        if self.stats.plan_reset_time:
            time_left = self.stats.plan_reset_time - datetime.now()
            if time_left.total_seconds() > 0:
                hours = int(time_left.total_seconds() // 3600)
                mins = int((time_left.total_seconds() % 3600) // 60)
                text.append(f"  {hours}h {mins}m to reset", style="dim italic")
        text.append("\n")
        
        # Context health indicator
        health_color = "green"
        if self.stats.context_used_pct > 80:
            health_color = "red"
        elif self.stats.context_used_pct > 60:
            health_color = "yellow"
            
        # Current iteration stats
        tokens = f"{self.stats.input_tokens:,} in / {self.stats.output_tokens:,} out"
        cost = f"${self.stats.total_cost_usd:.2f}" if self.stats.total_cost_usd else "$0.00"
        
        # Real-time elapsed time
        if self.stats.iteration_start_time:
            elapsed = (datetime.now() - self.stats.iteration_start_time).total_seconds()
            duration = f"{elapsed:.0f}s"
        elif self.stats.duration_ms:
            duration = f"{self.stats.duration_ms / 1000:.1f}s"
        else:
            duration = "0s"
        
        text.append("CONTEXT ", style="bold white")
        text.append(f"{self.stats.context_used_pct:.1f}%", style=f"bold {health_color}")
        text.append(f" ({self.stats.context_used_tokens:,}/{self.stats.context_limit:,})", style="dim")
        text.append("\n")
        
        text.append("TOKENS ", style="bold white")
        text.append(f"{tokens:<25}", style="cyan")
        text.append("COST ", style="bold white")
        text.append(f"{cost:<10}", style="green")
        text.append("TIME ", style="bold white")
        text.append(duration, style="yellow")
        
        # Add cumulative if multiple iterations
        if self.stats.iteration > 1 and self.mode != "spec":
            text.append("\n")
            text.append("CUMULATIVE ", style="bold dim")
            cum_tokens = f"{self.stats.cumulative_input_tokens:,} in / {self.stats.cumulative_output_tokens:,} out"
            cum_cost = f"${self.stats.cumulative_cost_usd:.2f}"
            cum_time = f"{self.stats.cumulative_duration_ms / 1000:.1f}s"
            text.append(f"{cum_tokens}  |  {cum_cost}  |  {cum_time}", style="dim")
        
        return text
    
    def print_summary(self) -> None:
        """Print final summary after run completes."""
        self.console.print()
        
        summary = Table(title=" Run Summary ", box=ROUNDED, border_style="cyan")
        summary.add_column("Metric", style="bold white")
        summary.add_column("Value", justify="right", style="cyan")
        
        summary.add_row("Iterations", str(self.stats.iteration))
        summary.add_row(
            "Total Tokens",
            f"{self.stats.cumulative_input_tokens:,} in / {self.stats.cumulative_output_tokens:,} out"
        )
        summary.add_row("Total Cost", f"${self.stats.cumulative_cost_usd:.2f}")
        summary.add_row(
            "Total Duration",
            f"{self.stats.cumulative_duration_ms / 1000:.1f}s"
        )
        
        self.console.print(summary)
