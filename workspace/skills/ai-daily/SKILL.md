---
name: ai-daily
description: "Fetch the latest or date-specific Juya AI Daily brief from https://daily.juya.uk/ and return its Overview as plain Markdown. Use for AI 日报、AI 早报、今日 AI 新闻、Juya AI Daily, or details about a numbered item."
metadata:
  {
    "openclaw":
      {
        "emoji": "🗞️",
        "requires": { "bins": ["python3"] },
      },
  }
---

# Juya AI Daily

Use the bundled deterministic script. Do not rewrite it as an inline Python heredoc.

## Latest overview

Run exactly once:

```bash
python3 {baseDir}/scripts/fetch_ai_daily.py
```

Return the script's stdout verbatim as the final plain Markdown response.

## Specific dates

Pass one or more `--date` options:

```bash
python3 {baseDir}/scripts/fetch_ai_daily.py --date 2026-07-22
python3 {baseDir}/scripts/fetch_ai_daily.py --date 2026-07-21 --date 2026-07-22
```

## Numbered item details

Pass `--item` with either the latest issue or one explicit date:

```bash
python3 {baseDir}/scripts/fetch_ai_daily.py --item 3
python3 {baseDir}/scripts/fetch_ai_daily.py --date 2026-07-22 --item 3
```

## Delivery rules

- Return text/Markdown only. Never generate or attach an image or screenshot.
- Never use a browser for this skill; the script handles RSS and website fallback internally.
- Never call `message`, Feishu, or another channel tool. Let the current chat or cron delivery publish the final response.
- Do not run ad-hoc RSS/GitHub commands before or after the script.
- If the script fails, return its concise error. Do not retry with a browser, inline Python, or the retired GitHub repository.
