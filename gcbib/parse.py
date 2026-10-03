"""Stage 2: raw talk JSON -> conferences, sessions, talks, paragraphs, footnotes.

Footnotes come from two places:
  * content.footnotes (1996+ numbered notes), stored with inline=0
  * parenthetical citations inside body paragraphs (the 1971-1995 style, still used
    occasionally today), stored with inline=1 and marker "i<pid>.<n>"
Both are later fed to the same citation extractor.
"""
from __future__ import annotations

import datetime as dt
import html as htmlmod
import json
import re
import sqlite3

from bs4 import BeautifulSoup, NavigableString, Tag

from .crawl import TalkRef, get_talk
from .selectors import is_talk

# Signals that a parenthetical group is a citation rather than prose.
CITE_SIGNAL = re.compile(
    r'class="scripture-ref"|<cite>|“|&#8220;|\b(1[6-9]|20)\d\d\b|\bpp?\.\s?\d|\bno\.\s?\d|\bvol\.|'
    r'\bHymns\b|\bJournal of Discourses\b|\bConference Report\b|\bEnsign\b|\bLiahona\b|\bIbid\b|'
    r'\b(act|scene|line|chapter|ch\.|sec\.)\s?\d',
    re.I,
)
PAREN = re.compile(r"\(([^()]{3,}?)\)")
WS = re.compile(r"\s+")


def plain(fragment: str) -> str:
    """HTML fragment -> normalized plain text."""
    t = re.sub(r"<[^>]+>", "", fragment)
    t = htmlmod.unescape(t).replace("\xa0", " ")
    return WS.sub(" ", t).strip()


def _speaker_role(soup: BeautifulSoup) -> str | None:
    el = soup.select_one("p.author-role")
    return plain(str(el)) if el else None


def _speaker_name_from_body(soup: BeautifulSoup) -> str | None:
    el = soup.select_one("p.author-name")
    if not el:
        return None
    name = plain(str(el))
    return re.sub(r"^(by|presented by)\s+", "", name, flags=re.I)


def _date(meta: dict) -> str | None:
    sd = meta.get("structuredData")
    if sd:
        try:
            d = json.loads(sd)
            dp = d.get("datePublished")
            if dp:
                return dp[:10]
        except Exception:  # noqa: BLE001
            pass
    return None


def _body_paragraphs(soup: BeautifulSoup) -> list[Tag]:
    """Paragraph-ish elements in reading order, excluding the notes footer and byline."""
    for footer in soup.select("footer.notes"):
        footer.decompose()
    out = []
    for el in soup.find_all(["p", "h1", "h2", "h3", "li"]):
        cls = " ".join(el.get("class", []))
        if any(k in cls for k in ("author-name", "author-role", "kicker", "title", "marker")):
            # kicker/title are kept only when they are not footnote chrome
            if "kicker" not in cls:
                continue
        if el.find_parent("footer"):
            continue
        if el.name == "li" and el.find("p"):
            continue
        out.append(el)
    return out


def _note_marker_positions(p_html: str) -> list[tuple[str, int]]:
    """[(note_id, char_offset_in_plain_text_before_marker), ...] for note-ref anchors in a paragraph."""
    out = []
    pos = 0
    for m in re.finditer(r'<a class="note-ref" href="#(note\d+)">.*?</a>|<[^>]+>|[^<]+', p_html):
        s = m.group(0)
        if m.group(1):
            out.append((m.group(1), pos))
        elif not s.startswith("<"):
            pos += len(plain(s)) + (1 if s.endswith(" ") else 0)
    return out


def _context_before(p_text: str, offset: int, width: int = 280) -> str:
    return p_text[max(0, offset - width):offset].strip()


def _inline_groups(p_html: str) -> list[tuple[str, str]]:
    """Return [(raw_html_fragment, context_before)] for citation-like parentheticals
    and for standalone scripture links in a body paragraph."""
    groups: list[tuple[str, str]] = []
    covered: list[tuple[int, int]] = []
    for m in PAREN.finditer(p_html):
        inner = m.group(1)
        if CITE_SIGNAL.search(inner):
            groups.append((inner, plain(p_html[:m.start()])[-280:]))
            covered.append((m.start(), m.end()))
    for m in re.finditer(r'<a class="scripture-ref"[^>]*>.*?</a>', p_html):
        if any(a <= m.start() < b for a, b in covered):
            continue
        groups.append((m.group(0), plain(p_html[:m.start()])[-280:]))
    return groups


