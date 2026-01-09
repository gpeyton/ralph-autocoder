"""Project-level configuration for Ralph."""

import json
from pathlib import Path
from typing import Any, Optional

from .registry import get_global_config_path

# Default configuration settings
# NOTE: Ralph uses claude_agent_sdk which ONLY supports Anthropic Claude models
# Gemini, Grok, and other vendors are NOT supported through this SDK
DEFAULT_CONFIG = {
    "spec_model": "claude-opus-4-5-20251101",
    "loop_model": "claude-sonnet-4-5-20250929",
    "context_limit": 200000,
    "rotate_threshold": 0.8,
    "auto_gutter": True,
    "max_iterations": 20,
    # Plan usage tracking: MAX 5x = 225 msgs/5h, MAX 20x = 900 msgs/5h
    "plan_messages_limit": 225,
    "other_models": {
        "spec_model_options": [
            "claude-opus-4-5-20251101 (Default)",
            "claude-sonnet-4-5-20250929",
            "claude-sonnet-4-20250514"
        ],
        "loop_model_options": [
            "claude-sonnet-4-5-20250929 (Default)",
            "claude-opus-4-5-20251101",
            "claude-sonnet-4-20250514"
        ]
    }
}

def load_project_config() -> dict[str, Any]:
    """Load global configuration from settings.json in the Ralph folder.
    
    If the file doesn't exist, returns default configuration.
    
    Returns:
        Dict containing configuration settings
    """
    config_path = get_global_config_path()
    config = DEFAULT_CONFIG.copy()
    
    if config_path.exists():
        try:
            user_config = json.loads(config_path.read_text())
            # Update defaults with user settings
            for key, value in user_config.items():
                config[key] = value
        except Exception:
            # If JSON is invalid, stick with defaults
            pass
            
    return config

def save_project_config(config: dict[str, Any]) -> None:
    """Save configuration to settings.json in the Ralph folder.
    
    Args:
        config: Configuration dictionary to save
    """
    config_path = get_global_config_path()
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

def get_config_value(key: str, default: Any = None) -> Any:
    """Get a specific configuration value.
    
    Args:
        key: Configuration key to retrieve
        default: Default value if key is not found
        
    Returns:
        Configuration value
    """
    config = load_project_config()
    return config.get(key, default)
