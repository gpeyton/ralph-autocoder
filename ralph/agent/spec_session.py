"""Spec Creation Session - Conversational spec discovery with Claude.

This module provides a continuous conversation model for spec creation,
similar to autocoder's SpecChatSession. Unlike the iteration-based approach,
this maintains a persistent Claude client and true back-and-forth conversation.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Callable, Optional

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

from .output import AgentDisplay

logger = logging.getLogger(__name__)


class SpecSession:
    """Manages a spec creation conversation with Claude.
    
    This is a continuous conversation (NOT iterations) where:
    1. Start with initial prompt
    2. Claude asks questions
    3. User responds
    4. Repeat until spec is complete
    
    IMPORTANT: During spec discovery, Claude can READ from the target project
    but can ONLY WRITE to the Ralph workspace (spec-session.md).
    No files should be created in the target project until the coding loop.
    """
    
    SPEC_COMPLETE_SIGNAL = "<promise>SPEC_COMPLETE</promise>"
    
    # Tools for spec discovery - READ ONLY from target, write to workspace
    SPEC_TOOLS = [
        "Read",
        "Glob",
        "Grep",
        "Write",  # Restricted to workspace only via permission handler
        "Edit",   # Restricted to workspace only via permission handler
    ]
    
    def __init__(
        self,
        project_dir: Path,
        workspace_dir: Path,
        display: Optional[AgentDisplay] = None,
        model: str = "claude-3-5-sonnet-20241022",
        context_limit: int = 200000,
    ):
        """Initialize the spec session.
        
        Args:
            project_dir: Path to the TARGET project directory (read-only access)
            workspace_dir: Path to Ralph's workspace (write access for spec files)
            display: Optional display for showing activity
            model: Claude model to use
            context_limit: Maximum context tokens for this model
        """
        self.project_dir = project_dir.resolve()
        self.workspace_dir = workspace_dir.resolve()
        self.display = display
        self.model = model
        self.context_limit = context_limit
        self.client: Optional[ClaudeSDKClient] = None
        self._client_context = None  # For async context manager
        self.messages: list[dict] = []
        self.complete: bool = False
        self.created_at = datetime.now()
        
        # Stats tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        self.num_exchanges = 0
    
    async def close(self) -> None:
        """Clean up resources and close the Claude client."""
        if self._client_context:
            try:
                await self._client_context.__aexit__(None, None, None)
            except Exception as e:
                logger.warning(f"Error closing Claude client: {e}")
            finally:
                self._client_context = None
                self.client = None
    
    async def start(self, prompt: str) -> AsyncGenerator[dict, None]:
        """Initialize session and get initial response from Claude.
        
        Args:
            prompt: The full spec discovery prompt (sent to query())
            
        Yields:
            Message chunks: {"type": "text"|"tool"|"thinking"|"complete", ...}
        """
        from .permissions import create_spec_permission_handler
        
        # Ensure workspace directory exists
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Create permission handler that:
        # - Allows READ from target project
        # - Only allows WRITE to workspace directory
        can_use_tool = create_spec_permission_handler(
            target_dir=self.project_dir,
            workspace_dir=self.workspace_dir,
        )
        
        # Build options
        options = ClaudeAgentOptions(
            model=self.model,
            allowed_tools=self.SPEC_TOOLS,
            permission_mode="acceptEdits",
            max_turns=100,  # Support long conversations
            cwd=str(self.project_dir),  # CWD is target for reading context
            can_use_tool=can_use_tool,
        )
        
        try:
            # Create client and enter context
            client_instance = ClaudeSDKClient(options=options)
            self.client = await client_instance.__aenter__()
            self._client_context = client_instance
            
        except Exception as e:
            logger.exception("Failed to create Claude client")
            yield {"type": "error", "content": f"Failed to initialize: {e}"}
            return
        
        # Start the conversation with the full prompt
        try:
            async for chunk in self._query(prompt):
                yield chunk
            yield {"type": "response_done"}
        except Exception as e:
            logger.exception("Failed to start spec session")
            yield {"type": "error", "content": f"Error starting session: {e}"}
    
    async def send_message(self, user_message: str) -> AsyncGenerator[dict, None]:
        """Send user message and stream Claude's response.
        
        Args:
            user_message: The user's response to Claude's questions
            
        Yields:
            Message chunks with type: text, tool, thinking, complete, error
        """
        if not self.client:
            yield {"type": "error", "content": "Session not initialized. Call start() first."}
            return
        
        # Store user message
        self.messages.append({
            "role": "user",
            "content": user_message,
            "timestamp": datetime.now().isoformat(),
        })
        
        self.num_exchanges += 1
        if self.display:
            self.display.set_iteration(self.num_exchanges)
        
        try:
            async for chunk in self._query(user_message):
                yield chunk
            yield {"type": "response_done"}
        except Exception as e:
            logger.exception("Error during Claude query")
            yield {"type": "error", "content": f"Error: {e}"}
    
    async def _query(self, message: str) -> AsyncGenerator[dict, None]:
        """Internal method to query Claude and stream responses.
        
        Handles assistant messages, tool use, and completion detection.
        """
        if not self.client:
            return
        
        await self.client.query(message)
        
        current_text = ""
        
        async for msg in self.client.receive_response():
            msg_type = type(msg).__name__
            
            if msg_type == "AssistantMessage" and hasattr(msg, "content"):
                for block in msg.content:
                    block_type = type(block).__name__
                    
                    if block_type == "TextBlock" and hasattr(block, "text"):
                        text = block.text
                        if text:
                            current_text += text
                            yield {"type": "text", "content": text}
                            
                            # Store in messages
                            self.messages.append({
                                "role": "assistant",
                                "content": text,
                                "timestamp": datetime.now().isoformat(),
                            })
                            
                            # Log to display if available
                            if self.display:
                                self.display.log_text(text)
                    
                    elif block_type == "ThinkingBlock" and hasattr(block, "thinking"):
                        yield {"type": "thinking", "content": block.thinking}
                        if self.display:
                            self.display.log_thinking(block.thinking)
                    
                    elif block_type == "ToolUseBlock":
                        # Yield tool information for streaming display
                        tool_name = getattr(block, "name", "Tool")
                        tool_input = getattr(block, "input", {})
                        
                        # Format tool input for display
                        input_str = self._format_tool_input(tool_name, tool_input)
                        yield {"type": "tool", "name": tool_name, "input": input_str}
                        
                        # Log to display if available
                        if self.display:
                            self.display.log_tool_use(tool_name, tool_input)
            
            elif msg_type == "ResultMessage":
                # Extract usage stats
                usage = getattr(msg, "usage", None)
                if usage:
                    # usage can be a dict or an object
                    if hasattr(usage, "get"):
                        input_tokens = usage.get("input_tokens", 0)
                        output_tokens = usage.get("output_tokens", 0)
                    else:
                        input_tokens = getattr(usage, "input_tokens", 0)
                        output_tokens = getattr(usage, "output_tokens", 0)
                        
                    self.total_input_tokens += input_tokens
                    self.total_output_tokens += output_tokens
                
                cost = getattr(msg, "total_cost_usd", 0.0)
                if cost:
                    self.total_cost_usd += cost
                
                # Update display stats if available
                if self.display:
                    self.display.update_stats(
                        input_tokens=self.total_input_tokens,
                        output_tokens=self.total_output_tokens,
                        cost_usd=self.total_cost_usd,
                        context_used_tokens=self.total_input_tokens,
                        context_limit=self.context_limit,
                    )
        
        # Check for completion signal
        if self.SPEC_COMPLETE_SIGNAL in current_text:
            self.complete = True
            yield {"type": "complete", "content": "Spec discovery complete!"}
            if self.display:
                self.display.log_activity("complete", "Spec complete!")
    
    def _format_tool_input(self, tool_name: str, tool_input: dict) -> str:
        """Format tool input for display."""
        if not tool_input:
            return ""
            
        if tool_name == "Read":
            return tool_input.get("file_path", "")
        elif tool_name in ("Write", "Edit"):
            return tool_input.get("file_path", "")
        elif tool_name == "Bash":
            cmd = tool_input.get("command", "")
            return cmd[:80] + "..." if len(cmd) > 80 else cmd
        elif tool_name == "Glob":
            return tool_input.get("pattern", "")
        elif tool_name == "Grep":
            return tool_input.get("pattern", "")
        return str(tool_input)[:80]
    
    def is_complete(self) -> bool:
        """Check if spec discovery is complete."""
        return self.complete
    
    def get_messages(self) -> list[dict]:
        """Get all messages in the conversation."""
        return self.messages.copy()
    
    def get_stats(self) -> dict:
        """Get session statistics."""
        return {
            "num_exchanges": self.num_exchanges,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "cost_usd": self.total_cost_usd,
            "duration_seconds": (datetime.now() - self.created_at).total_seconds(),
        }


async def run_spec_conversation(
    project_dir: Path,
    system_prompt: str,
    get_user_input: Callable[[], str],
    display: Optional[AgentDisplay] = None,
    on_text: Optional[Callable[[str], None]] = None,
) -> dict:
    """Run a complete spec discovery conversation.
    
    This is a convenience function that manages the full conversation loop:
    1. Starts the session
    2. Shows Claude's questions
    3. Gets user input
    4. Sends responses
    5. Repeats until complete
    
    Args:
        project_dir: Path to project directory
        system_prompt: The spec discovery prompt
        get_user_input: Callback to get user's response (blocking)
        display: Optional display for activity
        on_text: Optional callback for streaming text chunks
    
    Returns:
        Dict with stats and messages from the conversation
    """
    session = SpecSession(project_dir, display=display)
    
    try:
        # Start the session
        async for chunk in session.start(system_prompt):
            if chunk["type"] == "text" and on_text:
                on_text(chunk["content"])
            elif chunk["type"] == "error":
                logger.error(chunk["content"])
                return {"error": chunk["content"], "stats": session.get_stats()}
        
        # Main conversation loop
        while not session.is_complete():
            # Get user input (this blocks waiting for user)
            user_response = get_user_input()
            
            # Check for exit signals
            if user_response.lower() in ("quit", "exit", "done", "q"):
                break
            
            # Send to Claude and get response
            async for chunk in session.send_message(user_response):
                if chunk["type"] == "text" and on_text:
                    on_text(chunk["content"])
                elif chunk["type"] == "error":
                    logger.error(chunk["content"])
                    break
        
        return {
            "complete": session.is_complete(),
            "stats": session.get_stats(),
            "messages": session.get_messages(),
        }
    
    finally:
        await session.close()
