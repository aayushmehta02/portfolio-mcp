"""
Adds portfolio-mcp to Claude Desktop's MCP config.
Run once:  python setup_claude_desktop.py
"""
import json
import os
import shutil
from pathlib import Path

CONFIG_DIR  = Path.home() / "Library" / "Application Support" / "Claude"
CONFIG_FILE = CONFIG_DIR / "claude_desktop_config.json"

PROJECT_DIR = Path(__file__).parent.resolve()
VENV_PYTHON = PROJECT_DIR / ".venv" / "bin" / "python3"

ENTRY = {
    "command": str(VENV_PYTHON),
    "args":    ["-m", "portfolio_mcp"],
    "cwd":     str(PROJECT_DIR),
}

def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Read existing config (or start fresh)
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            config = json.load(f)
        shutil.copy(CONFIG_FILE, str(CONFIG_FILE) + ".bak")
        print(f"  Backed up existing config → {CONFIG_FILE}.bak")
    else:
        config = {}

    config.setdefault("mcpServers", {})

    if "portfolio-mcp" in config["mcpServers"]:
        print("  portfolio-mcp already present — updating entry.")

    config["mcpServers"]["portfolio-mcp"] = ENTRY

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\n✓ Config written to:\n  {CONFIG_FILE}\n")
    print("Next step: quit Claude Desktop completely and relaunch it.")
    print("Then ask Claude: 'Assess my portfolio'\n")

if __name__ == "__main__":
    main()
