#!/usr/bin/env python3
"""MacroQuant Ledger launcher.

Replaces the brittle netstat + taskkill batch logic with PID-file-based
single-instance enforcement. The server is bound to localhost by default,
started without a console window, and the launcher exits once the browser
has been opened.

Environment variables:
    MQLEDGER_PORT   port to serve on (default: 8080)
    MQLEDGER_HOST   host to bind to (default: 127.0.0.1)
"""
from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / "data" / "mqledger.pid"
LOG_FILE = ROOT / "data" / "logs" / "mqledger.log"

PORT = int(os.environ.get("MQLEDGER_PORT", "8080"))
HOST = os.environ.get("MQLEDGER_HOST", "127.0.0.1")
URL = f"http://{HOST}:{PORT}"


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        data = json.loads(PID_FILE.read_text(encoding="utf-8"))
        return int(data["pid"])
    except Exception:
        return None


def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, OSError):
        return False


def _pid_for_port(port: int) -> int | None:
    """Windows fallback: find the PID listening on a given port."""
    if sys.platform != "win32":
        return None
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in result.stdout.splitlines():
            match = re.search(rf"\s*{re.escape(HOST)}:{port}\s+\S+\s+LISTENING\s+(\d+)", line)
            if match:
                return int(match.group(1))
    except Exception:
        pass
    return None


def _terminate_existing() -> None:
    pid = _read_pid()
    if pid is not None and not _is_process_running(pid):
        pid = _pid_for_port(PORT) if _is_port_open(HOST, PORT) else None

    if pid is None:
        PID_FILE.unlink(missing_ok=True)
        return

    print(f"Stopping existing MacroQuant Ledger process (PID {pid})...")

    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                if not _is_process_running(pid):
                    break
                time.sleep(0.1)
            if _is_process_running(pid):
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    PID_FILE.unlink(missing_ok=True)


def _write_pid(pid: int) -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(
        json.dumps(
            {
                "pid": pid,
                "host": HOST,
                "port": PORT,
                "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _start_server() -> subprocess.Popen:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log_handle = open(LOG_FILE, "a", encoding="utf-8")

    env = os.environ.copy()
    env["MQLEDGER_HOST"] = HOST

    python_exe = sys.executable
    if python_exe.lower().endswith("python.exe"):
        pythonw = Path(python_exe).with_name("pythonw.exe")
        if pythonw.exists():
            python_exe = str(pythonw)

    cmd = [python_exe, str(ROOT / "app.py")]

    kwargs: dict = {
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NO_WINDOW
        )

    return subprocess.Popen(cmd, env=env, **kwargs)


def _wait_for_server(timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _is_port_open(HOST, PORT):
            return True
        time.sleep(0.2)
    return False


def _open_browser() -> None:
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["cmd", "/c", "start", "", f"microsoft-edge:{URL}"],
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return
        except Exception:
            pass
    import webbrowser

    webbrowser.open(URL)


def main() -> int:
    _terminate_existing()

    print(f"Starting MacroQuant Ledger on {URL} ...")
    proc = _start_server()
    _write_pid(proc.pid)

    if not _wait_for_server():
        print("Server failed to start. Check data/logs/mqledger.log for details.")
        proc.terminate()
        return 1

    _open_browser()
    print("Browser opened. MacroQuant Ledger is running.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
