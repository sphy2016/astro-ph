#!/usr/bin/env python3
"""Fetch and prepare arXiv material for the astro-ph reading diary."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


DEFAULT_CATEGORIES = [
    "astro-ph.CO",
    "astro-ph.EP",
    "astro-ph.GA",
    "astro-ph.HE",
    "astro-ph.IM",
    "astro-ph.SR",
]
DEFAULT_LOOKBACK_HOURS = 36.0
DEFAULT_MAX_RESULTS = 200
NEW_LIST_URL = "https://arxiv.org/list/astro-ph/new"

ROOT = Path(__file__).resolve().parents[1]
AI_DIR = ROOT / "ai"
WORK_DIR = AI_DIR / "work"
LATEST_PAPERS = WORK_DIR / "latest_papers.json"
LATEST_SOURCE_PACK = WORK_DIR / "latest_source_pack.md"
LATEST_MANIFEST = WORK_DIR / "latest_manifest.json"
STATE_FILE = AI_DIR / "state.json"

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

YEAR_DIR_RE = re.compile(r"^\d{4}$")
ARXIV_URL_ID_RE = re.compile(
    r"(?:export\.)?arxiv\.org/(?:abs|pdf)/"
    r"(?P<id>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}))"
    r"(?:v\d+)?(?:\.pdf)?",
    re.IGNORECASE,
)
ARXIV_ID_RE = re.compile(
    r"(?P<id>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}))(?:v\d+)?",
    re.IGNORECASE,
)
VERSION_SUFFIX_RE = re.compile(r"v\d+$", re.IGNORECASE)


class ArxivNotesError(RuntimeError):
    """Expected command failure."""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(value: dt.datetime | None = None) -> str:
    value = value or utc_now()
    return value.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def parse_datetime(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        return None


def normalize_arxiv_id(value: Any) -> str:
    text = str(value or "").strip()
    match = ARXIV_ID_RE.search(text)
    if not match:
        return text
    return VERSION_SUFFIX_RE.sub("", match.group("id"))


def parse_arxiv_id_from_url(value: str) -> str:
    return normalize_arxiv_id(value)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArxivNotesError(f"invalid JSON in {relative_path(path)}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def build_arxiv_search_url(categories: list[str], max_results: int) -> str:
    query = " OR ".join(f"cat:{category}" for category in categories)
    params = urllib.parse.urlencode(
        {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    return f"https://export.arxiv.org/api/query?{params}"


def build_arxiv_id_url(arxiv_ids: list[str]) -> str:
    params = urllib.parse.urlencode(
        {
            "id_list": ",".join(arxiv_ids),
            "max_results": len(arxiv_ids),
        }
    )
    return f"https://export.arxiv.org/api/query?{params}"


def entry_text(entry: ET.Element, path: str) -> str:
    value = entry.findtext(path, namespaces=ATOM_NS)
    return clean_text(value)


def parse_entry(entry: ET.Element) -> dict[str, Any] | None:
    entry_id = entry_text(entry, "atom:id")
    arxiv_id = parse_arxiv_id_from_url(entry_id)
    if not arxiv_id:
        return None

    authors = [
        clean_text(author.findtext("atom:name", namespaces=ATOM_NS))
        for author in entry.findall("atom:author", ATOM_NS)
    ]
    authors = [author for author in authors if author]

    category_terms = [
        clean_text(category.attrib.get("term", ""))
        for category in entry.findall("atom:category", ATOM_NS)
    ]
    category_terms = [category for category in category_terms if category]

    primary_node = entry.find("arxiv:primary_category", ATOM_NS)
    primary_category = ""
    if primary_node is not None:
        primary_category = clean_text(primary_node.attrib.get("term", ""))
    if not primary_category and category_terms:
        primary_category = category_terms[0]

    return {
        "arxiv_id": arxiv_id,
        "title": entry_text(entry, "atom:title"),
        "authors": authors,
        "abstract": entry_text(entry, "atom:summary"),
        "primary_category": primary_category,
        "categories": category_terms,
        "published": entry_text(entry, "atom:published"),
        "updated": entry_text(entry, "atom:updated"),
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
    }


def paper_published_datetime(paper: dict[str, Any]) -> dt.datetime | None:
    return parse_datetime(clean_text(paper.get("published", "")))


def latest_available_day_papers(papers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    dated = [
        (published, paper)
        for paper in papers
        if (published := paper_published_datetime(paper)) is not None
    ]
    if not dated:
        return papers, "No papers matched the lookback window; using unfiltered API results."

    latest_day = max(published.date() for published, _paper in dated)
    fallback = [paper for published, paper in dated if published.date() == latest_day]
    return fallback, f"No papers matched the lookback window; using latest arXiv date {latest_day}."


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "astro-ph-reading/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def parse_atom_payload(payload: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    papers = []
    for entry in root.findall("atom:entry", ATOM_NS):
        paper = parse_entry(entry)
        if paper:
            papers.append(paper)
    return papers


def fetch_new_submission_ids() -> list[str]:
    html = fetch_url(NEW_LIST_URL).decode("utf-8", errors="replace")
    start = html.find("<h3>New submissions")
    if start == -1:
        raise ArxivNotesError("could not find New submissions section on arXiv new-list page")

    section_ends = [
        value
        for value in (
            html.find("<h3>Cross", start),
            html.find("<h3>Replacements", start),
        )
        if value != -1
    ]
    end = min(section_ends) if section_ends else len(html)
    section = html[start:end]

    ids = []
    seen: set[str] = set()
    for match in re.finditer(
        r"href\s*=\s*['\"]/abs/"
        r"(?P<id>(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)"
        r"['\"]",
        section,
        re.IGNORECASE,
    ):
        arxiv_id = normalize_arxiv_id(match.group("id"))
        if arxiv_id and arxiv_id not in seen:
            ids.append(arxiv_id)
            seen.add(arxiv_id)
    return ids


def fetch_papers_by_ids(arxiv_ids: list[str], categories: list[str]) -> list[dict[str, Any]]:
    papers_by_id: dict[str, dict[str, Any]] = {}
    chunk_size = 50
    for offset in range(0, len(arxiv_ids), chunk_size):
        chunk = arxiv_ids[offset : offset + chunk_size]
        for paper in parse_atom_payload(fetch_url(build_arxiv_id_url(chunk))):
            if any(category in paper["categories"] for category in categories):
                papers_by_id[paper["arxiv_id"]] = paper

    return [papers_by_id[arxiv_id] for arxiv_id in arxiv_ids if arxiv_id in papers_by_id]


def fetch_search_papers(
    categories: list[str],
    lookback_hours: float,
    max_results: int,
    strict_lookback: bool,
) -> tuple[list[dict[str, Any]], str]:
    url = build_arxiv_search_url(categories, max_results)
    cutoff = utc_now() - dt.timedelta(hours=lookback_hours)

    all_papers_by_id: dict[str, dict[str, Any]] = {}
    for paper in parse_atom_payload(fetch_url(url)):
        if not any(category in paper["categories"] for category in categories):
            continue
        all_papers_by_id[paper["arxiv_id"]] = paper

    all_papers = list(all_papers_by_id.values())
    papers = [
        paper
        for paper in all_papers
        if (published := paper_published_datetime(paper)) is None or published >= cutoff
    ]

    note = ""
    if not papers and all_papers and not strict_lookback:
        papers, note = latest_available_day_papers(all_papers)

    return sorted(
        papers,
        key=lambda paper: (paper.get("published", ""), paper.get("arxiv_id", "")),
    ), note


def load_latest_papers() -> list[dict[str, Any]]:
    data = load_json(LATEST_PAPERS, [])
    if not isinstance(data, list):
        raise ArxivNotesError(f"{relative_path(LATEST_PAPERS)} must contain a JSON list")
    papers = []
    for item in data:
        if isinstance(item, dict):
            papers.append(item)
    return papers


def diary_markdown_files() -> list[Path]:
    paths: list[Path] = []
    for year_dir in sorted(ROOT.iterdir()):
        if not year_dir.is_dir() or not YEAR_DIR_RE.fullmatch(year_dir.name):
            continue
        paths.extend(sorted(year_dir.glob("*.md")))
    return paths


def existing_arxiv_ids() -> set[str]:
    ids: set[str] = set()
    for path in diary_markdown_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in ARXIV_URL_ID_RE.finditer(text):
            ids.add(normalize_arxiv_id(match.group("id")))
    return ids


def unseen_papers(papers: list[dict[str, Any]], seen_ids: set[str]) -> list[dict[str, Any]]:
    result = []
    added: set[str] = set()
    for paper in papers:
        arxiv_id = normalize_arxiv_id(paper.get("arxiv_id", ""))
        if not arxiv_id or arxiv_id in seen_ids or arxiv_id in added:
            continue
        paper = dict(paper)
        paper["arxiv_id"] = arxiv_id
        result.append(paper)
        added.add(arxiv_id)
    return sorted(result, key=lambda paper: (paper.get("published", ""), paper.get("arxiv_id", "")))


def normalize_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for paper in sorted(papers, key=lambda item: normalize_arxiv_id(item.get("arxiv_id", ""))):
        categories = paper.get("categories") or []
        if not isinstance(categories, list):
            categories = [categories]
        authors = paper.get("authors") or []
        if not isinstance(authors, list):
            authors = [authors]
        normalized.append(
            {
                "abstract": clean_text(paper.get("abstract", "")),
                "abs_url": clean_text(paper.get("abs_url", "")),
                "arxiv_id": normalize_arxiv_id(paper.get("arxiv_id", "")),
                "authors": [clean_text(author) for author in authors if clean_text(author)],
                "categories": sorted({clean_text(category) for category in categories if clean_text(category)}),
                "primary_category": clean_text(paper.get("primary_category", "")),
                "published": clean_text(paper.get("published", "")),
                "title": clean_text(paper.get("title", "")),
                "updated": clean_text(paper.get("updated", "")),
            }
        )
    return normalized


def material_fingerprint(papers: list[dict[str, Any]]) -> str:
    if not papers:
        return ""
    payload = json.dumps(
        normalize_papers(papers),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_state() -> dict[str, Any]:
    data = load_json(STATE_FILE, {})
    if not isinstance(data, dict):
        return {}
    return data


def previous_fingerprint() -> str:
    return clean_text(load_state().get("last_material_fingerprint", ""))


def suggested_target_monthly_file(papers: list[dict[str, Any]]) -> str:
    dates = [clean_text(paper.get("published", "")) for paper in papers]
    dates = [value for value in dates if re.match(r"^\d{4}-\d{2}", value)]
    if dates:
        value = max(dates)
        year = value[0:4]
        month = value[5:7]
    else:
        now = utc_now()
        year = f"{now.year:04d}"
        month = f"{now.month:02d}"
    return f"{year}/arxiv{year}{month}.md"


def write_source_pack(papers: list[dict[str, Any]], fingerprint: str, target: str) -> str:
    generated_at = iso_utc()
    lines = [
        "# arXiv source pack",
        "",
        f"Generated: {generated_at}",
        f"Fingerprint: {fingerprint}",
        f"Paper count: {len(papers)}",
        f"Suggested target monthly file: {target}",
        "",
    ]

    for paper in papers:
        authors = paper.get("authors") or []
        categories = paper.get("categories") or []
        lines.extend(
            [
                f"## {normalize_arxiv_id(paper.get('arxiv_id', ''))}",
                "",
                f"Title: {clean_text(paper.get('title', ''))}",
                f"Authors: {', '.join(clean_text(author) for author in authors)}",
                f"Published: {clean_text(paper.get('published', ''))}",
                f"Updated: {clean_text(paper.get('updated', ''))}",
                f"Primary category: {clean_text(paper.get('primary_category', ''))}",
                f"Categories: {', '.join(clean_text(category) for category in categories)}",
                f"Abs URL: {clean_text(paper.get('abs_url', ''))}",
                "",
                "Abstract:",
                clean_text(paper.get("abstract", "")),
                "",
            ]
        )

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_SOURCE_PACK.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return generated_at


def write_manifest(
    papers: list[dict[str, Any]],
    fingerprint: str,
    target: str,
    generated_at: str,
) -> None:
    write_json(
        LATEST_MANIFEST,
        {
            "arxiv_ids": [normalize_arxiv_id(paper.get("arxiv_id", "")) for paper in papers],
            "fingerprint": fingerprint,
            "generated_at": generated_at,
            "paper_count": len(papers),
            "suggested_target_monthly_file": target,
        },
    )


def command_fetch(args: argparse.Namespace) -> int:
    categories = args.category or DEFAULT_CATEGORIES
    if args.strict_lookback:
        papers, note = fetch_search_papers(
            categories,
            args.lookback_hours,
            args.max_results,
            strict_lookback=True,
        )
    else:
        arxiv_ids = fetch_new_submission_ids()
        papers = fetch_papers_by_ids(arxiv_ids, categories)
        note = f"Using arXiv new-list batch with {len(arxiv_ids)} IDs."

    write_json(LATEST_PAPERS, papers)
    if note:
        print(note)
    print(f"FETCHED {len(papers)} papers")
    print(f"wrote: {relative_path(LATEST_PAPERS)}")
    return 0


def command_prepare(_: argparse.Namespace) -> int:
    if not LATEST_PAPERS.exists():
        raise ArxivNotesError(f"missing {relative_path(LATEST_PAPERS)}; run fetch first")
    papers = load_latest_papers()
    seen_ids = existing_arxiv_ids()
    new_papers = unseen_papers(papers, seen_ids)
    fingerprint = material_fingerprint(new_papers)
    previous = previous_fingerprint()

    if not new_papers or (previous and fingerprint == previous):
        print("NO_NEW_MATERIAL")
        return 0

    target = suggested_target_monthly_file(new_papers)
    generated_at = write_source_pack(new_papers, fingerprint, target)
    write_manifest(new_papers, fingerprint, target, generated_at)

    print("PREPARED_SOURCE_PACK")
    print(f"paper_count: {len(new_papers)}")
    print(f"fingerprint: {fingerprint}")
    print(f"suggested_target_monthly_file: {target}")
    print(f"source_pack: {relative_path(LATEST_SOURCE_PACK)}")
    print(f"manifest: {relative_path(LATEST_MANIFEST)}")
    return 0


def command_status(_: argparse.Namespace) -> int:
    papers = load_latest_papers()
    seen_ids = existing_arxiv_ids()
    already_seen_count = sum(
        1 for paper in papers if normalize_arxiv_id(paper.get("arxiv_id", "")) in seen_ids
    )
    new_papers = unseen_papers(papers, seen_ids)
    fingerprint = material_fingerprint(new_papers)
    previous = previous_fingerprint()
    should_run = bool(new_papers and fingerprint and fingerprint != previous)

    print(f"latest_fetch_papers: {len(papers)}")
    print(f"already_seen_papers: {already_seen_count}")
    print(f"new_papers: {len(new_papers)}")
    print(f"current_fingerprint: {fingerprint or 'NONE'}")
    print(f"previous_fingerprint: {previous or 'NONE'}")
    print(f"should_run_codex_analysis: {'yes' if should_run else 'no'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch = subparsers.add_parser("fetch", help="fetch recent arXiv astro-ph metadata")
    fetch.add_argument("--category", action="append", help="arXiv category to include")
    fetch.add_argument("--lookback-hours", type=float, default=DEFAULT_LOOKBACK_HOURS)
    fetch.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    fetch.add_argument(
        "--strict-lookback",
        action="store_true",
        help="use an Atom API submitted-date search instead of the arXiv new-list batch",
    )
    fetch.set_defaults(func=command_fetch)

    prepare = subparsers.add_parser("prepare", help="prepare source material for Codex")
    prepare.set_defaults(func=command_prepare)

    status = subparsers.add_parser("status", help="show deduplication status")
    status.set_defaults(func=command_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ArxivNotesError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
