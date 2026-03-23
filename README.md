# paper-research

Standalone academic paper search across arXiv, OpenAlex, and Semantic Scholar with automatic deduplication.

## Install

```bash
pip install -e .
```

## CLI Usage

```bash
# Search across all sources
python -m paper_research search "chain of thought prompting" --limit 20

# Download arXiv PDF
python -m paper_research download 2201.11903 --output /tmp/
```

## Python API

```python
from paper_research import search_papers

papers = search_papers("transformer architecture", limit=10)
for p in papers:
    print(f"{p.title} ({p.year}) - {p.citation_count} citations")
```
