# Verification Policy

## Source priority

Use sources in this order:

1. Official conference, workshop, journal, or project page
2. arXiv abstract page
3. OpenReview forum page
4. ACL Anthology page
5. Official author or lab repository

Use search engines, aggregators, Semantic Scholar, and snippets only to discover candidates. Do not cite them as the sole evidence for a selected paper.

## Date rules

- Treat the requested range as inclusive.
- `首次发布时间` means the earliest verified public paper date.
- `最近更新时间` means a verified revision or official update date.
- A paper first posted before the range is not a new paper merely because search results surfaced it.
- Include an older paper only when it had an important update in the range or when the user explicitly permits influential background work.
- Label older additions as `范围外补充` and show both first and latest dates.

## Evidence rules

- Verify exact title and authors from the original page.
- Preserve the canonical arXiv, OpenReview, ACL Anthology, DOI, or conference URL.
- Verify a code link from the paper page, official project page, or an author-controlled repository.
- Attribute reported performance and conclusions to the authors.
- Mark cross-paper comparisons and group relevance as analysis.
- Do not claim a venue acceptance when only a preprint is verified.
- Do not infer code availability from a paper title or search snippet.

## Deduplication rules

Treat arXiv, OpenReview, workshop, and conference versions as one work when titles, authors, and methods substantially match. Select the version with the clearest current status, while mentioning another canonical version only when useful.

## Selection quality

Prefer:

- New pretraining, in-context learning, instruction tuning, zero/few-shot, or adaptation methods
- Cross-dataset, cross-domain, cross-task, or schema-transfer evidence
- Clear comparisons with traditional and modern baselines
- Public code, data, weights, or sufficiently detailed experiments

Normally reject:

- Pure surveys, benchmarks, and dataset releases
- Traditional single-dataset task models
- Industry applications with results but no methodological contribution
- Weak keyword matches without a foundation-model or transfer-learning contribution
