---
name: hf-daily
description: Fetch a date-specific Hugging Face Daily Papers ranking from the official API and return the top papers as concise Markdown with Chinese method and contribution summaries. Use for Hugging Face Daily Papers、HF 每日论文、HF Daily Top 10、每日论文榜单，especially when browser-free deterministic Cron delivery is required.
---

# Hugging Face Daily Papers

Use the bundled Python runner. Do not replace it with an `agentTurn`, browser
automation, screenshot, inline Python, or shell parsing.

## Latest daily Top 10

```bash
python3 {baseDir}/scripts/fetch_hf_daily.py
```

The runner uses the current `Asia/Shanghai` date, queries the official Hugging
Face Daily Papers API, preserves API ranking order, summarizes the returned
abstracts in Chinese, validates the Markdown, and writes only the report to
stdout.

## Specific date

```bash
python3 {baseDir}/scripts/fetch_hf_daily.py --date YYYY-MM-DD
```

If the requested date has fewer than ten papers, return only that date's actual
papers. If it has none, return a concise no-papers Markdown message. Never fill
the list with papers from another date.

## Delivery rules

- Return text/Markdown only; never generate screenshots, images, PDFs, or attachments.
- Do not send messages from the script. Let Cron deliver stdout.
- Use `--diagnostics` only for local testing; scheduled runs must omit it.
- If Chinese summarization is unavailable after the API succeeds, return the
  validated official-abstract fallback instead of an empty report.
