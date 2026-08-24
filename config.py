"""Non-secret defaults for MacroQuant Ledger."""

# OpenRouter — OpenAI-compatible Chat Completions (https://openrouter.ai/docs)
OPENROUTER_BASE_URL_DEFAULT = "https://openrouter.ai/api/v1"
# Default model slug on OpenRouter; override with OPENROUTER_MODEL or per-task env vars
OPENROUTER_MODEL_DEFAULT = "moonshotai/kimi-k2.6"

OPENROUTER_MAX_TOKENS_POLISH = 600
OPENROUTER_TEMPERATURE = 0.5

# User-facing local defaults. Leave blank to configure in the app under
# ··· → Settings. OBSIDIAN_EXPORT_PATH overrides this value when set.
OBSIDIAN_EXPORT_PATH_DEFAULT = r"C:\Users\jshap\JS_Obsidian"

# Dedicated Obsidian folder for bidirectional My Views sync. Change here or in
# the app under ··· → Settings; OBSIDIAN_VIEWS_FOLDER overrides this value.
OBSIDIAN_VIEWS_FOLDER_DEFAULT = r"C:\Users\jshap\JS_Obsidian\Views"

# Interview practice may use INTERVIEW_MODEL / INTERVIEW_BASE_URL /
# INTERVIEW_API_KEY. Each falls back to the existing OpenRouter configuration.
