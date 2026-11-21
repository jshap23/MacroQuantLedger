"""Advisory, web-grounded fact check for a Say it answer (and, later, a card).

Click-gated, cached on the session, and never scored: nothing here touches the
score, levels, trends, failure tags, or the synthesis. It always runs through
OpenRouter's ``openrouter:web_search`` server tool with the stored OpenRouter
key, even when interview chat runs on another provider.

Statuses are citation-gated. The model may only call a claim current, outdated,
or wrong if the search actually cited the source it names; anything else is
downgraded to unverifiable, and a figure with no cited source is dropped rather
than shown.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit

import config as app_config
from models.interview import (
    FactCheck,
    FactCheckClaim,
    InterviewAnswer,
    InterviewSession,
)
from services.interview_llm import (
    InterviewOutputError,
    InterviewProviderError,
    parse_json_response,
)
from storage import user_settings
from storage.interview_store import get_session, update_session

MAX_CLAIMS = 6
MAX_CARD_FACTS = 20
ANSWER_CHAR_LIMIT = 4000

_CITED_STATUSES = {"current", "outdated", "wrong"}
_STATUS_ALIASES = {
    "up to date": "current",
    "correct": "current",
    "accurate": "current",
    "confirmed": "current",
    "stale": "outdated",
    "superseded": "outdated",
    "revised": "outdated",
    "incorrect": "wrong",
    "false": "wrong",
    "inaccurate": "wrong",
    "contradicted": "wrong",
}

# (messages, model) -> (response text, URLs the search actually cited)
WebComplete = Callable[[list[dict], str], tuple[str, set[str]]]

_SYSTEM = (
    "You are a careful fact-checker for a macro and markets practice answer. "
    "Check only claims that can be verified: figures, dates, policy decisions, "
    "and events. Skip opinions, forecasts, and framing. Check at most "
    f"{MAX_CLAIMS} claims, and check claims the candidate made in their answer "
    "(origin 'answer') before dated facts from their notes (origin 'card'). Use "
    "the web search tool for the specific figure or event rather than the general "
    "topic. For every figure give the reference period it describes and the date "
    "it was released, and say if it has since been revised. Prefer primary "
    "sources: BLS, BEA, the Federal Reserve, the Treasury, FRED, and company "
    "filings. Mark a claim 'current', 'outdated', or 'wrong' only if you found a "
    "source for it, and put that page's URL in source_url. If you cannot find a "
    "source, mark it 'unverifiable'. If the answer was dictated, a number that "
    "could plausibly be misheard is 'unverifiable', never 'wrong'. Return JSON "
    "only, in the schema given."
)

_OUTPUT_SCHEMA = {
    "claims": [
        {
            "claim": "the claim, quoted or paraphrased in one sentence",
            "origin": "'answer' or 'card'",
            "status": "'current', 'outdated', 'wrong', or 'unverifiable'",
            "latest_value": "the up-to-date figure or fact, if you found one",
            "reference_period": "the period the figure describes, e.g. 'Oct 2026'",
            "released": "when that figure was published, e.g. '2026-11-13'",
            "source_url": "URL of the page you used",
            "source_title": "title of that page",
            "note": "one short sentence: what differs, or revisions",
        }
    ]
}


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def fact_check_model() -> str:
    configured = (os.environ.get("INTERVIEW_FACT_CHECK_MODEL") or "").strip()
    return configured or app_config.FACT_CHECK_MODEL_DEFAULT


def fact_check_available() -> bool:
    return bool(user_settings.llm_api_key(app_config.LLM_PROVIDER_OPENROUTER))


def _norm_url(url: str) -> str:
    """Host and path only, so scheme, ``www``, query, and trailing slash never matter."""
    parts = urlsplit((url or "").strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host + parts.path.rstrip("/") if host else ""


def _status(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", " ").replace("_", " ")
    text = _STATUS_ALIASES.get(text, text)
    return text if text in _CITED_STATUSES else "unverifiable"


def _text(value: object, limit: int) -> str:
    return str(value).strip()[:limit] if value is not None else ""


def validate_claims(data: object, cited_urls: set[str]) -> list[FactCheckClaim]:
    """Turn the model's JSON into claims, enforcing the citation gate.

    Raises ValueError when there is no ``claims`` list at all (an output
    failure). A claim keeps its source URL and figure only when that URL is among
    the URLs the search cited.
    """
    raw = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise ValueError("The fact-check response had no claims list.")
    cited = {_norm_url(url) for url in cited_urls} - {""}
    claims: list[FactCheckClaim] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        claim = _text(item.get("claim"), 300)
        if not claim:
            continue
        url = _text(item.get("source_url"), 500)
        sourced = (
            url.lower().startswith(("http://", "https://")) and _norm_url(url) in cited
        )
        status = _status(item.get("status"))
        note = _text(item.get("note"), 300)
        values = {
            "latest_value": _text(item.get("latest_value"), 200),
            "reference_period": _text(item.get("reference_period"), 100),
            "released": _text(item.get("released"), 100),
            "source_title": _text(item.get("source_title"), 200),
        }
        if not sourced:
            if status in _CITED_STATUSES:
                status = "unverifiable"
                note = f"{note} No cited source.".strip()
            url = ""
            values = {key: "" for key in values}
        origin = (
            "card"
            if str(item.get("origin") or "").strip().lower() == "card"
            else "answer"
        )
        claims.append(
            FactCheckClaim(
                claim=claim,
                origin=origin,
                status=status,
                source_url=url,
                note=note,
                **values,
            )
        )
    claims.sort(key=lambda entry: entry.origin == "card")
    return claims[:MAX_CLAIMS]


def _field(obj: object, name: str) -> object:
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _citation_urls(message: object) -> set[str]:
    """URLs from ``url_citation`` annotations, which the SDK may leave as extras."""
    annotations = getattr(message, "annotations", None)
    if not annotations:
        annotations = (getattr(message, "model_extra", None) or {}).get("annotations")
    urls: set[str] = set()
    for annotation in annotations or []:
        if _field(annotation, "type") != "url_citation":
            continue
        url = _field(_field(annotation, "url_citation"), "url")
        if url:
            urls.add(str(url))
    return urls


def _web_complete(messages: list[dict], model: str) -> tuple[str, set[str]]:
    """One OpenRouter call with the web search server tool; returns text and cited URLs."""
    from openai import OpenAI

    provider = app_config.LLM_PROVIDER_OPENROUTER
    api_key = user_settings.llm_api_key(provider)
    if not api_key:
        raise InterviewProviderError(
            "Set an OpenRouter API key in Settings to check facts."
        )
    headers = {
        "X-Title": (
            os.environ.get("OPENROUTER_APP_NAME")
            or "MacroQuantLedger Interview Practice"
        ).strip()
    }
    referer = (os.environ.get("OPENROUTER_HTTP_REFERER") or "").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    client = OpenAI(
        api_key=api_key,
        base_url=user_settings.llm_base_url(provider),
        default_headers=headers,
        timeout=app_config.FACT_CHECK_TIMEOUT_SECONDS,
    )
    # temperature is deliberately omitted: several search-capable models do not
    # accept it. The tool goes through extra_body so the SDK forwards it verbatim.
    # Reasoning is minimised rather than disabled: some models (GLM 5.3) refuse to
    # disable it, and with a server tool in the request OpenRouter reports that as
    # a generic 400 that never mentions reasoning, so it cannot be detected from
    # the message.
    extra_body: dict = {
        "reasoning": {"effort": "minimal"},
        "tools": [
            {
                "type": "openrouter:web_search",
                "parameters": {
                    "max_results": app_config.FACT_CHECK_MAX_RESULTS,
                    "max_uses": app_config.FACT_CHECK_MAX_SEARCHES,
                },
            }
        ],
    }
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": app_config.FACT_CHECK_MAX_TOKENS,
        "extra_body": extra_body,
    }
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as exc:
        # Only a 400 is retried, once and without the reasoning hint; an auth,
        # rate-limit, or network failure must never be sent twice.
        if getattr(exc, "status_code", None) != 400 or "reasoning" not in extra_body:
            raise InterviewProviderError(f"The fact-check call failed: {exc}") from exc
        extra_body.pop("reasoning")
        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as retry_exc:
            raise InterviewProviderError(
                f"The fact-check call failed: {retry_exc}"
            ) from retry_exc
    if not response.choices:
        raise InterviewProviderError("The fact-check model returned no response.")
    message = response.choices[0].message
    content = (message.content or "").strip()
    if not content:
        raise InterviewOutputError("The fact-check model returned empty content.")
    return content, _citation_urls(message)


def check_claims(
    *,
    topic: str,
    answer_text: str,
    card_facts: list[dict],
    voice: bool,
    model: str,
    today: str,
    web_complete: WebComplete | None = None,
) -> FactCheck:
    """Check an answer's claims and/or a card's dated facts. Never raises on model failure."""
    answer_text = (answer_text or "").strip()
    if not answer_text and not card_facts:
        return FactCheck(status="ok", model=model)
    prompt = {
        "today": today,
        "topic": topic,
        "candidate_answer": answer_text[:ANSWER_CHAR_LIMIT],
        "answer_was_dictated": voice,
        "card_facts": card_facts,
        "output_schema": _OUTPUT_SCHEMA,
    }
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
    ]
    try:
        content, cited = (web_complete or _web_complete)(messages, model)
        claims = validate_claims(parse_json_response(content), cited)
    except InterviewProviderError:
        return FactCheck(status="missing", error="provider", model=model)
    except (InterviewOutputError, ValueError):
        return FactCheck(status="missing", error="output", model=model)
    return FactCheck(
        status="ok",
        error="" if cited else "no_citations",
        model=model,
        claims=claims,
    )


def _card_facts(view_context: str) -> list[dict]:
    """Dated facts from the stored View's JSON context, in point order."""
    try:
        data = json.loads(view_context)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    facts: list[dict] = []
    for point in data.get("ordered_points") or []:
        if not isinstance(point, dict):
            continue
        for fact in point.get("facts") or []:
            if isinstance(fact, dict) and str(fact.get("text") or "").strip():
                facts.append(
                    {
                        "point": point.get("title") or "",
                        "fact": fact["text"],
                        "as_of": fact.get("as_of") or "",
                        "source": fact.get("source") or "",
                    }
                )
    return facts[:MAX_CARD_FACTS]


