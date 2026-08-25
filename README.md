# MacroQuant Ledger

A local personal dashboard for macro-quant research: view inventory, quant tracker, weekly reconciliation.

## Setup

```bash
pip install -r requirements.txt
python setup_speech_runtime.py
```

## Launch

Double-click `launch_macroQuantLedger.bat` for a production-style start
(no console window, single-instance enforcement, opens Microsoft Edge).

Or from an activated conda shell:

```bash
python launch.py
```

For development you can still run:

```bash
python app.py
```

Opens at `http://localhost:8080` by default.

## Local settings

Use **··· → Settings** in the app to configure the Obsidian export folder,
the LLM provider (OpenRouter or OpenCode Go), and per-provider API keys and
models. Values are stored in `data/user_settings.json` (gitignored) and can be
overridden with environment variables such as `OPENROUTER_API_KEY`,
`OPENCODE_API_KEY`, and `MQLEDGER_LLM_PROVIDER`.
