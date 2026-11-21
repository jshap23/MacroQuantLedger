"""Non-secret defaults for MacroQuant Ledger."""

# OpenRouter — OpenAI-compatible Chat Completions (https://openrouter.ai/docs)
OPENROUTER_BASE_URL_DEFAULT = "https://openrouter.ai/api/v1"
# Default model slug on OpenRouter; override with OPENROUTER_MODEL or per-task env vars
OPENROUTER_MODEL_DEFAULT = "deepseek/deepseek-v4.1-flash"

# Practice TTS uses OpenRouter's /audio/speech endpoint independently of the
# interview chat provider and model.
INTERVIEW_TTS_MODEL_DEFAULT = "google/gemini-3.1-flash-tts-preview"
INTERVIEW_TTS_MODELS = (
    INTERVIEW_TTS_MODEL_DEFAULT,
    "x-ai/grok-voice-tts-1.0",
    "deepgram/flux-tts:free",
)

# OpenCode Go — OpenAI-compatible subscription endpoint (https://opencode.ai/docs/go)
OPENCODE_GO_BASE_URL_DEFAULT = "https://opencode.ai/zen/go/v1"
# Default model ID on OpenCode Go; override with OPENCODE_MODEL or per-task env vars
OPENCODE_GO_MODEL_DEFAULT = "deepseek-v4.1-flash"

# Default grader for scored View practice (Deliver / Discuss / Defend). This is
# only a default selection — the model stays user-selectable per session so a
# more thoughtful model can be chosen on demand. Bump these (or set
# INTERVIEW_GRADER_MODEL) when the preferred grader changes.
INTERVIEW_GRADER_MODEL_OPENROUTER_DEFAULT = "z-ai/glm-5.3"
INTERVIEW_GRADER_MODEL_OPENCODE_GO_DEFAULT = "glm-5.3"

# Practice "Check facts" is an advisory, click-gated web check of a Say it answer.
# It always goes through OpenRouter's openrouter:web_search server tool, using the
# stored OpenRouter key even when interview chat runs on OpenCode Go.
# INTERVIEW_FACT_CHECK_MODEL overrides the model.
FACT_CHECK_MODEL_DEFAULT = "z-ai/glm-5.3"
FACT_CHECK_MAX_RESULTS = 5
FACT_CHECK_MAX_SEARCHES = 4
# Reasoning models spend this budget before emitting content, and the model may take
# several tool turns, so it is larger than the other compact interview calls.
FACT_CHECK_MAX_TOKENS = 1500
FACT_CHECK_TIMEOUT_SECONDS = 90

# Provider selection constants
LLM_PROVIDER_OPENROUTER = "openrouter"
LLM_PROVIDER_OPENCODE_GO = "opencode_go"
# OpenRouter remains the out-of-the-box default; OpenCode Go is opt-in via Settings.
LLM_PROVIDER_DEFAULT = LLM_PROVIDER_OPENROUTER

OPENROUTER_MAX_TOKENS_POLISH = 600
OPENROUTER_TEMPERATURE = 0.5

# User-facing local defaults. Leave blank to configure in the app under
# ··· → Settings. OBSIDIAN_EXPORT_PATH overrides this value when set.
OBSIDIAN_EXPORT_PATH_DEFAULT = r"C:\Users\jshap\JS_Obsidian"

# Dedicated Obsidian folder for bidirectional My Views sync. Change here or in
# the app under ··· → Settings; OBSIDIAN_VIEWS_FOLDER overrides this value.
OBSIDIAN_VIEWS_FOLDER_DEFAULT = r"C:\Users\jshap\JS_Obsidian\Views"

# Read-only Obsidian folder of interview-facing model notes powering Quant
# Practice "My Models". QUANT_MODELS_FOLDER overrides this value.
OBSIDIAN_MODELS_FOLDER_DEFAULT = r"C:\Users\jshap\JS_Obsidian\Resources\Models"

# Interview practice may use INTERVIEW_MODEL / INTERVIEW_BASE_URL /
# INTERVIEW_API_KEY. Each falls back to the active provider configuration.
