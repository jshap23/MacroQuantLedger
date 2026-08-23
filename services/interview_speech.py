"""Local, retry-safe speech transcription for interview answers."""
from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool


MODEL_DIR = Path(__file__).resolve().parent.parent / "data" / "models" / "whisper"
RUNTIME_DIR = Path(__file__).resolve().parent.parent / "data" / "speech_runtime"
WORKER_FILE = Path(__file__).resolve().parent / "interview_speech_worker.py"
MAX_AUDIO_BYTES = 40 * 1024 * 1024
_ROUTES_REGISTERED = False


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


def speech_model_name() -> str:
    return _env("INTERVIEW_STT_MODEL", "small.en")


def _device_candidates() -> list[str]:
    # CPU is the reliable Windows default. Set INTERVIEW_STT_DEVICE=cuda after
    # installing the matching CUDA 12 cuBLAS runtime.
    requested = _env("INTERVIEW_STT_DEVICE", "cpu").lower()
    if requested == "auto":
        return ["cuda", "cpu"]
    return ["cuda"] if requested == "cuda" else ["cpu"]


def _run_worker(
    path: Path, language: str, context: str, device: str,
) -> dict:
    command = [
        sys.executable, "-S", str(WORKER_FILE), str(path), language,
        context[:500], speech_model_name(), device, str(MODEL_DIR),
        str(RUNTIME_DIR),
    ]
    environment = os.environ.copy()
    environment["PYTHONNOUSERSITE"] = "1"
    environment["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    completed = subprocess.run(
        command,
        cwd=str(WORKER_FILE.parent.parent),
        env=environment,
        capture_output=True,
        text=True,
        timeout=int(_env("INTERVIEW_STT_TIMEOUT", "300")),
        creationflags=flags,
        check=False,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    data = {}
    if lines:
        try:
            data = json.loads(lines[-1])
        except json.JSONDecodeError:
            data = {}
    if completed.returncode or not data.get("text"):
        detail = data.get("error") or completed.stderr.strip() or "Speech worker failed."
        raise RuntimeError(f"{device}: {detail}")
    return data


def transcribe_file(path: Path, language: str = "en", context: str = "") -> dict:
    if not (RUNTIME_DIR / "numpy" / "__init__.py").exists():
        raise RuntimeError(
            "The isolated speech runtime is missing. Run: "
            "conda run -n mqledger python setup_speech_runtime.py"
        )
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    errors = []
    for device in _device_candidates():
        try:
            return _run_worker(path, language or "en", context, device)
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
    raise RuntimeError("Local transcription failed. " + " | ".join(errors))


def _suffix(content_type: str) -> str:
    content_type = (content_type or "").lower()
    if "ogg" in content_type:
        return ".ogg"
    if "mp4" in content_type:
        return ".mp4"
    if "wav" in content_type:
        return ".wav"
    return ".webm"


def register_interview_speech_routes(app) -> None:
    """Register the upload endpoint once on the NiceGUI/FastAPI app."""
    global _ROUTES_REGISTERED
    if _ROUTES_REGISTERED:
        return
    _ROUTES_REGISTERED = True

    @app.post("/api/interview/transcribe")
    async def transcribe_interview_answer(
        audio: UploadFile = File(...),
        language: str = Form("en"),
        context: str = Form(""),
    ):
        payload = await audio.read(MAX_AUDIO_BYTES + 1)
        if not payload:
            raise HTTPException(status_code=400, detail="The recording was empty.")
        if len(payload) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="The recording is too large.")

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=_suffix(audio.content_type), delete=False,
            ) as handle:
                handle.write(payload)
                temp_path = Path(handle.name)
            return await run_in_threadpool(
                transcribe_file, temp_path, language.strip(), context.strip(),
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
