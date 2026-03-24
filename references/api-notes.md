# API Notes

## arXiv

- **Rate limit**: 1 request per 3 seconds (enforced by client sleep)
- **API**: Atom feed at `export.arxiv.org/api/query`
- **Quirks**: Can hang on pagination; the `paper_research` package uses httpx with explicit timeouts instead of the `arxiv` pip library
- **PDF download**: `https://arxiv.org/pdf/{id}.pdf` — no auth required
- **Fallback**: If export.arxiv.org is slow, results from cache are used

## OpenAlex

- **Rate limit**: 10,000 requests/day (unauthenticated), 100K with polite pool (set `mailto` header)
- **API**: REST at `api.openalex.org`
- **Quirks**: Most generous limits; queried first to reduce pressure on other sources
- **Fallback**: Cache hit on failure

## Semantic Scholar

- **Rate limit**: 1,000 requests per 5 minutes (unauthenticated); higher with API key
- **API**: REST at `api.semanticscholar.org/graph/v1`
- **Quirks**: Best citation data; 1s delay added between calls
- **Fallback**: Cache hit on failure; set `S2_API_KEY` env var for higher limits

## Search Priority

Sources are queried in order: OpenAlex → Semantic Scholar → arXiv. This minimizes rate-limit risk (most generous first). If any source fails, cached results are used transparently.

## Vast GPU Lifecycle (for gpu_batch_extract.sh)

- Search filter: `reliability>0.99`, `inet_down>100`, `inet_up>50`, prefer US/EU geo
- Falls back to ≥95% reliability if no ≥99% offers available
- SSH wait: 3 minutes max, then destroy and retry (up to 3 attempts)
- marker-pdf installed fresh each time (instances are ephemeral)
- First run downloads OCR models (~2 GB, ~8 min); subsequent runs ~2-3 pages/sec
