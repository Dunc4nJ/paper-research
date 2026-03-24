"""HuggingFace Papers API client.

Provides search, metadata retrieval, markdown extraction, linked resource
discovery, and enrichment via the public HuggingFace API (no auth needed for reads).
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from dataclasses import replace
from pathlib import Path

import httpx

from paper_research.models import Author, Paper

logger = logging.getLogger(__name__)

_TIMEOUT = 15.0
_BASE = "https://huggingface.co"
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0


def _client() -> httpx.Client:
    return httpx.Client(timeout=_TIMEOUT, follow_redirects=True)


def _request_with_retry(
    client: httpx.Client,
    url: str,
    *,
    params: dict | None = None,
    max_retries: int = _MAX_RETRIES,
) -> httpx.Response:
    """GET with exponential backoff on 429/5xx."""
    for attempt in range(max_retries + 1):
        resp = client.get(url, params=params)
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == max_retries:
                resp.raise_for_status()
            wait = _RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
            logger.warning("HF API %s returned %d, retrying in %.1fs", url, resp.status_code, wait)
            time.sleep(wait)
            continue
        return resp
    return resp  # unreachable but satisfies type checker


# ------------------------------------------------------------------
# Search
# ------------------------------------------------------------------

def search_hf_papers(query: str, limit: int = 20) -> list[Paper]:
    """Hybrid semantic + full-text search on HuggingFace papers."""
    with _client() as c:
        resp = _request_with_retry(c, f"{_BASE}/api/papers/search", params={"q": query, "limit": limit})
        resp.raise_for_status()
        data = resp.json()

    papers: list[Paper] = []
    for item in data:
        # Search results may wrap paper data in a "paper" key
        paper_data = item.get("paper", item) if isinstance(item, dict) else item
        papers.append(_parse_paper(paper_data))
    return papers


# ------------------------------------------------------------------
# Paper markdown
# ------------------------------------------------------------------

def get_paper_markdown(arxiv_id: str) -> str | None:
    """Fetch full paper as markdown from HF. Returns None if 404."""
    with _client() as c:
        resp = _request_with_retry(c, f"{_BASE}/papers/{arxiv_id}.md")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text


# Alias for task spec
fetch_hf_markdown = get_paper_markdown


# ------------------------------------------------------------------
# Structured metadata
# ------------------------------------------------------------------

def get_paper_metadata(arxiv_id: str) -> dict | None:
    """Fetch structured metadata JSON for a paper."""
    with _client() as c:
        resp = _request_with_retry(c, f"{_BASE}/api/papers/{arxiv_id}")
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
                resp = _request_with_retry(c, f"{_BASE}/api/{kind}", params={"filter": f"arxiv:{arxiv_id}"})
                resp.raise_for_status()
                result[kind] = resp.json()
            except Exception:
                logger.warning("Failed to fetch %s for %s", kind, arxiv_id)
    return result


# ------------------------------------------------------------------
# Enrichment
# ------------------------------------------------------------------

def enrich_with_hf_metadata(papers: list[Paper]) -> list[Paper]:
    """Enrich papers that have arxiv_ids with HF metadata.

    Fetches upvotes, AI summary, github_repo, project_page, and
    counts of linked models/datasets/spaces.
    """
    enriched: list[Paper] = []
    with _client() as c:
        for paper in papers:
            if not paper.arxiv_id:
                enriched.append(paper)
                continue

            hf_meta: dict = {}
            try:
                resp = _request_with_retry(c, f"{_BASE}/api/papers/{paper.arxiv_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    hf_meta["upvotes"] = data.get("upvotes", 0)
                    hf_meta["ai_summary"] = data.get("aiSummary", "")
                    hf_meta["github_repo"] = data.get("githubRepo", "")
                    hf_meta["project_page"] = data.get("projectPage", "")
            except Exception:
                logger.warning("Failed to fetch HF metadata for %s", paper.arxiv_id)

            # Linked resources
            for kind in ("models", "datasets", "spaces"):
                try:
                    resp = _request_with_retry(
                        c, f"{_BASE}/api/{kind}", params={"filter": f"arxiv:{paper.arxiv_id}"}
                    )
                    if resp.status_code == 200:
                        hf_meta[f"{kind}_count"] = len(resp.json())
                    else:
                        hf_meta[f"{kind}_count"] = 0
                except Exception:
                    hf_meta[f"{kind}_count"] = 0

            enriched.append(replace(paper, hf_metadata=hf_meta) if hf_meta else paper)
            time.sleep(0.3)  # gentle rate limiting

    return enriched


# ------------------------------------------------------------------
# Daily papers
# ------------------------------------------------------------------

def get_daily_papers(date: str | None = None, sort: str = "trending", limit: int = 20) -> list[Paper]:
    """Fetch the Daily Papers feed."""
    params: dict[str, str | int] = {"sort": sort, "limit": limit}
    if date:
        params["date"] = date
    with _client() as c:
        resp = _request_with_retry(c, f"{_BASE}/api/daily_papers", params=params)
        resp.raise_for_status()
        data = resp.json()

    papers: list[Paper] = []
    for item in data:
        paper_data = item.get("paper", item)
        papers.append(_parse_paper(paper_data))
    return papers


# ------------------------------------------------------------------
# Image download
# ------------------------------------------------------------------

def download_paper_images(markdown_text: str, output_dir: str) -> list[str]:
    """Download images referenced in paper markdown to output_dir."""
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
    arxiv_id = item.get("id", "") or item.get("paperId", "") or ""
    title = item.get("title", "")
    summary = item.get("summary", "") or item.get("abstract", "")

    authors_raw = item.get("authors", [])
    authors: list[Author] = []
    for a in authors_raw:
        if isinstance(a, dict):
            name = a.get("name", "") or a.get("user", {}).get("fullname", "") if isinstance(a.get("user"), dict) else a.get("name", "")
            if name:
                authors.append(Author(name=str(name)))
        elif isinstance(a, str):
            authors.append(Author(name=a))

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
