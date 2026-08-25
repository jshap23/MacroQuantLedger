"""Research paper feed aggregator.

Merges Fed research feeds (FEDS, FEDS Notes, IFDP), NBER working papers,
ECB publications, BIS working papers, NY Fed's Liberty Street Economics,
and a deep arXiv q-fin pull (API with RSS fallback) into one reverse-
chronological list persisted to data/research_feed.json.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from storage.fed_client import get_feed_items

logger = logging.getLogger(__name__)

ARXIV_API_URL = (
    "https://export.arxiv.org/api/query?search_query=cat:q-fin.*"
    "&sortBy=submittedDate&sortOrder=descending&max_results="
)
ARXIV_MAX_RESULTS = 200
ARXIV_RSS_FALLBACK = "https://rss.arxiv.org/rss/q-fin"

SOURCES: list[tuple[str, str]] = [
    ("FEDS", "https://www.federalreserve.gov/feeds/feds.xml"),
    ("FEDS Notes", "https://www.federalreserve.gov/feeds/feds_notes.xml"),
    ("IFDP", "https://www.federalreserve.gov/feeds/ifdp.xml"),
    ("NBER", "https://www.nber.org/rss/new.xml"),
    ("ECB", "https://www.ecb.europa.eu/rss/pub.html"),
    ("BIS WP", "https://www.bis.org/doclist/bis_fsi_publs.rss"),
    ("Liberty St", "https://libertystreeteconomics.newyorkfed.org/feed/"),
    ("SF Fed", "https://www.frbsf.org/feed/"),
    ("arXiv q-fin", ARXIV_RSS_FALLBACK),
]
_ARXIV_LABEL = "arXiv q-fin"
_SOURCE_FETCH_PAUSE_S = 1.5

MAX_ITEMS = 800
MAX_READ_IDS = 1600

STORE_FILE = Path(__file__).resolve().parent.parent / "data" / "research_feed.json"
_LOCK = threading.RLock()


class FeedItem(BaseModel):
    id: str
    source: str
    title: str
    authors: str = ""
    summary: str = ""
    url: str
    published: str = ""   # YYYY-MM-DD


class PaperSummary(BaseModel):
    text: str
    model: str = ""       # model slug that generated it
    endpoint: str = ""    # host of the API base URL
    created_at: str = ""  # YYYY-MM-DD HH:MM


class ResearchStore(BaseModel):
    items: list[FeedItem] = Field(default_factory=list)
    read_ids: list[str] = Field(default_factory=list)
    queued_ids: list[str] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)
    summaries: dict[str, PaperSummary] = Field(default_factory=dict)
    last_fetch: str = ""


def _item_id(link: str) -> str:
    return hashlib.sha1(_canon_link(link).encode("utf-8")).hexdigest()[:16]


def _canon_link(url: str) -> str:
    url = (url or "").strip().split("#", 1)[0]
    url = re.sub(r"(arxiv\.org/abs/.+?)v\d+$", r"\1", url)
    return url


def _fetch_arxiv() -> list[dict]:
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            return get_feed_items(f"{ARXIV_API_URL}{ARXIV_MAX_RESULTS}")
        except Exception as exc:
            last_exc = exc
            if "429" not in str(exc):
                break
            time.sleep(min(45, 15 * (attempt + 1)))
            logger.warning("arXiv API rate-limited (attempt %d)", attempt + 1)
    logger.warning("arXiv API failed (%s) — falling back to RSS", last_exc)
    return get_feed_items(ARXIV_RSS_FALLBACK)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def load_store() -> ResearchStore:
    with _LOCK:
        try:
            return ResearchStore.model_validate_json(STORE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return ResearchStore()


def save_store(store: ResearchStore) -> None:
    with _LOCK:
        store.items = store.items[:MAX_ITEMS]
        store.read_ids = store.read_ids[:MAX_READ_IDS]
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = STORE_FILE.with_suffix(".tmp")
        temp.write_text(store.model_dump_json(indent=2), encoding="utf-8")
        temp.replace(STORE_FILE)


def refresh_feeds() -> tuple[ResearchStore, int, str]:
    """Fetch all sources and merge into the store.

    Returns (store, newly_added, note). Sources that fail are skipped so one
    dead feed never blanks the whole list.
    """
    with _LOCK:
        store = load_store()
        known = {it.id for it in store.items}
        canon_known = {_canon_link(it.url) for it in store.items}
        merged: dict[str, FeedItem] = {it.id: it for it in store.items}
        errors: list[str] = []

        def _merge(label: str, raw_items: list[dict]) -> None:
            for raw in raw_items:
                link = _canon_link(raw["link"])
                if not link:
                    continue
                item_id = hashlib.sha1(link.encode("utf-8")).hexdigest()[:16]
                if item_id in known or link in canon_known:
                    continue
                merged[item_id] = FeedItem(
                    id=item_id,
                    source=label,
                    title=_clean(raw["title"]),
                    authors=_clean(raw.get("author") or ""),
                    summary=_clean(raw.get("description") or "")[:1200],
                    url=link,
                    published=raw["date"],
                )

        for idx, (label, url) in enumerate(SOURCES):
            try:
                if idx:
                    time.sleep(_SOURCE_FETCH_PAUSE_S)
                if label == _ARXIV_LABEL:
                    _merge(label, _fetch_arxiv())
                else:
                    _merge(label, get_feed_items(url))
            except Exception as exc:
                logger.warning("feed %s failed: %s", label, exc)
                errors.append(label)

        items = sorted(
            merged.values(),
            key=lambda it: it.published or "0000-00-00",
            reverse=True,
        )[:MAX_ITEMS]

        newly_added = sum(1 for it in items if it.id not in known)
        store.items = items
        valid_ids = {it.id for it in items}
        store.read_ids = [rid for rid in store.read_ids if rid in valid_ids]
        store.queued_ids = [qid for qid in store.queued_ids if qid in valid_ids]
        if store.notes:
            store.notes = {k: v for k, v in store.notes.items() if k in valid_ids}
        if store.summaries:
            store.summaries = {k: v for k, v in store.summaries.items() if k in valid_ids}
        store.last_fetch = datetime.now().strftime("%Y-%m-%d %H:%M")
        save_store(store)

        failed = f" · {len(errors)} feed(s) unreachable" if errors else ""
        note = f"{len(items)} papers · +{newly_added} new · updated {store.last_fetch}{failed}"
        return store, newly_added, note


def unread_count(store: ResearchStore) -> int:
    read = set(store.read_ids)
    return sum(1 for it in store.items if it.id not in read)


def mark_read(item_id: str) -> None:
    with _LOCK:
        store = load_store()
        if item_id not in store.read_ids:
            store.read_ids.insert(0, item_id)
            save_store(store)


def mark_unread(item_id: str) -> None:
    with _LOCK:
        store = load_store()
        if item_id in store.read_ids:
            store.read_ids.remove(item_id)
            save_store(store)


def mark_all_read() -> None:
    with _LOCK:
        store = load_store()
        store.read_ids = [it.id for it in store.items][:MAX_READ_IDS]
        save_store(store)


def set_queued(item_id: str, queued: bool) -> None:
    with _LOCK:
        store = load_store()
        changed = False
        if queued and item_id not in store.queued_ids:
            store.queued_ids.insert(0, item_id)
            changed = True
        elif not queued and item_id in store.queued_ids:
            store.queued_ids.remove(item_id)
            changed = True
        if changed:
            save_store(store)


def save_note(item_id: str, note: str) -> None:
    with _LOCK:
        store = load_store()
        cleaned = (note or "").strip()
        if cleaned:
            store.notes[item_id] = cleaned
        else:
            store.notes.pop(item_id, None)
        save_store(store)


def save_summary(item_id: str, summary: PaperSummary) -> None:
    with _LOCK:
        store = load_store()
        store.summaries[item_id] = summary
        save_store(store)
