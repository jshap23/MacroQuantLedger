"""Isolated faster-whisper worker; invoked with Python's site loading disabled."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _configure_paths(runtime_dir: Path) -> None:
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    sys.path.insert(0, str(site_packages))
    sys.path.insert(0, str(runtime_dir))


def main() -> int:
    if len(sys.argv) != 8:
        print(json.dumps({"error": "Invalid speech worker arguments."}))
        return 2
    audio_path = Path(sys.argv[1])
    language, context, model_name, device = sys.argv[2:6]
    model_dir = Path(sys.argv[6])
    runtime_dir = Path(sys.argv[7])
    _configure_paths(runtime_dir)

    try:
        import numpy
        from faster_whisper import WhisperModel

        if runtime_dir.resolve() not in Path(numpy.__file__).resolve().parents:
            raise RuntimeError("The isolated speech numerical runtime is not active.")
        compute_type = "int8_float16" if device == "cuda" else "int8"
        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            download_root=str(model_dir),
        )
        segments, info = model.transcribe(
            str(audio_path),
            language=language or None,
            beam_size=5,
            vad_filter=False,
            initial_prompt=context[:500] or None,
            condition_on_previous_text=False,
        )
        text = " ".join(
            segment.text.strip() for segment in segments if segment.text.strip()
        ).strip()
        if not text:
            raise RuntimeError("No speech was detected in the recording.")
        print(json.dumps({
            "text": text,
            "language": getattr(info, "language", language),
            "device": device,
            "model": model_name,
        }))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "device": device}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
