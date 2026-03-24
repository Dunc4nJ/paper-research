#!/usr/bin/env python3
"""Download arXiv PDFs by ID."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "/data/projects/paper-research")

from paper_research.arxiv_client import download_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Download arXiv PDFs")
    parser.add_argument("--ids", nargs="+", required=True, help="arXiv IDs (e.g. 2201.11903)")
    parser.add_argument("--output", default="/tmp/paper-research", help="Output directory")
    parser.add_argument("--method", choices=["pdf", "hf"], default="pdf",
                        help="Download method: pdf (arXiv PDF) or hf (HF markdown, falls back to PDF)")
    args = parser.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s", stream=sys.stderr)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for arxiv_id in args.ids:
        path = None
        if args.method == "hf":
            from paper_research.hf_papers_client import fetch_hf_markdown
            md = fetch_hf_markdown(arxiv_id)
            if md:
                md_path = out_dir / f"{arxiv_id.replace('/', '_')}.md"
                md_path.write_text(md)
                results.append({"arxiv_id": arxiv_id, "path": str(md_path), "status": "ok", "format": "markdown"})
                print(f"Downloaded markdown: {md_path}", file=sys.stderr)
                continue
            else:
                print(f"HF markdown unavailable for {arxiv_id}, falling back to PDF", file=sys.stderr)

        path = download_pdf(arxiv_id, dirpath=str(out_dir))
        if path:
            results.append({"arxiv_id": arxiv_id, "path": str(path), "status": "ok", "format": "pdf"})
            print(f"Downloaded: {path}", file=sys.stderr)
        else:
            results.append({"arxiv_id": arxiv_id, "path": None, "status": "failed"})
            print(f"Failed: {arxiv_id}", file=sys.stderr)

    import json
    json.dump(results, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
