"""Run the nstack host review workflow using native Codex processes."""
from pathlib import Path
import sys

from review_adapter import CodexAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from review_workflow import main


if __name__ == "__main__":
    main(CodexAdapter)
