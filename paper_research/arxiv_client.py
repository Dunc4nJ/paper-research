"""arXiv API client using direct HTTP requests with proper timeouts.

Replaces the ``arxiv`` pip library which can hang indefinitely when
export.arxiv.org is slow (upstream pagination blocking issue).

Uses httpx with explicit timeouts against the arXiv Atom API directly.

Public API
----------
- ``search_arxiv(query, limit, sort_by, year_min)`` → ``list[Paper]``
- ``download_pdf(arxiv_id, dirpath)`` → ``Path | None``
- ``get_paper_by_id(arxiv_id)`` → ``Paper | None``
- ``search_arxiv_advanced(...)`` → ``list[Paper]``
"""

from __future__ import annotations

import datetime
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from paper_research.models import Author, Paper

logger = logging.getLogger(__name__)

_ARXIV_API = "https://export.arxiv.org/api/query"
_TIMEOUT = 15  # seconds
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# ---------------------------------------------------------------------------
# Circuit breaker (kept for extra safety)
# ---------------------------------------------------------------------------

_CB_THRESHOLD = 3
_CB_INITIAL_COOLDOWN = 180
_CB_MAX_COOLDOWN = 600

_CB_CLOSED = "closed"
_CB_OPEN = "open"
_CB_HALF_OPEN = "half_open"

_cb_state: str = _CB_CLOSED
_cb_consecutive_fails: int = 0
_cb_cooldown_sec: float = _CB_INITIAL_COOLDOWN
_cb_open_since: float = 0.0
_cb_trip_count: int = 0
_cb_lock = threading.Lock()


def _reset_circuit_breaker() -> None:
    global _cb_state, _cb_consecutive_fails, _cb_cooldown_sec
    global _cb_open_since, _cb_trip_count
    with _cb_lock:
        _cb_state = _CB_CLOSED
        _cb_consecutive_fails = 0
        _cb_cooldown_sec = _CB_INITIAL_COOLDOWN
        _cb_open_since = 0.0
        _cb_trip_count = 0


def _cb_should_allow() -> bool:
    global _cb_state
    with _cb_lock:
        if _cb_state == _CB_CLOSED:
            return True
        if _cb_state == _CB_OPEN:
            elapsed = time.monotonic() - _cb_open_since
            if elapsed >= _cb_cooldown_sec:
                _cb_state = _CB_HALF_OPEN
                logger.info("arXiv circuit breaker → HALF_OPEN (%.0fs cooldown elapsed)", elapsed)
                return True
            return False
        return True  # HALF_OPEN


def _cb_on_success() -> None:
    global _cb_state, _cb_consecutive_fails, _cb_cooldown_sec
    with _cb_lock:
        _cb_consecutive_fails = 0
        if _cb_state != _CB_CLOSED:
            logger.info("arXiv circuit breaker → CLOSED (request succeeded)")
            _cb_state = _CB_CLOSED
            _cb_cooldown_sec = _CB_INITIAL_COOLDOWN


def _cb_on_failure() -> bool:
    global _cb_state, _cb_consecutive_fails, _cb_cooldown_sec
    global _cb_open_since, _cb_trip_count
    with _cb_lock:
        _cb_consecutive_fails += 1
        if _cb_state == _CB_HALF_OPEN or _cb_consecutive_fails >= _CB_THRESHOLD:
            if _cb_state == _CB_HALF_OPEN:
                _cb_cooldown_sec = min(_cb_cooldown_sec * 2, _CB_MAX_COOLDOWN)
            _cb_state = _CB_OPEN
            _cb_open_since = time.monotonic()
            _cb_trip_count += 1
            logger.warning(
                "arXiv circuit breaker TRIPPED (trip #%d, cooldown %.0fs)",
                _cb_trip_count, _cb_cooldown_sec,
            )
            return True
        return False


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------


def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _parse_entry(entry: ET.Element) -> Paper:
    """Parse a single Atom <entry> into a Paper."""
    title = " ".join(_text(entry.find("atom:title", _NS)).split())
    abstract = " ".join(_text(entry.find("atom:summary", _NS)).split())

    entry_id = _text(entry.find("atom:id", _NS))
    arxiv_id = ""
    if entry_id:
        m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?$", entry_id)
        if m:
            arxiv_id = m.group(1)

    authors = tuple(
        Author(name=_text(a.find("atom:name", _NS)))
        for a in entry.findall("atom:author", _NS)
    )

    published = _text(entry.find("atom:published", _NS))
    year = int(published[:4]) if published and len(published) >= 4 else 0

    # DOI
    doi_el = entry.find("arxiv:doi", _NS)
    doi = _text(doi_el)

    # Primary category
    pcat = entry.find("arxiv:primary_category", _NS)
    venue = pcat.get("term", "") if pcat is not None else ""

    # PDF link
    pdf_url = ""
    for link in entry.findall("atom:link", _NS):
        if link.get("title") == "pdf":
            pdf_url = link.get("href", "")
            break

    url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else entry_id

    return Paper(
        paper_id=f"arxiv-{arxiv_id}" if arxiv_id else f"arxiv-{entry_id}",
        title=title,
        authors=authors,
        year=year,
        abstract=abstract,
        venue=venue,
        citation_count=0,
        doi=doi,
        arxiv_id=arxiv_id,
        url=url,
        source="arxiv",
    )


