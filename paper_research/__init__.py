"""Standalone literature search package.

Search arXiv, OpenAlex, and Semantic Scholar with deduplication.
"""

from paper_research.models import Author, Paper
from paper_research.search import search_papers

__all__ = ["Author", "Paper", "search_papers"]
