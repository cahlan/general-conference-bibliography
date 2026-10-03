"""Turn a scope selector into a concrete list of talks.

Selector grammar (positional argument to every command):
    all                  every conference from 1971 to the present
    2026                 both conferences of one year
    2019..2026           a range of years (inclusive)
    2026/04              one conference
    2026/04/13kearon     one talk
Filters:
    --session TEXT       session title contains TEXT (case-insensitive; '-' matches space)
    --speaker TEXT       speaker name contains TEXT (case-insensitive)
    --include-non-talks  keep sustainings, audit and statistical reports
"""
from __future__ import annotations

import datetime as dt
import re

from .crawl import FIRST_YEAR, TalkRef, get_toc, toc_talks

NON_TALK_TITLE = re.compile(
    r"^(the )?(solemn assembly( and)? )?sustaining (of|a new|the)|"
    r"^statistical report|^(the )?(church )?audit(ing)? (committee|department )?report|^audit report|"
    r"^church (audit|auditing|finance)|^(the )?solemn assembly$|^presentation of|"
    r"^revelation on priesthood accepted|^video:|\[video presentation\]|annual report of the church|"
    r"^statistical and financial report|^financial report",
    re.I,
)


def is_talk(ref: TalkRef) -> bool:
    if not ref.speaker.strip():
        return False
    return not NON_TALK_TITLE.search(ref.title.strip())


def _year_months(selector: str) -> tuple[list[tuple[int, int]], str | None]:
    """Return ([(year, month), ...], talk_slug_or_None)."""
    today = dt.date.today()
    s = selector.strip().strip("/")
    if s in ("all", "*", ""):
        years = range(FIRST_YEAR, today.year + 1)
        return [(y, m) for y in years for m in (4, 10)], None
    m = re.fullmatch(r"(\d{4})\.\.(\d{4})", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return [(y, mo) for y in range(a, b + 1) for mo in (4, 10)], None
    m = re.fullmatch(r"(\d{4})", s)
    if m:
        y = int(m.group(1))
        return [(y, 4), (y, 10)], None
    m = re.fullmatch(r"(\d{4})/(\d{1,2})", s)
    if m:
        return [(int(m.group(1)), int(m.group(2)))], None
    m = re.fullmatch(r"(\d{4})/(\d{1,2})/([^/]+)", s)
    if m:
        return [(int(m.group(1)), int(m.group(2)))], m.group(3)
    m = re.fullmatch(r"(?:https?://[^/]+)?(?:/study)?/general-conference/(\d{4})/(\d{2})/([^/?]+).*", s)
    if m:
        return [(int(m.group(1)), int(m.group(2)))], m.group(3)
    raise SystemExit(f"unrecognized selector: {selector!r}")


def select(selector: str, session: str | None = None, speaker: str | None = None,
           include_non_talks: bool = False, refresh_toc: bool = False, log=print) -> list[TalkRef]:
    yms, slug = _year_months(selector)
    refs: list[TalkRef] = []
    for y, mo in yms:
        toc = get_toc(y, mo, refresh=refresh_toc)
        if toc is None:
            if slug or len(yms) <= 2:
                log(f"  no conference found for {y}/{mo:02d}")
            continue
        refs.extend(toc_talks(y, mo, toc))
    if slug:
        refs = [r for r in refs if r.slug == slug]
        if not refs:
            raise SystemExit(f"talk {slug!r} not found in {selector}")
    if session:
        key = session.lower().replace("-", " ")
        refs = [r for r in refs if key in r.session.lower()]
    if speaker:
        key = speaker.lower()
        refs = [r for r in refs if key in r.speaker.lower()]
    if not include_non_talks:
        refs = [r for r in refs if is_talk(r)]
    return refs
