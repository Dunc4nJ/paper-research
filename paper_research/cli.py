"""CLI for paper-research: search and download academic papers."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="paper_research", description="Academic paper search CLI")
    sub = parser.add_subparsers(dest="command")

    # search
    sp = sub.add_parser("search", help="Search for papers")
    sp.add_argument("query", help="Search query")
    sp.add_argument("--limit", type=int, default=20, help="Max results per source")
    sp.add_argument("--sources", default="openalex,semantic_scholar,arxiv", help="Comma-separated sources")
    sp.add_argument("--year-min", type=int, default=0, help="Minimum publication year")

    # download
    dp = sub.add_parser("download", help="Download arXiv PDF")
    dp.add_argument("arxiv_id", help="arXiv paper ID (e.g. 2301.00001)")
    dp.add_argument("--output", default=".", help="Output directory")

    args = parser.parse_args()

    if args.command == "search":
        _do_search(args)
    elif args.command == "download":
        _do_download(args)
    else:
        parser.print_help()
        sys.exit(1)


def _do_search(args: argparse.Namespace) -> None:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from paper_research.search import search_papers

    sources = [s.strip() for s in args.sources.split(",")]
    papers = search_papers(args.query, limit=args.limit, sources=sources, year_min=args.year_min)

    if not papers:
        print("No results found.")
        return

    # Print formatted table
    print(f"\n{'#':>3}  {'Year':>4}  {'Citations':>9}  {'Source':<18}  {'Title'}")
    print("-" * 100)
    for i, p in enumerate(papers, 1):
        title = p.title[:60] + "…" if len(p.title) > 60 else p.title
        venue = p.venue[:15] if p.venue else ""
        print(f"{i:>3}  {p.year:>4}  {p.citation_count:>9}  {p.source:<18}  {title}")

    print(f"\nTotal: {len(papers)} papers (deduplicated)")


def _do_download(args: argparse.Namespace) -> None:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from paper_research.arxiv_client import download_pdf

    path = download_pdf(args.arxiv_id, dirpath=args.output)
    if path:
        print(f"Downloaded: {path}")
    else:
        print("Download failed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
