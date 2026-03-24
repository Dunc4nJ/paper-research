"""HuggingFace Papers API client.

Provides search, metadata retrieval, markdown extraction, and linked resource
discovery via the public HuggingFace API (no auth needed for reads).
"""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path

import httpx

from paper_research.models import Author, Paper

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_BASE = "https://huggingface.co"


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True)


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------

def search_hf_papers(query: str, limit: int = 20) -> list[Paper]:
    """Hybrid semantic + full-text search on HuggingFace papers."""
    with _client() as c:
        resp = c.get(f"{_BASE}/api/papers/search", params={"q": query, "limit": limit})
        resp.raise_for_status()
        data = resp.json()

    papers: list[Paper] = []
    for item in data:
        papers.append(_parse_paper(item))
    return papers


# ------------------------------------------------------------------
# Paper markdown
# ------------------------------------------------------------------

def get_paper_markdown(arxiv_id: str) -> str | None:
    """Fetch full paper as markdown from HF. Returns None if 404."""
    with _client() as c:
        resp = c.get(f"{_BASE}/papers/{arxiv_id}.md")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text


# ------------------------------------------------------------------
# Structured metadata
# ------------------------------------------------------------------

def get_paper_metadata(arxiv_id: str) -> dict | None:
    """Fetch structured metadata JSON for a paper."""
    with _client() as c:
        resp = c.get(f"{_BASE}/api/papers/{arxiv_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


# ------------------------------------------------------------------
# Linked resources
# ------------------------------------------------------------------

def get_linked_resources(arxiv_id: str) -> dict:
    """Find models, datasets, and spaces linked to a paper."""
    result: dict[str, list] = {"models": [], "datasets": [], "spaces": []}
    with _client() as c:
        for kind in ("models", "datasets", "spaces"):
            try:
                resp = c.get(f"{_BASE}/api/{kind}", params={"filter": f"arxiv:{arxiv_id}"})
                resp.raise_for_status()
                result[kind] = resp.json()
            except Exception:
                logger.warning("Failed to fetch %s for %s", kind, arxiv_id)
    return result


# ------------------------------------------------------------------
# Daily papers
# ------------------------------------------------------------------

def get_daily_papers(date: str | None = None, sort: str = "trending", limit: int = 20) -> list[Paper]:
    """Fetch the Daily Papers feed."""
    params: dict[str, str | int] = {"sort": sort, "limit": limit}
    if date:
        params["date"] = date
    with _client() as c:
        resp = c.get(f"{_BASE}/api/daily_papers", params=params)
        resp.raise_for_status()
        data = resp.json()

    papers: list[Paper] = []
    for item in data:
        # daily_papers wraps paper data in a "paper" key
        paper_data = item.get("paper", item)
        papers.append(_parse_paper(paper_data))
    return papers


# ------------------------------------------------------------------
# Image download
# ------------------------------------------------------------------

def download_paper_images(markdown_text: str, output_dir: str) -> list[str]:
    """Download images referenced in paper markdown to output_dir."""
    # Match markdown images with arxiv.org HTML URLs or HF URLs
    pattern = r'!\[[^\]]*\]\((https?://[^\s\)]+)\)'
    urls = re.findall(pattern, markdown_text)

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    downloaded: list[str] = []

    with _client() as c:
        for url in urls:
            try:
                fname = url.split("/")[-1]
                if not fname or len(fname) > 200:
                    fname = f"image_{len(downloaded)}.png"
                dest = os.path.join(output_dir, fname)
                resp = c.get(url)
                resp.raise_for_status()
                with open(dest, "wb") as f:
                    f.write(resp.content)
                downloaded.append(dest)
            except Exception:
                logger.warning("Failed to download image: %s", url)

    return downloaded


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _parse_paper(item: dict) -> Paper:
    """Convert an HF API paper dict into our Paper model."""
    # Handle both search results and metadata responses
    arxiv_id = item.get("id", "") or item.get("paperId", "") or ""
    title = item.get("title", "")
    summary = item.get("summary", "") or item.get("abstract", "")

    # Authors can be list of dicts with "name" or "_id"/"user" etc.
    authors_raw = item.get("authors", [])
    authors: list[Author] = []
    for a in authors_raw:
        if isinstance(a, dict):
            name = a.get("name", "") or a.get("user", {}).get("fullname", "") if isinstance(a.get("user"), dict) else a.get("name", "")
            if name:
                authors.append(Author(name=str(name)))
        elif isinstance(a, str):
            authors.append(Author(name=a))

    # Extract year from publishedAt or id
    year = 0
    pub = item.get("publishedAt", "") or ""
    if pub and len(pub) >= 4:
        try:
            year = int(pub[:4])
        except ValueError:
            pass
    if not year and arxiv_id and "." in arxiv_id:
        prefix = arxiv_id.split(".")[0]
        if len(prefix) == 4:
            try:
                yy = int(prefix[:2])
                year = 2000 + yy if yy < 100 else yy
            except ValueError:
                pass

    return Paper(
        paper_id=f"hf:{arxiv_id}",
        title=title,
        authors=tuple(authors),
        year=year,
        abstract=summary,
        arxiv_id=arxiv_id,
        url=f"https://huggingface.co/papers/{arxiv_id}" if arxiv_id else "",
        source="hf",
    )
