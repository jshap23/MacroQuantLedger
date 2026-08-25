"""Validate LLM provider settings round-trip without network calls."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import config as app_config
import storage.user_settings as us


def main() -> int:
    original_file = us.SETTINGS_FILE
    with tempfile.TemporaryDirectory() as td:
        us.SETTINGS_FILE = Path(td) / "user_settings.json"
        # Clear env vars that could interfere
        for key in [
            "MQLEDGER_LLM_PROVIDER",
            "OPENCODE_API_KEY",
            "OPENCODE_BASE_URL",
            "OPENCODE_MODEL",
            "OPENCODE_POLISH_MODEL",
            "OPENCODE_RESEARCH_MODEL",
            "OPENROUTER_API_KEY",
            "OPENROUTER_BASE_URL",
            "OPENROUTER_MODEL",
            "OPENROUTER_POLISH_MODEL",
            "OPENROUTER_RESEARCH_MODEL",
            "INTERVIEW_MODEL",
        ]:
            os.environ.pop(key, None)

        # Default provider is OpenRouter
        assert us.llm_provider() == app_config.LLM_PROVIDER_DEFAULT, "default provider should be OpenRouter"
        assert us.llm_api_key() == "", "default API key should be empty"
        assert us.llm_model() == app_config.OPENROUTER_MODEL_DEFAULT, "default model should match OpenRouter default"

        # Switch to OpenCode Go
        us.save_llm_provider(app_config.LLM_PROVIDER_OPENCODE_GO)
        assert us.llm_provider() == app_config.LLM_PROVIDER_OPENCODE_GO, "provider should persist"
        assert us.llm_base_url() == app_config.OPENCODE_GO_BASE_URL_DEFAULT, "OpenCode Go base URL should default"

        us.save_llm_api_key(app_config.LLM_PROVIDER_OPENCODE_GO, "sk-opencode-test")
        assert us.llm_api_key() == "sk-opencode-test", "OpenCode Go API key should persist"

        us.save_llm_model(app_config.LLM_PROVIDER_OPENCODE_GO, "deepseek-v4-pro")
        assert us.llm_model() == "deepseek-v4-pro", "OpenCode Go model should persist"

        # Env override for model
        os.environ["OPENCODE_MODEL"] = "kimi-k2.6"
        assert us.llm_model() == "kimi-k2.6", "OPENCODE_MODEL env var should override"

        # Env override for API key
        os.environ["OPENCODE_API_KEY"] = "env-key"
        assert us.llm_api_key() == "env-key", "OPENCODE_API_KEY env var should override stored key"

        # Switch back to OpenRouter
        os.environ["OPENROUTER_API_KEY"] = "or-env-key"
        us.save_llm_provider(app_config.LLM_PROVIDER_OPENROUTER)
        assert us.llm_provider() == app_config.LLM_PROVIDER_OPENROUTER, "provider should switch back"
        assert us.llm_api_key() == "or-env-key", "OPENROUTER_API_KEY env var should be used"
        assert us.llm_base_url() == app_config.OPENROUTER_BASE_URL_DEFAULT, "OpenRouter base URL should default"

        # Stored values survive a reload
        reloaded = us.load_user_settings()
        assert reloaded.get("llm_provider") == app_config.LLM_PROVIDER_OPENROUTER, "provider should survive reload"
        assert reloaded.get("openrouter_api_key") is None, "stored OpenRouter key should remain empty"
        assert reloaded.get("opencode_go_api_key") == "sk-opencode-test", "stored OpenCode Go key should survive"

        # MQLEDGER_LLM_PROVIDER env var wins
        os.environ["MQLEDGER_LLM_PROVIDER"] = app_config.LLM_PROVIDER_OPENCODE_GO
        assert us.llm_provider() == app_config.LLM_PROVIDER_OPENCODE_GO, "MQLEDGER_LLM_PROVIDER env var should win"

    us.SETTINGS_FILE = original_file
    print("LLM provider settings round-trip: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
