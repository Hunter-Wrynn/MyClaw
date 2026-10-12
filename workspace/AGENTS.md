# Research push workspace

This is a portable OpenClaw workspace for Chinese research and news reports.
Use the bundled skills for Juya AI Daily, Hugging Face Daily Papers, and weekly
domain reviews. Return plain Markdown. Let OpenClaw Cron deliver scheduled
command stdout. Follow explicit user authorization for manual delivery.

Weekly reports use the native web search of the separate Codex CLI invoked by
the Python runner. Do not replace these scheduled command runners with browser
automation, screenshots, or agent-generated shell heredocs.

Keep credentials, personal identifiers, chat history, and local artifacts out of
version control. All source-verified report rules live in the relevant skill.
