"""Utility functions and helpers for Ralph CLI."""

import asyncio
import os
import sys
import threading
import time
from pathlib import Path

import questionary
from questionary import Style


class Colors:
    """ANSI color codes."""
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    CYAN = "\033[0;36m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    NC = "\033[0m"  # No Color


# Custom style for questionary prompts - Claude Code inspired
PROMPT_STYLE = Style([
    ('qmark', 'fg:#6366f1 bold'),       # Indigo marker
    ('question', 'fg:#e2e8f0'),          # Light gray question
    ('answer', 'fg:#22c55e bold'),       # Green answer
    ('pointer', 'fg:#6366f1 bold'),      # Indigo pointer
    ('highlighted', 'fg:#6366f1 bold'),  # Indigo highlighted
    ('selected', 'fg:#22c55e'),          # Green selected
    ('instruction', 'fg:#64748b'),       # Slate instruction
])


def print_separator():
    """Print a subtle separator line."""
    print(f"{Colors.DIM}{'─' * 56}{Colors.NC}")


class ThinkingSpinner:
    """A spinner that shows while Claude is thinking.
    
    Usage:
        spinner = ThinkingSpinner()
        spinner.start()
        # ... do work ...
        spinner.stop()
        
    Or as context manager:
        with ThinkingSpinner():
            # ... do work ...
    """
    
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    
    def __init__(self, message: str = "Thinking"):
        self.message = message
        self._running = False
        self._thread = None
    
    def _spin(self):
        """Animation loop running in background thread."""
        idx = 0
        while self._running:
            frame = self.FRAMES[idx % len(self.FRAMES)]
            # \r returns to start of line, \033[K clears to end
            sys.stdout.write(f"\r{Colors.DIM}{frame} {self.message}...{Colors.NC}\033[K")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.08)
        # Clear the line when done
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
    
    def start(self):
        """Start the spinner."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop the spinner."""
        if not self._running:
            return
        self._running = False
        if self._thread:
            self._thread.join(timeout=0.5)
            self._thread = None
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, *args):
        self.stop()


class AsyncThinkingSpinner:
    """Async version of the thinking spinner.
    
    Usage:
        async with AsyncThinkingSpinner():
            await some_async_work()
    """
    
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    
    def __init__(self, message: str = "Thinking"):
        self.message = message
        self._task = None
    
    async def _spin(self):
        """Animation loop."""
        idx = 0
        try:
            while True:
                frame = self.FRAMES[idx % len(self.FRAMES)]
                sys.stdout.write(f"\r{Colors.DIM}{frame} {self.message}...{Colors.NC}\033[K")
                sys.stdout.flush()
                idx += 1
                await asyncio.sleep(0.08)
        except asyncio.CancelledError:
            # Clear the line when cancelled
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()
    
    async def __aenter__(self):
        self._task = asyncio.create_task(self._spin())
        return self
    
    async def __aexit__(self, *args):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


def get_ralph_root() -> Path:
    """Get the root directory of the ralph installation."""
    return Path(__file__).parent.parent


def get_templates_dir() -> Path:
    """Get the templates directory."""
    return get_ralph_root() / "templates"


def resolve_project_path(project: str) -> Path:
    """Resolve project path - can be '.', relative, or absolute.
    
    Handles:
    - '.' for current directory
    - Quoted paths (strips surrounding quotes)
    - Absolute paths
    - Relative paths (resolved from cwd)
    - Home directory expansion (~)
    """
    # Strip surrounding quotes if present
    project = project.strip().strip("'\"")
    
    if project == ".":
        return Path.cwd()
    
    # Expand ~ to home directory
    if project.startswith("~"):
        project = os.path.expanduser(project)
    
    path = Path(project)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def print_header(title: str):
    """Print a styled header."""
    print()
    print(f"{Colors.BOLD}{Colors.CYAN}┌{'─' * 54}┐{Colors.NC}")
    print(f"{Colors.BOLD}{Colors.CYAN}│{Colors.NC}  {title:<52}{Colors.BOLD}{Colors.CYAN}│{Colors.NC}")
    print(f"{Colors.BOLD}{Colors.CYAN}└{'─' * 54}┘{Colors.NC}")
    print()


def print_success(message: str):
    """Print a success message."""
    print(f"{Colors.GREEN}v {message}{Colors.NC}")


def print_error(message: str):
    """Print an error message."""
    print(f"{Colors.RED}x {message}{Colors.NC}")


def print_info(message: str):
    """Print an info message."""
    print(f"{Colors.CYAN}i {message}{Colors.NC}")


def print_step(step: int, total: int, message: str):
    """Print a step indicator."""
    print(f"{Colors.BOLD}[{step}/{total}]{Colors.NC} {message}")


def sanitize_project_name(name: str) -> str:
    """Sanitize project name to lowercase with hyphens."""
    return "".join(c if c.isalnum() or c == "-" else "-" for c in name.lower()).strip("-")


