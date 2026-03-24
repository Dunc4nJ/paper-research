---
name: paper-research
description: "Search, download, and extract academic papers from arXiv, OpenAlex, and Semantic Scholar. Use when the user says 'research papers on', 'find papers about', 'literature review', 'arxiv search', 'paper research', 'search for papers', or wants to build a reading list from academic sources."
---

# Paper Research

Search multiple academic databases, download PDFs, extract text via GPU-accelerated marker-pdf, and write structured vault notes.

## Workflow

### 1. Search

Run the search script against all three sources:

```bash
python3 ~/.agent/skills/paper-research/scripts/search.py "query terms" --limit 20
```

Options: `--sources arxiv,openalex,s2,hf` (default: arxiv,openalex,s2), `--limit N` (per source), `--enrich-hf` (add HF metadata).

The `hf` source searches HuggingFace Papers (hybrid semantic + full-text). It is NOT included by default — add it explicitly with `--sources arxiv,openalex,s2,hf`.

The `--enrich-hf` flag fetches additional metadata from HuggingFace for each paper with an arXiv ID: upvotes, AI summary, GitHub repo, project page, and counts of linked models/datasets/spaces.

Output: JSON array to stdout. Each entry has: title, authors, year, abstract, arxiv_id, doi, url, citation_count, source.

### 2. Screen Results

Review the JSON output. Filter by relevance, recency, citation count, and abstract quality. Discard off-topic or low-quality papers.

### 3. Present Shortlist (mandatory human gate)

**Always show the user a shortlist before proceeding.** Present: title, authors (first author + et al.), year, citation count, abstract (truncated to ~2 sentences), and source. Ask which papers to extract. Do not proceed without explicit approval.

### 4. Download PDFs

```bash
python3 ~/.agent/skills/paper-research/scripts/download.py --ids 2201.11903 2305.14314 --output /tmp/paper-research/
```

Downloads approved papers from arXiv by ID. Only papers with valid arXiv IDs can be downloaded.

Add `--method hf` to download papers as markdown from HuggingFace instead of PDF. Falls back to PDF if HF markdown is unavailable. This is a free alternative to GPU extraction for papers with HTML versions on arXiv.

```bash
python3 ~/.agent/skills/paper-research/scripts/download.py --ids 2301.00001 --method hf --output /tmp/paper-research/
```

### 5. GPU Extraction

```bash
bash ~/.agent/skills/paper-research/scripts/gpu_batch_extract.sh /tmp/paper-research/
```

Spins up a Vast.ai GPU instance, uploads all PDFs, runs marker-pdf batch extraction, downloads markdown results, and destroys the instance. See `references/api-notes.md` for details on the Vast lifecycle and retry logic.

If only 1-2 short papers, consider whether GPU extraction is worth the overhead. For simple papers, direct text extraction may suffice.

### 6. Synthesize

Read the extracted markdown files from `/tmp/paper-research/output/`. Identify key contributions, methods, findings, and connections between papers.

### 7. Write Vault Notes

Write to `/data/projects/obsidian-vault/` in the appropriate Knowledge section:

- **One note per paper**: frontmatter with `created`, `description`, `source` (URL or DOI). Include: summary, key contributions, methodology, results, limitations, relevant quotes.
- **Synthesis note** (optional): when multiple papers share a theme, write a synthesis connecting findings.
- **Update nearest MOC**: add links to new notes in the relevant Map of Contents.

### 8. Commit and Push

```bash
cd /data/projects/obsidian-vault && git add -A && git commit -m "Add paper notes: <topic>" && git push
qmd update
```

If Knowledge is a subrepo, commit and push it separately first.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/search.py` | Multi-source search with dedup, JSON output |
| `scripts/download.py` | Download arXiv PDFs by ID |
| `scripts/gpu_batch_extract.sh` | Vast GPU lifecycle for marker-pdf batch |

## References

- `references/api-notes.md` — Rate limits, quirks, and fallback behavior for each academic API, plus Vast GPU lifecycle notes.
