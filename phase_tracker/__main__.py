from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Track and archive three-agent project handoffs")
    parser.add_argument("--root", type=Path, help="Project root to open")
    args = parser.parse_args()

    try:
        from .main_window import run
    except ImportError as error:
        if error.name == "PySide6" or str(error.name).startswith("PySide6."):
            parser.error("PySide6 is not installed. Run ./install.sh first.")
        raise
    return run(args.root)


if __name__ == "__main__":
    raise SystemExit(main())

