"""Centralized credential loader — reads from env vars or ~/.claude-env"""
import os

_CLAUDE_ENV_PATH = os.path.expanduser("~/.claude-env")
_cache = {}


def _parse_claude_env():
    """Parse ~/.claude-env file (format: export VAR=value or VAR=value)."""
    if _cache:
        return _cache
    if not os.path.exists(_CLAUDE_ENV_PATH):
        return _cache
    with open(_CLAUDE_ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            _cache[key] = value
    return _cache


def get_key(name, required=True):
    """Return credential value from env var or ~/.claude-env.

    Args:
        name: Environment variable name.
        required: If True (default), raises RuntimeError when missing.
                  If False, returns None when missing.
    """
    value = os.environ.get(name)
    if value:
        return value
    env_data = _parse_claude_env()
    value = env_data.get(name)
    if value:
        return value
    if required:
        raise RuntimeError(
            f"Missing credential: {name}. "
            f"Set it as an env var or add it to {_CLAUDE_ENV_PATH}"
        )
    return None
