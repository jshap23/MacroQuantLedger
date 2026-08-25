"""Federal Reserve communications client — FOMC statements, minutes, speeches.

Public sources only (federalreserve.gov RSS + HTML). Document bodies are cached
to data/fed_cache/ permanently once fetched; listings are re-fetched on demand.
"""
from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}
_TIMEOUT = 25

MONETARY_FEED = "https://www.federalreserve.gov/feeds/press_monetary.xml"
SPEECHES_FEED = "https://www.federalreserve.gov/feeds/speeches.xml"

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "fed_cache"


class FedDoc(BaseModel):
    id: str
    kind: str            # "Statement" | "Minutes" | "Speech"
    title: str
    speaker: str = ""
    venue: str = ""
    date: str = ""       # YYYY-MM-DD (release date)
    url: str             # press-release / speech page URL


def _slug(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _fetch_text(url: str) -> str:
    r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    # federalreserve.gov serves no charset header, so requests defaults to
    # ISO-8859-1 and mangles UTF-8 punctuation; re-detect before decoding.
    if (r.encoding or "").lower().replace("_", "-") in ("iso-8859-1", "windows-1252", ""):
        r.encoding = r.apparent_encoding or "utf-8"
    return r.text


# ── RSS parsing ───────────────────────────────────────────────────────────────

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child(item: ET.Element, name: str) -> str:
    for child in item:
        if _local(child.tag) == name:
            return unescape((child.text or "").strip())
    return ""


def _iso_date(raw: str) -> str:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return raw[:16]


def _entry_dict(elem: ET.Element) -> dict | None:
    """Normalize an RSS <item> or Atom <entry> into a feed-item dict."""
    if _local(elem.tag) == "item":
        link = _child(elem, "link")
        raw_date = (
            _child(elem, "pubdate") or _child(elem, "pubDate") or _child(elem, "date")
        )
        date_str = ""
        if raw_date:
            try:
                date_str = parsedate_to_datetime(raw_date).strftime("%Y-%m-%d")
            except (TypeError, ValueError):
                date_str = _iso_date(raw_date)
        description = unescape(_child(elem, "description"))
        author = _child(elem, "creator") or _child(elem, "author")
    elif _local(elem.tag) == "entry":
        link = ""
        for child in elem:
            if _local(child.tag) == "link":
                href = child.get("href") or child.get("to", "")
                rel = child.get("rel", "")
                if href and (rel in ("", "alternate") or not link):
                    link = href
        raw_date = _child(elem, "published") or _child(elem, "updated")
        date_str = _iso_date(raw_date) if raw_date else ""
        description = unescape(_child(elem, "summary")) or unescape(_child(elem, "content"))
        authors = [
            unescape(_child(c, "name")) for c in elem if _local(c.tag) == "author"
        ]
        author = ", ".join(a for a in authors if a)
    else:
        return None
    title = _child(elem, "title")
    if not link or not title:
        return None
    return {
        "title": re.sub(r"\s+", " ", title),
        "link": link.strip(),
        "date": date_str,
        "description": re.sub(r"\s+", " ", description),
        "author": re.sub(r"\s+", " ", author),
    }


def _parse_rss(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    out = []
    for item in root.iter():
        normalized = _entry_dict(item)
        if normalized:
            out.append(normalized)
    return out


def get_feed_items(url: str) -> list[dict]:
    """Fetch an RSS/Atom-ish feed and return normalized item dicts."""
    r = requests.get(url, headers=_UA, timeout=_TIMEOUT)
    r.raise_for_status()
    return _parse_rss(r.content)


# ── HTML article extraction (#article div, nesting-aware) ────────────────────

class _ArticleExtractor(HTMLParser):
    """Collect visible text inside the element with the given id."""

    def __init__(self, target_id: str = "article"):
        super().__init__(convert_charrefs=True)
        self.target_id = target_id
        self.depth = 0
        self.active = False
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        if not self.active and attrs_d.get("id") == self.target_id:
            self.active = True
            self.depth = 1
            return
        if not self.active:
            return
        if tag == "div":
            self.depth += 1
        if tag in ("p", "br", "li", "h1", "h2", "h3", "h4"):
            self.chunks.append("\n\n")
        elif tag in ("td", "th", "tr", "table"):
            self.chunks.append(" ")

    def handle_endtag(self, tag):
        if not self.active:
            return
        if tag == "div":
            self.depth -= 1
            if self.depth <= 0:
                self.active = False
        if tag in ("p", "h1", "h2", "h3", "h4"):
            self.chunks.append("\n\n")

    def handle_data(self, data):
        if self.active:
            self.chunks.append(data)


def extract_article(html: str) -> str:
    extractor = _ArticleExtractor("article")
    try:
        extractor.feed(html)
    except Exception as exc:
        logger.warning("article extraction failed: %s", exc)
        return ""
    text = "".join(extractor.chunks)
    text = unescape(text)
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in text.splitlines()]
    paragraphs, buf = [], []
    for line in lines:
        if line:
            buf.append(line)
        elif buf:
            paragraphs.append(" ".join(buf))
            buf = []
    if buf:
        paragraphs.append(" ".join(buf))
    return "\n\n".join(p for p in paragraphs if len(p) > 2)


# ── Document body cache (bodies never change once published) ─────────────────

def _cached_body(doc_id: str) -> str | None:
    path = CACHE_DIR / f"{doc_id}.txt"
    try:
        text = path.read_text(encoding="utf-8")
        return text or None
    except OSError:
        return None


def _store_body(doc_id: str, text: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{doc_id}.txt").write_text(text, encoding="utf-8")
    except OSError as exc:
        logger.warning("fed cache write failed: %s", exc)


def clear_cache() -> int:
    """Delete all cached document bodies. Returns number removed."""
    if not CACHE_DIR.exists():
        return 0
    removed = 0
    for f in CACHE_DIR.glob("*.txt"):
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


# ── Listings ──────────────────────────────────────────────────────────────────

_MINUTES_LINK_RE = re.compile(r'href="(/monetarypolicy/fomcminutes\d{8}\.htm)"')


def fomc_documents(limit: int = 14) -> tuple[list[FedDoc], str]:
    """Recent FOMC statements + minutes. Returns (docs, fetch_note)."""
    try:
        items = get_feed_items(MONETARY_FEED)
        note = "via federalreserve.gov"
    except Exception as exc:
        logger.warning("monetary feed failed: %s", exc)
        return [], f"Feed error: {type(exc).__name__}"

    docs: dict[str, FedDoc] = {}
    order: list[str] = []
    for it in items:
        title, link = it["title"], it["link"]
        low = title.lower()
        is_statement = "fomc statement" in low
        is_minutes = low.startswith("minutes of the federal open market committee")
        if not (is_statement or is_minutes):
            continue
        kind = "Minutes" if is_minutes else "Statement"
        doc_id = _slug(link)
        if doc_id in docs:
            continue
        docs[doc_id] = FedDoc(
            id=doc_id, kind=kind, title=title, date=it["date"], url=link,
        )
        order.append(doc_id)

    result = [docs[i] for i in order][:limit]
    return result, note


def recent_speeches(limit: int = 12) -> tuple[list[FedDoc], str]:
    """Recent Board governor speeches. Returns (docs, fetch_note)."""
    try:
        items = get_feed_items(SPEECHES_FEED)
        note = "via federalreserve.gov"
    except Exception as exc:
        logger.warning("speeches feed failed: %s", exc)
        return [], f"Feed error: {type(exc).__name__}"

    docs = []
    seen: set[str] = set()
    for it in items:
        link = it["link"]
        if link in seen:
            continue
        seen.add(link)
        title = it["title"]
        speaker = title.split(",", 1)[0].strip() if "," in title else ""
        main_title = title.split(",", 1)[1].strip() if "," in title else title
        docs.append(FedDoc(
            id=_slug(link), kind="Speech",
            title=re.sub(r"\s+", " ", main_title),
            speaker=speaker, venue=it["description"], date=it["date"], url=link,
        ))
        if len(docs) >= limit:
            break
    return docs, note


def document_body(doc: FedDoc) -> str:
    """Full readable text for a document (statement, minutes, or speech).

    Cached on disk after first fetch. Returns '' when no text version exists.
    """
    cached = _cached_body(doc.id)
    if cached is not None:
        return cached

    html = _fetch_text(doc.url)

    if doc.kind == "Minutes":
        # The press release announces the minutes; the full text lives on the
        # linked /monetarypolicy/fomcminutes<date>.htm page.
        match = _MINUTES_LINK_RE.search(html)
        if match:
            html = _fetch_text(f"https://www.federalreserve.gov{match.group(1)}")

    text = extract_article(html)
    if text:
        _store_body(doc.id, text)
    return text


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
