"""Non-secret defaults for MacroQuant Ledger."""

# OpenRouter — OpenAI-compatible Chat Completions (https://openrouter.ai/docs)
OPENROUTER_BASE_URL_DEFAULT = "https://openrouter.ai/api/v1"
# Default model slug on OpenRouter; override with OPENROUTER_MODEL or per-task env vars
OPENROUTER_MODEL_DEFAULT = "moonshotai/kimi-k2.6"

OPENROUTER_MAX_TOKENS_POLISH = 600
OPENROUTER_MAX_TOKENS_BRIEFING = 1500
OPENROUTER_TEMPERATURE = 0.5
