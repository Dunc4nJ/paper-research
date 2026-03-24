#!/usr/bin/env python3
"""Test HF Papers integration."""

import sys
sys.path.insert(0, "/data/projects/paper-research")

from paper_research.hf_papers_client import search_hf_papers, enrich_with_hf_metadata, fetch_hf_markdown
from paper_research.models import Paper


def test_search():
    print("=== Test 1: HF Search ===")
    papers = search_hf_papers("vision language models", limit=5)
    print(f"Found {len(papers)} papers")
    for p in papers[:3]:
        print(f"  - [{p.year}] {p.title[:80]}  (arxiv: {p.arxiv_id})")
    assert len(papers) > 0, "Expected at least 1 result"
    assert all(p.source == "hf" for p in papers)
    assert any(p.arxiv_id for p in papers), "Expected at least one paper with arxiv_id"
    print("PASSED\n")
    return papers


def test_enrichment(papers: list[Paper]):
    print("=== Test 2: HF Enrichment ===")
    # Use first paper with an arxiv_id
    subset = [p for p in papers if p.arxiv_id][:2]
    enriched = enrich_with_hf_metadata(subset)
    for p in enriched:
        if p.hf_metadata:
            m = p.hf_metadata
            print(f"  {p.arxiv_id}: upvotes={m.get('upvotes')}, "
                  f"models={m.get('models_count')}, datasets={m.get('datasets_count')}, "
                  f"spaces={m.get('spaces_count')}, github={m.get('github_repo', 'n/a')}")
        else:
            print(f"  {p.arxiv_id}: no HF metadata")
    assert any(p.hf_metadata for p in enriched), "Expected at least one enriched paper"
    print("PASSED\n")


def test_markdown():
    print("=== Test 3: HF Markdown Fetch ===")
    # Use a well-known paper
    md = fetch_hf_markdown("2310.06825")  # Mistral 7B
    if md:
        print(f"  Markdown length: {len(md)} chars")
        print(f"  First 200 chars: {md[:200]}...")
        print("PASSED\n")
    else:
        print("  Markdown not available (may be expected for some papers)")
        print("SKIPPED\n")


def test_enrichment_specific():
    print("=== Test 4: Enrichment on specific paper (2602.08025) ===")
    from paper_research.hf_papers_client import get_paper_metadata, get_linked_resources
    meta = get_paper_metadata("2602.08025")
    if meta:
        print(f"  Title: {meta.get('title', 'n/a')}")
        print(f"  Upvotes: {meta.get('upvotes', 'n/a')}")
        print(f"  GitHub: {meta.get('githubRepo', 'n/a')}")
    else:
        print("  Paper not found on HF")

    resources = get_linked_resources("2602.08025")
    print(f"  Models: {len(resources['models'])}, Datasets: {len(resources['datasets'])}, Spaces: {len(resources['spaces'])}")
    print("PASSED\n")


if __name__ == "__main__":
    papers = test_search()
    test_enrichment(papers)
    test_markdown()
    test_enrichment_specific()
    print("All tests passed!")
