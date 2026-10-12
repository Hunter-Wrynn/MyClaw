#!/usr/bin/env python3
"""Fetch Juya AI Daily as deterministic plain Markdown."""

from __future__ import annotations

import argparse
import html as html_lib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass


BASE_URL = "https://daily.juya.uk/"
RSS_URL = urllib.parse.urljoin(BASE_URL, "rss.xml")
USER_AGENT = "Mozilla/5.0 (compatible; OpenClaw-ai-daily/1.0; +https://daily.juya.uk/)"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class FetchError(RuntimeError):
    """A user-facing fetch or parse failure."""


@dataclass(frozen=True)
class Issue:
    date: str
    url: str
    body_html: str


def fetch_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/html;q=0.9, */*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"request failed for {url}: {exc}") from exc


def normalize_date(value: str) -> str:
    value = value.strip()
    if not DATE_RE.fullmatch(value):
        raise FetchError(f"invalid date {value!r}; expected YYYY-MM-DD")
    return value


def issue_from_rss() -> Issue:
    try:
        root = ET.fromstring(fetch_text(RSS_URL))
    except ET.ParseError as exc:
        raise FetchError(f"invalid RSS XML: {exc}") from exc

    item = root.find("./channel/item")
    if item is None:
        raise FetchError("RSS contains no issues")

    issue_url = (item.findtext("link") or "").strip()
    issue_date = (item.findtext("title") or "").strip()
    content = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
    body_html = content.text if content is not None and content.text else ""
    if not issue_url or not body_html:
        raise FetchError("latest RSS issue is missing its URL or full content")

    if not DATE_RE.fullmatch(issue_date):
        match = re.search(r"/issues/(\d{4}-\d{2}-\d{2})/", issue_url)
        if not match:
            raise FetchError("could not determine latest issue date from RSS")
        issue_date = match.group(1)
    return Issue(issue_date, issue_url, body_html)


def latest_issue_url_from_homepage() -> tuple[str, str]:
    homepage = fetch_text(BASE_URL)
    matches = re.findall(
        r'href=["\']([^"\']*/issues/(\d{4}-\d{2}-\d{2})/?)',
        homepage,
        flags=re.I,
    )
    if not matches:
        raise FetchError("homepage contains no issue links")
    relative_url, issue_date = max(matches, key=lambda pair: pair[1])
    return issue_date, urllib.parse.urljoin(BASE_URL, html_lib.unescape(relative_url))


def issue_from_website(issue_date: str | None = None) -> Issue:
    if issue_date is None:
        issue_date, issue_url = latest_issue_url_from_homepage()
    else:
        issue_date = normalize_date(issue_date)
        issue_url = urllib.parse.urljoin(BASE_URL, f"issues/{issue_date}/")
    return Issue(issue_date, issue_url, fetch_text(issue_url))


def latest_issue() -> Issue:
    errors: list[str] = []
    for source, loader in (("RSS", issue_from_rss), ("website", issue_from_website)):
        try:
            return loader()
        except FetchError as exc:
            errors.append(f"{source}: {exc}")
    raise FetchError("; ".join(errors))


def plain_text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</(?:p|li|ul|ol|blockquote|h[1-6])>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = html_lib.unescape(fragment)
    fragment = re.sub(r"[ \t\r\f\v]+", " ", fragment)
    fragment = re.sub(r" *\n *", "\n", fragment)
    return re.sub(r"\n{3,}", "\n\n", fragment).strip()


def inline_markdown(fragment: str) -> str:
    def replace_link(match: re.Match[str]) -> str:
        attrs, inner = match.group(1), match.group(2)
        href_match = re.search(r'href=["\']([^"\']+)["\']', attrs, flags=re.I)
        label = plain_text(inner)
        if not href_match or not label:
            return label
        href = html_lib.unescape(href_match.group(1))
        return f"[{label}]({href})"

    fragment = re.sub(r"<a\b([^>]*)>(.*?)</a>", replace_link, fragment, flags=re.I | re.S)
    fragment = re.sub(r"</?code\b[^>]*>", "", fragment, flags=re.I)
    return " ".join(plain_text(fragment).split())


def overview_fragment(body_html: str) -> str:
    start = re.search(r"<h2\b[^>]*>\s*概览\s*</h2>", body_html, flags=re.I | re.S)
    if not start:
        raise FetchError("Overview heading was not found")
    remainder = body_html[start.end() :]
    end = re.search(r"<hr\b[^>]*>|<h2\b[^>]*>", remainder, flags=re.I)
    return remainder[: end.start()] if end else remainder


def overview_markdown(body_html: str) -> str:
    fragment = overview_fragment(body_html)
    categories = re.findall(
        r"<h3\b[^>]*>(.*?)</h3>\s*<ul\b[^>]*>(.*?)</ul>",
        fragment,
        flags=re.I | re.S,
    )
    if not categories:
        text = plain_text(fragment)
        if not text:
            raise FetchError("Overview section is empty")
        return "## 概览\n\n" + text

    output = ["## 概览"]
    for heading_html, list_html in categories:
        heading = inline_markdown(heading_html)
        items = re.findall(r"<li\b[^>]*>(.*?)</li>", list_html, flags=re.I | re.S)
        if not heading or not items:
            continue
        output.extend(("", f"### {heading}", ""))
        output.extend(f"- {inline_markdown(item)}" for item in items)
    if len(output) == 1:
        raise FetchError("Overview categories are empty")
    return "\n".join(output)


def item_markdown(issue: Issue, item_number: int) -> str:
    header = None
    for candidate in re.finditer(r"<h3\b[^>]*>(.*?)</h3>", issue.body_html, flags=re.I | re.S):
        if re.search(
            rf"<code\b[^>]*>\s*#{item_number}\s*</code>",
            candidate.group(1),
            flags=re.I,
        ):
            header = candidate
            break
    if not header:
        raise FetchError(f"item #{item_number} was not found in issue {issue.date}")
    remainder = issue.body_html[header.end() :]
    end = re.search(r"<h3\b[^>]*>|<h2\b[^>]*>|<hr\b[^>]*>", remainder, flags=re.I)
    detail_html = remainder[: end.start()] if end else remainder
    title = inline_markdown(header.group(1))
    details = plain_text(detail_html)
    output = [f"# Juya AI Daily｜{issue.date}", "", f"原文：{issue.url}", "", f"## {title}"]
    if details:
        output.extend(("", details))
    return "\n".join(output)


def issue_markdown(issue: Issue) -> str:
    return f"# Juya AI Daily｜{issue.date}\n\n原文：{issue.url}\n\n{overview_markdown(issue.body_html)}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", action="append", default=[], help="issue date (repeatable, YYYY-MM-DD)")
    parser.add_argument("--item", type=int, help="return details for one numbered item")
    args = parser.parse_args()
    if args.item is not None and args.item < 1:
        parser.error("--item must be a positive integer")
    if args.item is not None and len(args.date) > 1:
        parser.error("--item accepts at most one --date")
    return args


def main() -> int:
    args = parse_args()
    try:
        issues = [issue_from_website(normalize_date(value)) for value in args.date] if args.date else [latest_issue()]
        rendered = [item_markdown(issue, args.item) if args.item else issue_markdown(issue) for issue in issues]
    except FetchError as exc:
        print(f"ai-daily fetch failed: {exc}", file=sys.stderr)
        return 1
    print("\n\n---\n\n".join(rendered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