def prompt_choice(prompt: str, choices: list[str], default: int = 0) -> int:
    """Prompt user to choose from a list of options.
    
    Use arrow keys to navigate, Enter to select, Ctrl+C to exit.
    Returns the index of the selected choice.
    """
    print()
    print_separator()
    result = questionary.select(
        prompt,
        choices=choices,
        default=choices[default] if 0 <= default < len(choices) else choices[0],
        style=PROMPT_STYLE,
        qmark="›",
        instruction="(↑↓ to move, enter to select, ctrl+c to cancel)",
        use_shortcuts=False,
    ).ask()
    
    if result is None:
        print("\nCancelled.")
        sys.exit(0)
    
    return choices.index(result)


async def prompt_choice_async(prompt: str, choices: list[str], default: int = 0) -> int:
    """Async version of prompt_choice for use inside async functions.
    
    Use arrow keys to navigate, Enter to select, Ctrl+C to exit.
    Returns the index of the selected choice.
    """
    print()
    print_separator()
    result = await questionary.select(
        prompt,
        choices=choices,
        default=choices[default] if 0 <= default < len(choices) else choices[0],
        style=PROMPT_STYLE,
        qmark="›",
        instruction="(↑↓ to move, enter to select, ctrl+c to cancel)",
        use_shortcuts=False,
    ).ask_async()
    
    if result is None:
        print("\nCancelled.")
        sys.exit(0)
    
    return choices.index(result)


def prompt_input(prompt: str, default: str = "") -> str:
    """Prompt for text input.
    
    Ctrl+C to exit.
    """
    print()
    print_separator()
    result = questionary.text(
        prompt,
        default=default,
        style=PROMPT_STYLE,
        qmark="›",
    ).ask()
    
    if result is None:
        print("\nCancelled.")
        sys.exit(0)
    
    return result.strip()


async def prompt_input_async(prompt: str, default: str = "") -> str:
    """Async version of prompt_input for use inside async functions.
    
    Ctrl+C to exit.
    """
    print()
    print_separator()
    result = await questionary.text(
        prompt,
        default=default,
        style=PROMPT_STYLE,
        qmark="›",
    ).ask_async()
    
    if result is None:
        print("\nCancelled.")
        sys.exit(0)
    
    return result.strip()


def prompt_confirm(prompt: str, default: bool = True) -> bool:
    """Prompt for yes/no confirmation.
    
    Ctrl+C to exit.
    """
    print()
    print_separator()
    result = questionary.confirm(
        prompt,
        default=default,
        style=PROMPT_STYLE,
        qmark="›",
    ).ask()
    
    if result is None:
        print("\nCancelled.")
        sys.exit(0)
    
    return result


def create_question_handler():
    """Create a question handler for HITL interactions with Claude.
    
    Returns a function that can be passed to RalphAgent for handling
    AskUserQuestion tool calls during spec discovery.
    
    The handler displays questions using questionary and returns answers.
    """
    
    def handle_questions(questions: list[dict]) -> dict[str, str]:
        """Handle questions from Claude's AskUserQuestion tool.
        
        Args:
            questions: List of question dicts with:
                - question: The full question text
                - header: Short label (max 12 chars)
                - options: List of {label, description} dicts
                - multiSelect: Whether multiple answers allowed
        
        Returns:
            Dict mapping question text to answer string
        """
        answers = {}
        
        print()
        print(f"{Colors.BOLD}{Colors.CYAN}┌{'─' * 54}┐{Colors.NC}")
        print(f"{Colors.BOLD}{Colors.CYAN}│{Colors.NC}  {'Claude has questions for you':<52}{Colors.BOLD}{Colors.CYAN}│{Colors.NC}")
        print(f"{Colors.BOLD}{Colors.CYAN}└{'─' * 54}┘{Colors.NC}")
        
        for q in questions:
            question_text = q.get("question", "")
            header = q.get("header", "")
            options = q.get("options", [])
            multi_select = q.get("multiSelect", False)
            
            print()
            if header:
                print(f"{Colors.DIM}[{header}]{Colors.NC}")
            
            if options:
                # Create choices from options
                choices = [
                    f"{opt.get('label', '')} - {opt.get('description', '')}"
                    for opt in options
                ]
                
                if multi_select:
                    # Checkbox selection for multi-select
                    result = questionary.checkbox(
                        question_text,
                        choices=choices,
                        style=PROMPT_STYLE,
                        qmark="›",
                        instruction="(space to select, enter to confirm)",
                    ).ask()
                    
                    if result is None:
                        print("\nCancelled.")
                        sys.exit(0)
                    
                    # Extract just the labels for the answer
                    selected_labels = [
                        options[choices.index(r)].get("label", r)
                        for r in result
                    ]
                    answers[question_text] = ", ".join(selected_labels)
                else:
                    # Single select
                    result = questionary.select(
                        question_text,
                        choices=choices,
                        style=PROMPT_STYLE,
                        qmark="›",
                        instruction="(↑↓ to move, enter to select)",
                    ).ask()
                    
                    if result is None:
                        print("\nCancelled.")
                        sys.exit(0)
                    
                    # Extract just the label
                    selected_idx = choices.index(result)
                    answers[question_text] = options[selected_idx].get("label", result)
            else:
                # Free-form text input
                result = questionary.text(
                    question_text,
                    style=PROMPT_STYLE,
                    qmark="›",
                ).ask()
                
                if result is None:
                    print("\nCancelled.")
                    sys.exit(0)
                
                answers[question_text] = result.strip()
        
        print()
        return answers
    
    return handle_questions
