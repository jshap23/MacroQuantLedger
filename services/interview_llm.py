"""Compact, provider-neutral interview chat interface."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol

import config as app_config
from storage import user_settings


FAILURE_TAGS = {
    "ANSWER_FIRST", "RAMBLE", "DID_NOT_ANSWER", "KNOWLEDGE_GAP",
    "EVIDENCE_GAP", "WEAK_MECHANISM", "UNSUPPORTED_ASSERTION",
    "FAILED_PUSHBACK", "IMPLEMENTATION_GAP", "TOO_HEDGED", "OVERCONFIDENT",
}

INTERVIEW_MODELS_OPENROUTER = [
    "deepseek/deepseek-v4-flash-0731",
    "openai/gpt-5.6-luna",
    "deepseek/deepseek-v4-pro-0813",
    "tencent/hy3",
    "xiaomi/mimo-v2.5",
    "moonshotai/kimi-k3",
]

INTERVIEW_MODELS_OPENCODE_GO = [
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "kimi-k2.6",
    "kimi-k3",
    "glm-5.1",
    "glm-5.2",
    "glm-5.3",
    "hy3",
    "mimo-v2.5",
]


@dataclass
class CompletionOptions:
    model: str
    max_tokens: int = 500
    temperature: float = 0.4
    json_mode: bool = True


class LLMProvider(Protocol):
    def complete(self, messages: list[dict[str, str]], options: CompletionOptions) -> str: ...


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _provider() -> str:
    return user_settings.llm_provider()


def _provider_label() -> str:
    return "OpenRouter" if _provider() == app_config.LLM_PROVIDER_OPENROUTER else "OpenCode Go"


def _interview_models() -> list[str]:
    if _provider() == app_config.LLM_PROVIDER_OPENCODE_GO:
        return INTERVIEW_MODELS_OPENCODE_GO
    return INTERVIEW_MODELS_OPENROUTER


def interview_model(selected: str = "") -> str:
    if selected:
        return selected.strip()
    env_interview = _env("INTERVIEW_MODEL")
    if env_interview:
        return env_interview
    if _provider() == app_config.LLM_PROVIDER_OPENROUTER:
        env_or = _env("OPENROUTER_MODEL")
        if env_or:
            return env_or
    return user_settings.llm_model(_provider()) or _interview_models()[0]


def selectable_models() -> list[str]:
    """Return requested choices plus any environment-configured custom default."""
    configured = interview_model()
    return list(dict.fromkeys([configured, *_interview_models()]))


def available() -> bool:
    return bool(user_settings.llm_api_key(_provider()))


class OpenAICompatibleProvider:
    """Works with OpenRouter, OpenCode Go, or any OpenAI-compatible endpoint."""

    def __init__(self) -> None:
        from openai import OpenAI

        provider = _provider()
        api_key = user_settings.llm_api_key(provider)
        base_url = user_settings.llm_base_url(provider)
        headers = {"X-Title": _env("OPENROUTER_APP_NAME") or "MacroQuantLedger Interview Practice"}
        if provider == app_config.LLM_PROVIDER_OPENROUTER:
            referer = _env("OPENROUTER_HTTP_REFERER")
            if referer:
                headers["HTTP-Referer"] = referer
        self.client = OpenAI(api_key=api_key, base_url=base_url, default_headers=headers)

    def complete(self, messages: list[dict[str, str]], options: CompletionOptions) -> str:
        kwargs = {
            "model": options.model,
            "messages": messages,
            "max_tokens": options.max_tokens,
            "temperature": options.temperature,
        }
        if options.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            # Retry only when the compatibility problem is specifically JSON
            # response formatting; never duplicate auth/network/rate-limit calls.
            if "response_format" not in str(exc).lower() and "json_object" not in str(exc).lower():
                raise
            kwargs.pop("response_format", None)
            response = self.client.chat.completions.create(**kwargs)
        if not response.choices:
            raise RuntimeError("The interview model returned no response.")
        return (response.choices[0].message.content or "").strip()


def default_provider() -> LLMProvider:
    if not available():
        raise RuntimeError(
            f"Set the {_provider_label()} API key via environment variable or in Settings before starting practice."
        )
    return OpenAICompatibleProvider()


def parse_json_response(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return {"question": cleaned}
        value = json.loads(match.group(0))
    return value if isinstance(value, dict) else {"question": cleaned}
