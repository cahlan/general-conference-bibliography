"""Stage 1: fetch conference tables of contents and talk content from the
Gospel Library JSON API and cache them on disk under raw/.

Layout:
    raw/2026-04/toc.json
    raw/2026-04/13kearon.json
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import requests

BASE = "https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/"
HEADERS = {"User-Agent": "Mozilla/5.0 (gcbib research crawler; personal use)"}
RAW_DIR = Path(__file__).resolve().parent.parent / "raw"
FIRST_YEAR = 1971

_session = requests.Session()
_session.headers.update(HEADERS)


class NotFound(Exception):
    pass


def _fetch(kind: str, uri: str, retries: int = 3) -> dict:
    url = f"{BASE}{kind}?lang=eng&uri={uri}"
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = _session.get(url, timeout=30)
            if r.status_code == 404:
                raise NotFound(uri)
            r.raise_for_status()
            # The API emits a few raw control characters inside strings.
            data = json.loads(r.text, strict=False)
            if isinstance(data, dict) and data.get("statusCode") == 404:
                raise NotFound(uri)
            return data
        except NotFound:
            raise
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def conf_dir(year: int, month: int) -> Path:
    return RAW_DIR / f"{year}-{month:02d}"


def conf_uri(year: int, month: int) -> str:
    return f"/general-conference/{year}/{month:02d}"


def get_toc(year: int, month: int, refresh: bool = False) -> dict | None:
    """Return the cached TOC for a conference, fetching it if needed.
    Returns None when the conference does not exist (yet)."""
    path = conf_dir(year, month) / "toc.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    try:
        data = _fetch("toc", conf_uri(year, month))
    except NotFound:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


@dataclass
class TalkRef:
    year: int
    month: int
    uri: str          # /general-conference/2026/04/13kearon
    slug: str         # 13kearon
    title: str
    speaker: str
    session: str
    session_uri: str
    session_order: int
    order: int        # order within the session

    @property
    def raw_path(self) -> Path:
        return conf_dir(self.year, self.month) / f"{self.slug}.json"

    @property
    def conference(self) -> tuple[int, int]:
        return (self.year, self.month)


def toc_talks(year: int, month: int, toc: dict) -> list[TalkRef]:
    out: list[TalkRef] = []
    s_order = 0
    for entry in toc.get("entries", []):
        section = entry.get("section")
        if not section:
            continue
        s_order += 1
        for i, item in enumerate(section.get("entries", [])):
            c = item.get("content")
            if not c:
                continue
            uri = c["uri"].replace("/study", "", 1)
            out.append(TalkRef(
                year=year, month=month, uri=uri, slug=uri.rsplit("/", 1)[-1],
                title=c.get("title", ""), speaker=c.get("subtitle", "") or "",
                session=section.get("title", ""), session_uri=section.get("uri", ""),
                session_order=s_order, order=i + 1,
            ))
    return out


def get_talk(ref: TalkRef, refresh: bool = False) -> dict:
    if ref.raw_path.exists() and not refresh:
        return json.loads(ref.raw_path.read_text())
    data = _fetch("content", ref.uri)
    ref.raw_path.parent.mkdir(parents=True, exist_ok=True)
    ref.raw_path.write_text(json.dumps(data))
    return data


def crawl(refs: list[TalkRef], refresh: bool = False, workers: int = 4, log=print) -> int:
    """Fetch every talk in refs that is not already cached. Returns count fetched."""
    todo = [r for r in refs if refresh or not r.raw_path.exists()]
    log(f"crawl: {len(refs)} talks in scope, {len(todo)} to fetch")
    fetched = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(get_talk, r, refresh): r for r in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            r = futs[fut]
            try:
                fut.result()
                fetched += 1
            except Exception as e:  # noqa: BLE001
                log(f"  ERROR {r.uri}: {e}")
            if n % 50 == 0:
                log(f"  {n}/{len(todo)}")
    return fetched