def _query_api(params: dict[str, Any]) -> list[ET.Element]:
    """Hit the arXiv API and return entry elements."""
    resp = httpx.get(
        _ARXIV_API,
        params=params,
        timeout=_TIMEOUT,
        follow_redirects=True,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    return root.findall("atom:entry", _NS)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def search_arxiv(
    query: str,
    *,
    limit: int = 50,
    sort_by: str = "relevance",
    year_min: int = 0,
    date_from: "datetime.date | None" = None,
    date_to: "datetime.date | None" = None,
) -> list[Paper]:
    """Search arXiv for papers matching *query*.

    Parameters
    ----------
    query:
        Free-text search query. Supports arXiv field syntax
        (e.g., ``ti:transformer``, ``au:vaswani``, ``cat:cs.LG``).
    limit:
        Maximum number of results (up to 300).
    sort_by:
        Sort criterion: "relevance", "submitted_date", or "last_updated".
    year_min:
        If > 0, only return papers published in this year or later.

    Returns
    -------
    list[Paper]
        Parsed papers. Empty list on failure.
    """
    if not _cb_should_allow():
        logger.info("[rate-limit] arXiv circuit breaker OPEN — skipping")
        return []

    limit = min(limit, 300)

    sort_map = {
        "relevance": "relevance",
        "submitted_date": "submittedDate",
        "last_updated": "lastUpdatedDate",
    }
    sort_val = sort_map.get(sort_by, "relevance")

    # Build search query — wrap multi-word queries for the API
    # Use ti+abs fields for better relevance than 'all:'
    search_query = query
    if not any(prefix in query for prefix in ("ti:", "au:", "abs:", "cat:", "all:")):
        # Quote the query as a phrase search across title+abstract
        words = query.strip().split()
        if len(words) > 1:
            search_query = f'ti:"{query}" OR abs:"{query}"'
        else:
            search_query = f"all:{query}"

    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": limit,
        "sortBy": sort_val,
        "sortOrder": "descending",
    }

    papers: list[Paper] = []
    try:
        entries = _query_api(params)
        for entry in entries:
            paper = _parse_entry(entry)
            if not paper.title:
                continue
            if year_min > 0 and paper.year < year_min:
                continue
            if date_from and paper.year < date_from.year:
                continue
            if date_to and paper.year > date_to.year:
                continue
            papers.append(paper)
        _cb_on_success()
        logger.info("arXiv: found %d papers for %r", len(papers), query)
    except httpx.TimeoutException:
        logger.warning("arXiv request timed out for %r", query)
        _cb_on_failure()
    except Exception as exc:
        logger.warning("arXiv search failed: %s", exc)
        _cb_on_failure()

    return papers


def get_paper_by_id(arxiv_id: str) -> Paper | None:
    """Fetch a single paper by arXiv ID (e.g., '2301.00001')."""
    try:
        entries = _query_api({"id_list": arxiv_id, "max_results": 1})
        for entry in entries:
            p = _parse_entry(entry)
            if p.title:
                return p
    except Exception as exc:
        logger.warning("arXiv ID lookup failed for %s: %s", arxiv_id, exc)
    return None


def download_pdf(
    arxiv_id: str,
    dirpath: str | Path = ".",
    filename: str = "",
) -> Path | None:
    """Download PDF for a given arXiv ID."""
    try:
        url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        dirpath = Path(dirpath)
        dirpath.mkdir(parents=True, exist_ok=True)
        fname = filename or f"{arxiv_id.replace('/', '_')}.pdf"
        with httpx.stream("GET", url, timeout=30, follow_redirects=True) as resp:
            resp.raise_for_status()
            pdf_path = dirpath / fname
            with open(pdf_path, "wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        logger.info("Downloaded arXiv PDF: %s → %s", arxiv_id, pdf_path)
        return pdf_path
    except Exception as exc:
        logger.warning("PDF download failed for %s: %s", arxiv_id, exc)
    return None


def search_arxiv_advanced(
    *,
    title: str = "",
    author: str = "",
    abstract: str = "",
    category: str = "",
    limit: int = 50,
    year_min: int = 0,
) -> list[Paper]:
    """Advanced arXiv search using field-specific queries."""
    parts = []
    if title:
        parts.append(f"ti:{title}")
    if author:
        parts.append(f"au:{author}")
    if abstract:
        parts.append(f"abs:{abstract}")
    if category:
        parts.append(f"cat:{category}")

    if not parts:
        return []

    query = " AND ".join(parts)
    return search_arxiv(query, limit=limit, year_min=year_min)
