#!/usr/bin/env python3
"""Search arXiv for a verified date-range candidate pool."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

API_URL = "https://arxiv.org/api/query"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
USER_AGENT = "OpenClaw weekly-domain-paper-review/1.0"


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date {value!r}; use YYYY-MM-DD") from exc


def clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def base_arxiv_id(url: str) -> str:
    value = url.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", value)


def iso_date(value: str) -> dt.date:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def quote_term(term: str) -> str:
    safe = term.replace("\\", " ").replace('"', " ").strip()
    return f'all:"{safe}"'


def fetch_feed(search_query: str, max_results: int) -> bytes:
    params = urllib.parse.urlencode(
        {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "lastUpdatedDate",
            "sortOrder": "descending",
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml"},
    )
    delays = (0, 4, 12, 30)
    last_error: Exception | None = None
    for delay in delays:
        if delay:
            time.sleep(delay)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
    raise RuntimeError(f"arXiv API request failed after retries: {last_error}")


def entry_value(entry: ET.Element, path: str) -> str:
    return clean_text(entry.findtext(path, default="", namespaces=ATOM))


def parse_entries(
    payload: bytes,
    start: dt.date,
    end: dt.date,
    terms: list[str],
    abstract_chars: int,
) -> list[dict]:
    root = ET.fromstring(payload)
    candidates: dict[str, dict] = {}
    for entry in root.findall("a:entry", ATOM):
        canonical_url = entry_value(entry, "a:id")
        arxiv_id = base_arxiv_id(canonical_url)
        published_raw = entry_value(entry, "a:published")
        updated_raw = entry_value(entry, "a:updated")
        if not arxiv_id or not published_raw or not updated_raw:
            continue

        published = iso_date(published_raw)
        updated = iso_date(updated_raw)
        within_published = start <= published <= end
        within_updated = start <= updated <= end
        if not (within_published or within_updated):
            continue

        title = entry_value(entry, "a:title")
        abstract = entry_value(entry, "a:summary")
        haystack = f"{title}\n{abstract}".casefold()
        matched = [term for term in terms if term.casefold() in haystack]
        if not matched:
            continue

        authors = [
            clean_text(author.findtext("a:name", default="", namespaces=ATOM))
            for author in entry.findall("a:author", ATOM)
        ]
        authors = [author for author in authors if author]
        categories = [
            category.attrib.get("term", "")
            for category in entry.findall("a:category", ATOM)
            if category.attrib.get("term")
        ]
        primary = entry.find("a:primary_category", {"a": "http://arxiv.org/schemas/atom"})
        primary_category = primary.attrib.get("term") if primary is not None else None

        pdf_url = None
        for link in entry.findall("a:link", ATOM):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href")
                break

        if within_published and within_updated:
            date_basis = "first-published-and-updated-in-range"
        elif within_published:
            date_basis = "first-published-in-range"
        else:
            date_basis = "older-paper-updated-in-range"

        candidates[arxiv_id] = {
            "arxiv_id": arxiv_id,
            "title": title,
            "authors": authors,
            "published": published.isoformat(),
            "updated": updated.isoformat(),
            "date_basis": date_basis,
            "primary_category": primary_category,
            "categories": categories,
            "abstract": abstract[:abstract_chars],
            "abstract_truncated": len(abstract) > abstract_chars,
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            "pdf_url": pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
            "matched_queries": matched,
            "match_count": len(matched),
        }

    return sorted(
        candidates.values(),
        key=lambda item: (item["match_count"], item["updated"], item["published"]),
        reverse=True,
    )


def to_markdown(result: dict) -> str:
    lines = [
        f"# arXiv candidates: {result['range']['start']} to {result['range']['end']}",
        "",
        f"Matched candidates: {result['count']}",
        "",
    ]
    for item in result["candidates"]:
        lines.extend(
            [
                f"- [{item['title']}]({item['abs_url']})",
                f"  - First: {item['published']}; updated: {item['updated']}; {item['date_basis']}",
                f"  - Categories: {', '.join(item['categories'])}",
                f"  - Matched: {', '.join(item['matched_queries'])}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, type=parse_date)
    parser.add_argument("--end", required=True, type=parse_date)
    parser.add_argument("--query", action="append", required=True)
    parser.add_argument("--max-results", type=int, default=120)
    parser.add_argument("--abstract-chars", type=int, default=1600)
    parser.add_argument("--format", choices=("json", "md"), default="json")
    args = parser.parse_args()

    if args.start > args.end:
        parser.error("--start must be on or before --end")

    terms = list(dict.fromkeys(clean_text(term) for term in args.query if clean_text(term)))
    if not terms:
        parser.error("at least one non-empty --query is required")

    max_results = max(1, min(args.max_results, 300))
    abstract_chars = max(200, min(args.abstract_chars, 5000))
    search_query = "(" + " OR ".join(quote_term(term) for term in terms) + ")"

    try:
        payload = fetch_feed(search_query, max_results)
        candidates = parse_entries(
            payload, args.start, args.end, terms, abstract_chars
        )
    except (RuntimeError, ET.ParseError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    result = {
        "ok": True,
        "range": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "queries": terms,
        "search_query": search_query,
        "requested_results": max_results,
        "count": len(candidates),
        "candidates": candidates,
    }
    if args.format == "md":
        sys.stdout.write(to_markdown(result))
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
