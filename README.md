# paper-research

Multi-source academic paper search with deduplication, HuggingFace metadata enrichment, and multiple extraction paths.

Searches **arXiv**, **OpenAlex**, **Semantic Scholar**, and optionally **HuggingFace Papers**. Downloads PDFs or grabs free full-text markdown from HF when available.

Built as a standalone package and an [OpenClaw](https://github.com/openclaw/openclaw) agent skill.

## Install

```bash
pip install -e .
```

## Search

```bash
# Default sources (arXiv, OpenAlex, Semantic Scholar)
python -m paper_research search "chain of thought prompting" --limit 20

# Include HuggingFace Papers (AI/ML only)
python -m paper_research search "vision language models" --sources arxiv,openalex,s2,hf --limit 10

# Date filtering
python -m paper_research search "reasoning" --since "3 months" --until "2026-03"

# Enrich results with HF metadata (linked models, datasets, spaces, github)
python -m paper_research search "transformers" --sources hf,openalex --enrich-hf
```

## Download

```bash
# Download arXiv PDF
python -m paper_research download 2201.11903 --output /tmp/papers/

# Try HF markdown first (free, no GPU needed), fall back to PDF
python -m paper_research download 2401.02415 --output /tmp/papers/ --method hf
```

## Python API

```python
from paper_research import search_papers

papers = search_papers("transformer architecture", limit=10, sources=["arxiv", "openalex", "s2", "hf"])
for p in papers:
    print(f"{p.title} ({p.year}) - {p.citation_count} citations")
```

## Sources

| Source | Coverage | Notes |
|--------|----------|-------|
| arXiv | All fields | Direct API, title+abstract search |
| OpenAlex | All fields | Broad academic coverage, good citation data |
| Semantic Scholar | All fields | AI2, citation counts, rate-limited without API key |
| HuggingFace | AI/ML only | Opt-in via `--sources hf`. Linked models/datasets/spaces via `--enrich-hf` |

## HF Enrichment

When `--enrich-hf` is passed, papers with arXiv IDs get enriched with:
- Linked **models**, **datasets**, and **spaces** on HuggingFace
- **GitHub repo** and **project page** URLs
- **Upvotes** and **AI-generated summary**

## GPU Extraction

For full-text extraction from PDFs (when HF markdown isn't available):

```bash
bash scripts/gpu_batch_extract.sh /tmp/papers/
```

Spins up a Vast.ai GPU instance, runs marker-pdf batch extraction, downloads results, and tears down the instance.

## Skill Scripts

Convenience wrappers for agent workflows:

| Script | Purpose |
|--------|---------|
| `scripts/search.py` | Multi-source search with JSON output |
| `scripts/download.py` | Download PDFs or HF markdown |
| `scripts/gpu_batch_extract.sh` | Vast GPU lifecycle for marker-pdf |

## License

MIT
