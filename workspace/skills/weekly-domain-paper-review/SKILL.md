---
name: weekly-domain-paper-review
description: Search and verify recent research papers and produce a Chinese weekly or date-range domain report. Use for 专题论文周报、领域论文回溯、组会精读推荐 with original-source verification.
---

# Weekly Domain Paper Review

Use the Python runner with the preset matching the user's requested topic.
It invokes Codex native web search, verifies original paper pages, extracts the
final Markdown, and checks the six-section report contract. OpenClaw Cron
delivers stdout. The runner itself does not send messages.

## Inputs and presets

The default date range is the previous complete Monday–Sunday week in
Asia/Shanghai. For an explicit range pass both `--start` and `--end`.

- `monday-routing`: Model Reuse / Model Routing / Model Selection
- `tuesday-structured-data`: Tabular / Time Series / Structured Data Foundation Models
- `wednesday-adaptation`: Continual Learning / Test-Time Adaptation / Meta-Learning / Efficient Adaptation
- `thursday-posttraining`: LLM Post-training / RLVR / Reward-Value Model / Verifier / Test-time Scaling
- `friday-mllm`: Multimodal LLM / VLM / Evaluation & Adaptation

```bash
python3 {baseDir}/scripts/run_codex_weekly.py --preset monday-routing
python3 {baseDir}/scripts/run_codex_weekly.py --preset monday-routing --start YYYY-MM-DD --end YYYY-MM-DD --diagnostics
python3 {baseDir}/scripts/run_codex_weekly.py --preset monday-routing --print-prompt
```

`MYCLAW_CODEX_MODEL` selects the default model; `--model` overrides it.
Paths are derived from this skill's installed workspace, or overridden with
`MYCLAW_WORKSPACE`. Codex must be in PATH or `MYCLAW_CODEX_BIN` must point to it.

## Research and report rules

Read [verification-policy.md](references/verification-policy.md) and
[report-format.md](references/report-format.md) when checking or changing reports.
Prefer original arXiv, OpenReview, ACL Anthology, conference and official project
pages. Search snippets discover candidates but do not establish methods or
results. Deduplicate versions, mark older exceptions and distinguish author
claims from analysis. Favor methodological contributions, cross-model/task/domain
generalization and reproducibility. Return fewer papers when quality is lacking.

Do not use screenshots or attachments for these reports. Scheduled commands
must return only the complete Markdown on stdout; use `--diagnostics` only for
local debugging.

## Failure handling

Rejected drafts are retained locally under
`.artifacts/weekly-domain-paper-review/` and excluded from Git. Up to two
format-only repair passes share the runner's 2340-second total budget inside
the Cron job's 2400-second limit. Repair cannot add papers, URLs or experimental
facts. Output must pass the same strict validator before delivery.

The bundled `search_arxiv.py` is an optional local candidate-pool utility;
scheduled runs use Codex native web search directly.
