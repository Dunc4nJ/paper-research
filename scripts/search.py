#!/usr/bin/env python3
"""Search arXiv, OpenAlex, and Semantic Scholar. Output deduplicated JSON."""

import argparse
import datetime
import json
import re
import sys

sys.path.insert(0, "/data/projects/paper-research")

from paper_research.search import search_papers


def parse_date_expr(expr: str) -> datetime.date:
    """Parse a human-friendly date expression into a date.

    Supports:
    - Relative: "2 months", "30 days", "1 year", "6 weeks"
    - Absolute: "2025-01-01", "2025-06"
    """
    expr = expr.strip()

    # Relative: "N unit(s)"
    m = re.match(r"^(\d+)\s*(day|week|month|year)s?$", expr, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        today = datetime.date.today()
        if unit == "day":
            return today - datetime.timedelta(days=n)
        elif unit == "week":
            return today - datetime.timedelta(weeks=n)
        elif unit == "month":
            # Approximate: subtract n months
            month = today.month - n
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            day = min(today.day, 28)  # safe day
            return datetime.date(year, month, day)
        elif unit == "year":
            return datetime.date(today.year - n, today.month, min(today.day, 28))

    # Absolute: YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", expr)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # Absolute: YYYY-MM
    m = re.match(r"^(\d{4})-(\d{2})$", expr)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), 1)

    raise ValueError(f"Cannot parse date expression: {expr!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-source academic paper search")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--limit", type=int, default=20, help="Max results per source")
    parser.add_argument(
        "--sources",
        default="arxiv,openalex,s2,hf",
        help="Comma-separated sources: arxiv, openalex, s2, hf",
    )
    parser.add_argument("--year-min", type=int, default=0, help="Minimum year (legacy)")
    parser.add_argument("--since", type=str, default=None,
                        help='From date: "2 months", "2025-01", "2025-01-15"')
    parser.add_argument("--until", type=str, default=None,
                        help='To date: "2025-06", "2025-06-30"')
    parser.add_argument("--enrich-hf", action="store_true",
                        help="Enrich results with HuggingFace metadata")
    args = parser.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stderr)

    source_map = {"s2": "semantic_scholar", "arxiv": "arxiv", "openalex": "openalex", "hf": "hf"}
    sources = [source_map.get(s.strip(), s.strip()) for s in args.sources.split(",")]

    date_from = None
    date_to = None
    if args.since:
        date_from = parse_date_expr(args.since)
    if args.until:
        date_to = parse_date_expr(args.until)

    papers = search_papers(
        args.query,
        limit=args.limit,
        sources=sources,
        year_min=args.year_min,
        date_from=date_from,
        date_to=date_to,
    )

    if args.enrich_hf:
        from paper_research.hf_papers_client import enrich_with_hf_metadata
        papers = enrich_with_hf_metadata(papers)

    output = []
    for p in papers:
        authors = [a.name for a in p.authors]
        output.append({
            "title": p.title,
            "authors": authors,
            "year": p.year,
            "abstract": p.abstract,
            "arxiv_id": p.arxiv_id,
            "doi": p.doi,
            "url": p.url,
            "citation_count": p.citation_count,
            "source": p.source,
            "hf_metadata": p.hf_metadata,
        })

    json.dump(output, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
