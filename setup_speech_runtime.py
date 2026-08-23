"""Install the isolated NumPy wheel used by local interview transcription."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parent / "data" / "speech_runtime"


def main() -> int:
    if (RUNTIME_DIR / "numpy" / "__init__.py").exists():
        print(f"Speech runtime ready: {RUNTIME_DIR}")
        return 0
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "pip", "install", "--target", str(RUNTIME_DIR),
        "--only-binary=:all:", "--upgrade", "numpy<3",
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        return completed.returncode
    print(f"Speech runtime installed: {RUNTIME_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
