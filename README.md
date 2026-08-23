# MacroQuant Ledger

A local personal dashboard for macro-quant research: view inventory, quant tracker, weekly reconciliation.

## Setup

```bash
pip install -r requirements.txt
python setup_speech_runtime.py
python app.py
```

Opens at `http://localhost:8080`.

## Local settings

Use **··· → Settings** in the app to configure the Obsidian export folder.
The value is stored in `data/user_settings.json` and can be overridden with
the `OBSIDIAN_EXPORT_PATH` environment variable.