def _first_answer(session: InterviewSession) -> InterviewAnswer | None:
    for question in session.questions:
        if question.answers:
            return question.answers[0]
    return None


def fact_check_session(
    session_id: str, web_complete: WebComplete | None = None
) -> InterviewSession:
    """Fact-check a completed Say it rep and cache the result on the session.

    A cached usable result is returned without another call. A failure is
    recorded as ``status="missing"`` with the error kind and never raises; a
    result with no cited sources is stored but not treated as cached, so the
    user can retry it with another model. Saved through ``update_session`` so a
    summary or reference answer written meanwhile is not overwritten.
    """
    session = get_session(session_id)
    if session is None or session.status != "completed":
        raise RuntimeError("Facts can only be checked after a completed rep.")
    cached = session.fact_check
    if cached is not None and cached.status == "ok" and not cached.error:
        return session
    answer = _first_answer(session)
    if answer is None:
        raise RuntimeError("This rep has no answer to check.")
    result = check_claims(
        topic=session.topic,
        answer_text=answer.text,
        card_facts=_card_facts(session.view_context),
        voice=answer.voice,
        model=fact_check_model(),
        today=_today(),
        web_complete=web_complete,
    )

    def apply(fresh: InterviewSession) -> None:
        fresh.fact_check = result

    return update_session(session_id, apply) or session