def parse_talk(con: sqlite3.Connection, ref: TalkRef, raw: dict | None = None) -> int:
    raw = raw or get_talk(ref)
    meta = raw.get("meta", {})
    content = raw.get("content", {})
    body_html = content.get("body", "") or ""
    soup = BeautifulSoup(body_html, "lxml")

    cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO conferences(year, month, title) VALUES (?,?,?)",
                (ref.year, ref.month, f"{'April' if ref.month == 4 else 'October'} {ref.year} general conference"))
    conf_id = cur.execute("SELECT id FROM conferences WHERE year=? AND month=?", (ref.year, ref.month)).fetchone()[0]
    cur.execute("INSERT OR IGNORE INTO sessions(conference_id, title, uri, ord) VALUES (?,?,?,?)",
                (conf_id, ref.session, ref.session_uri, ref.session_order))
    sess_id = cur.execute("SELECT id FROM sessions WHERE conference_id=? AND title=?", (conf_id, ref.session)).fetchone()[0]

    speaker = ref.speaker or _speaker_name_from_body(soup) or ""
    cur.execute("""INSERT INTO talks(uri, conference_id, session_id, ord, title, speaker_name, speaker_role, date, is_talk, parsed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(uri) DO UPDATE SET conference_id=excluded.conference_id, session_id=excluded.session_id,
                     ord=excluded.ord, title=excluded.title, speaker_name=excluded.speaker_name, speaker_role=excluded.speaker_role,
                     date=excluded.date, is_talk=excluded.is_talk, parsed_at=excluded.parsed_at, extracted_at=NULL""",
                (ref.uri, conf_id, sess_id, ref.order, meta.get("title") or ref.title, speaker,
                 _speaker_role(soup), _date(meta), int(is_talk(ref)), dt.datetime.now().isoformat(timespec="seconds")))
    talk_id = cur.execute("SELECT id FROM talks WHERE uri=?", (ref.uri,)).fetchone()[0]
    cur.execute("DELETE FROM citations WHERE talk_id=?", (talk_id,))
    cur.execute("DELETE FROM footnotes WHERE talk_id=?", (talk_id,))
    cur.execute("DELETE FROM paragraphs WHERE talk_id=?", (talk_id,))

    # Paragraphs (body only) + map pid -> (text, html)
    para_by_pid: dict[str, tuple[str, str]] = {}
    rows = []
    for i, el in enumerate(_body_paragraphs(soup)):
        pid = el.get("data-aid") or el.get("id") or f"x{i}"
        p_html = str(el)
        text = plain(p_html)
        if not text:
            continue
        para_by_pid[pid] = (text, p_html)
        if el.get("id"):
            para_by_pid.setdefault(el["id"], (text, p_html))
        rows.append((talk_id, pid, i, text))
    cur.executemany("INSERT OR IGNORE INTO paragraphs(talk_id, pid, ord, text) VALUES (?,?,?,?)", rows)

    # Numbered footnotes
    fn_rows = []
    marker_ctx: dict[str, str] = {}
    for pid, (text, p_html) in para_by_pid.items():
        for note_id, off in _note_marker_positions(p_html):
            marker_ctx[note_id] = _context_before(text, off)
    footnotes = content.get("footnotes") or {}
    for ord_, (note_id, fn) in enumerate(footnotes.items()):
        raw_html = fn.get("text", "") or ""
        fn_rows.append((talk_id, note_id, ord_, fn.get("pid"), raw_html, plain(raw_html),
                        marker_ctx.get(note_id) or fn.get("context") or "", 0))

    # Inline parenthetical / standalone scripture citations in the body.
    # A citation that opens its paragraph (an epigraph's source line) takes the previous paragraph as context.
    n_inline = 0
    prev_text = ""
    for (_tid, pid, _ord, text) in rows:
        p_html = para_by_pid[pid][1]
        for k, (frag, ctx) in enumerate(_inline_groups(p_html)):
            n_inline += 1
            fn_rows.append((talk_id, f"i{pid}.{k}", 10000 + n_inline, pid, frag, plain(frag), ctx or prev_text[-280:], 1))
        prev_text = text

    cur.executemany("""INSERT OR IGNORE INTO footnotes(talk_id, marker, ord, pid, raw_html, text, context, inline)
                       VALUES (?,?,?,?,?,?,?,?)""", fn_rows)
    con.commit()
    return talk_id


def parse_many(con: sqlite3.Connection, refs: list[TalkRef], log=print) -> int:
    n = 0
    for i, ref in enumerate(refs, 1):
        if not ref.raw_path.exists():
            log(f"  skip (not crawled): {ref.uri}")
            continue
        parse_talk(con, ref)
        n += 1
        if i % 100 == 0:
            log(f"  parsed {i}/{len(refs)}")
    update_coverage(con)
    return n


def update_coverage(con: sqlite3.Connection) -> None:
    con.execute("""
        INSERT INTO coverage(conference_id, talks_total, talks_parsed, talks_extracted, updated_at)
        SELECT c.id, COUNT(t.id), SUM(t.parsed_at IS NOT NULL), SUM(t.extracted_at IS NOT NULL), ?
        FROM conferences c LEFT JOIN talks t ON t.conference_id=c.id AND t.is_talk=1
        GROUP BY c.id
        ON CONFLICT(conference_id) DO UPDATE SET talks_total=excluded.talks_total, talks_parsed=excluded.talks_parsed,
            talks_extracted=excluded.talks_extracted, updated_at=excluded.updated_at
    """, (dt.datetime.now().isoformat(timespec="seconds"),))
    con.commit()
