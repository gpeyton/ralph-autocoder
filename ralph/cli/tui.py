"""Ralph TUI - Terminal user interface with Rich panels."""

import sys
from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

import questionary
from questionary import Style


# Shared console instance
console = Console()


# Custom style for questionary prompts
PROMPT_STYLE = Style([
    ('qmark', 'fg:#6366f1 bold'),
    ('question', 'fg:#e2e8f0'),
    ('answer', 'fg:#22c55e bold'),
    ('pointer', 'fg:#6366f1 bold'),
    ('highlighted', 'bg:#6366f1 fg:#ffffff bold'),
    ('selected', 'fg:#22c55e'),
    ('instruction', 'fg:#64748b'),
])


class OutputBuffer:
    """Buffer for collecting output messages."""
    
    def __init__(self, max_lines: int = 50):
        self.lines: list[Text] = []
        self.max_lines = max_lines
    
    def add(self, message: str, style: str = "") -> None:
        """Add a message to the buffer."""
        if style:
            self.lines.append(Text(message, style=style))
        else:
            self.lines.append(Text.from_markup(message))
        
        # Trim old lines
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines:]
    
    def render(self) -> Group:
        """Render the buffer as a Rich Group."""
        return Group(*self.lines) if self.lines else Group(Text("", style="dim"))
    
    def clear(self) -> None:
        """Clear the buffer."""
        self.lines = []


class RalphTUI:
    """Ralph Terminal UI with separate output and input panels."""
    
    # Fixed height for consistent display
    MIN_OUTPUT_LINES = 15
    
    def __init__(self, title: str = "Ralph - AI Coding Loop"):
        self.title = title
        self.output = OutputBuffer()
        self._live: Optional[Live] = None
        self._started = False
    
    def _render(self) -> Panel:
        """Render the output panel with fixed minimum height."""
        lines = self.output.lines.copy()
        
        # Pad to minimum height for consistent sizing
        while len(lines) < self.MIN_OUTPUT_LINES:
            lines.append(Text(""))
        
        content = Group(*lines)
        return Panel(
            content,
            title=f"[bold #6366f1]{self.title}[/]",
            border_style="#6366f1",
            padding=(1, 2),
        )
    
    def _refresh(self) -> None:
        """Refresh the display."""
        if self._live:
            self._live.update(self._render())
    
    def start(self) -> None:
        """Start the TUI display."""
        console.clear()
        self._started = True
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=4,
            transient=True,  # Replace content instead of stacking
        )
        self._live.start()
    
    def stop(self) -> None:
        """Stop the TUI display."""
        if self._live:
            # Print final state before stopping
            self._live.stop()
            # Print final output so it persists
            console.print(self._render())
            self._live = None
        self._started = False
    
    def log(self, message: str, style: str = "") -> None:
        """Log a message to the output panel."""
        self.output.add(message, style)
        self._refresh()
    
    def log_success(self, message: str) -> None:
        """Log a success message."""
        self.log(f"v {message}", "green")
    
    def log_error(self, message: str) -> None:
        """Log an error message."""
        self.log(f"x {message}", "red")
    
    def log_info(self, message: str) -> None:
        """Log an info message."""
        self.log(f"i {message}", "cyan")
    
    def log_step(self, step: int, total: int, message: str) -> None:
        """Log a step indicator."""
        self.log(f"[bold cyan][{step}/{total}][/bold cyan] {message}")
    
    def _pause_live(self) -> None:
        """Pause the live display for input - print current state."""
        if self._live:
            self._live.stop()
            # Print the current panel state so user sees context
            console.print(self._render())
            self._live = None
    
    def _resume_live(self) -> None:
        """Resume the live display after input - clear and restart."""
        # Clear and restart fresh
        console.clear()
        self._live = Live(
            self._render(),
            console=console,
            refresh_per_second=4,
            transient=True,
        )
        self._live.start()
    
    def prompt_text(self, prompt: str, default: str = "") -> str:
        """Prompt for text input with separated input area."""
        self._pause_live()
        
        # Show input panel
        console.print()
        console.print(Panel(
            f"[bold]{prompt}[/bold]",
            border_style="#6366f1",
            padding=(0, 1),
        ))
        
        result = questionary.text(
            "›",
            default=default,
            style=PROMPT_STYLE,
        ).ask()
        
        if result is None:
            console.print("\n[dim]Cancelled.[/dim]")
            sys.exit(0)
        
        result = result.strip()
        
        # Log the input to output buffer
        self.log(f"[dim]› {prompt}:[/dim] [cyan]{result}[/cyan]")
        
        # Clear input area and resume
        self._resume_live()
        
        return result
    
    def prompt_choice(self, prompt: str, choices: list[str], default: int = 0) -> int:
        """Prompt for a choice with separated input area."""
        self._pause_live()
        
        # Show input panel
        console.print()
        console.print(Panel(
            f"[bold]{prompt}[/bold]\n[dim](↑↓ to move, enter to select, ctrl+c to cancel)[/dim]",
            border_style="#6366f1",
            padding=(0, 1),
        ))
        
        result = questionary.select(
            "›",
            choices=choices,
            default=choices[default] if 0 <= default < len(choices) else choices[0],
            style=PROMPT_STYLE,
            use_shortcuts=False,
        ).ask()
        
        if result is None:
            console.print("\n[dim]Cancelled.[/dim]")
            sys.exit(0)
        
        index = choices.index(result)
        
        # Log the selection to output buffer
        self.log(f"[dim]› {prompt}:[/dim] [cyan]{result}[/cyan]")
        
        # Clear and resume
        self._resume_live()
        
        return index
    
    def prompt_confirm(self, prompt: str, default: bool = True) -> bool:
        """Prompt for confirmation with separated input area."""
        self._pause_live()
        
        # Show input panel
        console.print()
        suffix = "[Y/n]" if default else "[y/N]"
        console.print(Panel(
            f"[bold]{prompt}[/bold] {suffix}",
            border_style="#6366f1",
            padding=(0, 1),
        ))
        
        result = questionary.confirm(
            "›",
            default=default,
            style=PROMPT_STYLE,
        ).ask()
        
        if result is None:
            console.print("\n[dim]Cancelled.[/dim]")
            sys.exit(0)
        
        # Log to output buffer
        self.log(f"[dim]› {prompt}:[/dim] [cyan]{'Yes' if result else 'No'}[/cyan]")
        
        # Clear and resume
        self._resume_live()
        
        return result
    
    def show_status(self, tasks_done: int, tasks_total: int, progress_entries: int) -> None:
        """Show quick project status."""
        self.log(f"  Tasks: {tasks_done}/{tasks_total} complete")
        self.log(f"  Progress entries: {progress_entries}")


# Global TUI instance
_tui: Optional[RalphTUI] = None


def get_tui() -> RalphTUI:
    """Get or create the global TUI instance."""
    global _tui
    if _tui is None:
        _tui = RalphTUI()
    return _tui


def start_tui(title: str = "Ralph - AI Coding Loop") -> RalphTUI:
    """Start the TUI and return it."""
    global _tui
    _tui = RalphTUI(title)
    _tui.start()
    return _tui


def stop_tui() -> None:
    """Stop the TUI."""
    global _tui
    if _tui:
        _tui.stop()
        _tui = None
