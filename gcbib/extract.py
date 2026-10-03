"""Stage 3: footnotes -> citation rows.

Each footnote (numbered or inline) is tokenized, split into citation segments, and each
segment yields zero or more citations in one of three tiers:
    scripture   from <a class="scripture-ref"> links (book/chapter/verse parsed from the href)
    crossref    from <a class="cross-ref"> links to other talks, manuals, magazines, hymns
    freetext    everything else, parsed by grammar.parse_segment()
Segments that turn out to be explanatory prose are stored with tier='note' so they can be
audited but are excluded from counts.
"""
from __future__ import annotations

import datetime as dt
import html as htmlmod
import re
import sqlite3
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

from . import grammar
from .scripture import book_name_from_href, parse_scripture_href

A_RE = re.compile(r'<a\b([^>]*)>(.*?)</a>', re.S)
TAG_RE = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")
ABBREV = re.compile(r"(?:\b(?:pp?|vol|vols|no|nos|chap|ch|sec|ed|eds|comp|comps|trans|rev|sel|arr|adapt|illus|intro|pref|fwd|Jr|Sr|St|Dr|Mr|Mrs|Ms|Prof|Gen|Col|Capt|Lt|Sgt|Rev|Hon|Pres|Gov|Sen|Rep|Univ|Inst|Co|Corp|Inc|Ltd|Bros|Assn|Dept|Mo|Tenn|Tex|Mich|Minn|Mass|Calif|Colo|Conn|Fla|Ill|Ind|Kans|Ky|Md|Miss|Mont|Nebr|Nev|Okla|Oreg|Pa|Va|Wash|Wis|Wyo|Ala|Ariz|Ark|Del|Ga|La|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept|Sep|Oct|Nov|Dec|cf|e\.g|i\.e|etc|vs|v|bk|pt|ca|c|b|d|fl|Gen|Ex|Lev|Num|Deut|Josh|Judg|Sam|Kgs|Chr|Neh|Ps|Prov|Eccl|Isa|Jer|Lam|Ezek|Dan|Hos|Obad|Mic|Nah|Hab|Zeph|Hag|Zech|Mal|Matt|Rom|Cor|Gal|Eph|Philip|Col|Thes|Tim|Philem|Heb|Pet|Rev|Ne|Jac|Enos|Jar|Omni|W of M|Morm|Moro|Hel|Alma|Mosiah|Ether|D&C|Abr|JS|A of F)|\b[A-Z])\.$")


@dataclass
class Link:
    kind: str   # S | X | U
    href: str
    text: str


@dataclass
class Marked:
    text: str
    links: list[Link] = field(default_factory=list)


def tokenize(fragment: str) -> Marked:
    """Replace links with placeholders and <cite> with ⟪⟫; strip all other markup."""
    links: list[Link] = []

    def sub_a(m: re.Match) -> str:
        attrs, inner = m.group(1), m.group(2)
        cls = (re.search(r'class="([^"]*)"', attrs) or [None, ""])[1]
        href = htmlmod.unescape((re.search(r'href="([^"]*)"', attrs) or [None, ""])[1])
        kind = "S" if "scripture-ref" in cls else "X" if "cross-ref" in cls else "U"
        if kind == "U" and not href.startswith("http"):
            kind = "X"
        n = len(links)
        links.append(Link(kind, href, _plain(inner)))
        return f"⟦{kind}{n}⟧"

    t = fragment.replace("</p>", " ¶ ")
    t = A_RE.sub(sub_a, t)
    t = re.sub(r"<cite[^>]*>", "⟪", t)
    t = t.replace("</cite>", "⟫")
    t = TAG_RE.sub("", t)
    t = htmlmod.unescape(t).replace("\xa0", " ")
    t = t.replace("“", "“").replace("”", "”")
    t = WS.sub(" ", t).strip()
    return Marked(t, links)


def _plain(s: str) -> str:
    return WS.sub(" ", htmlmod.unescape(TAG_RE.sub("", s)).replace("\xa0", " ")).strip()


# ----------------------------------------------------------------------------- segmentation

def _split_top_level(s: str, sep: str) -> list[str]:
    """Split on sep when not inside “…”, (…), or ⟪…⟫."""
    out, depth_p, in_q, in_c, buf = [], 0, False, False, []
    for ch in s:
        if ch == "(":
            depth_p += 1
        elif ch == ")":
            depth_p = max(0, depth_p - 1)
        elif ch == "“":
            in_q = True
        elif ch == "”":
            in_q = False
        elif ch == "⟪":
            in_c = True
        elif ch == "⟫":
            in_c = False
        if ch == sep and depth_p == 0 and not in_q and not in_c:
            out.append("".join(buf)); buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def _split_sentences(s: str) -> list[str]:
    """Conservative sentence split: '. ' followed by an uppercase/placeholder/quote, not after an abbreviation."""
    parts, start = [], 0
    for m in re.finditer(r"\. (?=[A-Z“⟦⟪(])", s):
        before = s[start:m.start() + 1]
        if ABBREV.search(before.strip()):
            continue
        # don't split inside quotes/parens
        if before.count("“") != before.count("”") or before.count("(") != before.count(")"):
            continue
        parts.append(before.strip()); start = m.end()
    parts.append(s[start:].strip())
    return [p for p in parts if p]


CITE_SIGNAL = re.compile(r"⟦|⟪|“|\b(1[6-9]|20)\d\d\b|\bpp?\.\s?\d|\bno\.\s?\d|\bHymns\b|\bIbid\b", re.I)
# A parenthetical that is a whole citation (not just "(2000)" or "(2nd ed.)")
PAREN_CITATION = re.compile(r"⟦|⟪|“|\bsee\b|\bin\b|,", re.I)
BARE_PAREN = re.compile(r"^\s*(?:c\.|ca\.)?\s*(?:1[5-9]\d\d|20[0-2]\d)(?:\s*[–-]\s*\d{2,4})?\s*$|^[^,]*\bed\.\s*$|^\s*emphasis (?:added|in original)\s*$", re.I)
EDITORIAL = re.compile(r"^(?:emphasis (?:added|in original|mine)|punctuation (?:modernized|standardized|added)|spelling (?:modernized|standardized)|"
                       r"capitalization (?:modernized|standardized)|italics (?:added|in original|removed)|brackets? in original|"
                       r"paragraphing altered|paragraph divisions altered|line breaks altered|translation ours|author’s translation|"
                       r"my translation|punctuation and spelling (?:modernized|standardized)|spelling and punctuation (?:modernized|standardized)|"
                       r"spelling, punctuation, and capitalization (?:modernized|standardized)|emphasis added; punctuation modernized)\.?$", re.I)


def segments(marked: Marked) -> list[tuple[str, str]]:
    """Break a footnote into (citation segment, local context) pairs."""
    segs: list[tuple[str, str]] = []
    for para in marked.text.split("¶"):
        para = para.strip()
        if not para:
            continue
        parens = [m for m in re.finditer(r"\(([^()]{3,}?)\)", para)
                  if PAREN_CITATION.search(m.group(1)) and not BARE_PAREN.match(m.group(1)) and CITE_SIGNAL.search(m.group(1))]
        outside = re.sub(r"\([^()]*\)", "", para)
        outside_prose = len(re.sub(r"⟦[SXU]\d+⟧|[“”\s]", "", outside))
        if parens and (outside_prose > 40 or para.startswith("“")):
            # Prose (often a quotation) wrapping citations in parentheses: the parentheticals are the citations,
            # the prose is context ("President Holland taught: “…” (“Lord, I Believe,” Liahona, May 2013, 94).").
            ctx = _plain_marked(outside, marked)
            for m in parens:
                for piece in _split_top_level(m.group(1), ";"):
                    segs.append((piece, ctx))
            for ph in re.findall(r"⟦[SXU]\d+⟧", outside):
                segs.append((ph, ctx))
            continue
        for sent in _split_sentences(para):
            for piece in _split_top_level(sent, ";"):
                segs.append((piece, ""))
    # Post-process: drop editorial tails, fold "or Ensign, Nov. 2007, 107" alternates into nothing
    out: list[tuple[str, str]] = []
    for seg, ctx in segs:
        bare = re.sub(r"[\s.]+$", "", seg)
        if EDITORIAL.match(bare):
            continue
        if re.match(r"^or\s+(?:in\s+)?(?:⟪)?(?:Ensign|Liahona|Conference Report|Improvement Era|New Era|Tambuli|Friend)\b", seg, re.I):
            continue
        out.append((seg, ctx))
    return out


def _plain_marked(s: str, marked: Marked) -> str:
    def repl(m: re.Match) -> str:
        return marked.links[int(m.group(2))].text
    s = re.sub(r"⟦([SXU])(\d+)⟧", repl, s)
    return re.sub(r"\s+", " ", s.replace("⟪", "").replace("⟫", "")).strip()


# ----------------------------------------------------------------------------- href interpretation

def classify_crossref(href: str, text: str) -> dict:
    """Interpret a Gospel Library href. Returns dict with work_type, container_title, cited_talk_uri, work_title_hint."""
    path = urlparse(href).path
    path = re.sub(r"^/study", "", path)
    parts = [p for p in path.split("/") if p]
    out: dict = {"work_type": "other", "container_title": None, "cited_talk_uri": None, "work_title_hint": None}
    if not parts:
        return out
    head = parts[0]
    if head == "general-conference" and len(parts) >= 4:
        out.update(work_type="talk", cited_talk_uri="/" + "/".join(parts[:4]), container_title="General Conference")
    elif head == "general-conference":
        out.update(work_type="talk", container_title="General Conference")
    elif head in ("ensign", "liahona", "new-era", "friend", "tambuli", "ya-weekly", "yw-weekly"):
        out.update(work_type="article", container_title={"new-era": "New Era"}.get(head, head.capitalize()))
    elif head == "manual":
        slug = parts[1] if len(parts) > 1 else ""
        if slug.startswith("hymns") or slug in ("childrens-songbook",):
            out.update(work_type="hymn", container_title="Hymns" if slug.startswith("hymns") else "Children's Songbook")
        else:
            out.update(work_type="manual", work_title_hint=_humanize(slug))
    elif head == "music":
        out.update(work_type="hymn", container_title="Hymns")
    elif head == "scriptures":
        sub = parts[1] if len(parts) > 1 else ""
        names = {"bd": "Bible Dictionary", "gs": "Guide to the Scriptures", "tg": "Topical Guide", "jst": "Joseph Smith Translation",
                 "harmony": "Harmony of the Gospels", "jst-appendix": "Joseph Smith Translation Appendix"}
        if sub in names:
            out.update(work_type="study_help", container_title=names[sub])
        else:
            out.update(work_type="scripture")
    elif head == "history":
        sub = parts[1] if len(parts) > 1 else ""
        out.update(work_type="book", work_title_hint={"saints-v1": "Saints, Volume 1", "saints-v2": "Saints, Volume 2",
                                                       "saints-v3": "Saints, Volume 3", "saints-v4": "Saints, Volume 4",
                                                       "topics": "Church History Topics", "joseph-smith-papers": "The Joseph Smith Papers"}.get(sub, _humanize(sub)))
    elif head in ("broadcasts", "devotionals", "video", "media"):
        out.update(work_type="speech")
    elif head == "books":
        out.update(work_type="book", work_title_hint=_humanize(parts[1]) if len(parts) > 1 else None)
    return out


def _humanize(slug: str) -> str:
    slug = re.sub(r"-\d{4}$", "", slug)
    return " ".join(w.capitalize() if w not in ("of", "the", "and", "in", "to", "for", "a") else w for w in slug.split("-")).strip()


# ----------------------------------------------------------------------------- main

@dataclass
class Cit:
    tier: str
    relation: str = "quoted"
    raw_text: str = ""
    author_name: str | None = None
    person_quoted: str | None = None
    work_title: str | None = None
    work_type: str | None = None
    container_title: str | None = None
    locator: str | None = None
    year: int | None = None
    cited_talk_uri: str | None = None
    href: str | None = None
    scripture_book: str | None = None
    chapter: int | None = None
    verse_start: int | None = None
    verse_end: int | None = None
    parser: str = "rules"
    confidence: float = 1.0


def extract_footnote(raw_html: str, context: str, memory: list[Cit]) -> list[Cit]:
    marked = tokenize(raw_html)
    out: list[Cit] = []
    for seg, local_ctx in segments(marked):
        ctx = (context + " " + local_ctx).strip() if local_ctx else context
        out.extend(_extract_segment(seg, marked, ctx, memory + out, local_ctx))
    return out


GLUE = re.compile(r"^(?:see also|see|also|and|or|cf\.|compare|in|from|[\s,;.:()–—-])+$", re.I)


def _extract_segment(seg: str, marked: Marked, context: str, memory: list[Cit], local_ctx: str = "") -> list[Cit]:
    cits: list[Cit] = []
    lead = grammar.SEE_RE.match(seg)
    relation = "see" if lead and lead.group(1).lower().startswith(("see", "cf", "compare", "also")) else "quoted"
    placeholders = [(m.group(1), int(m.group(2))) for m in re.finditer(r"⟦([SXU])(\d+)⟧", seg)]

    # Tier 1: scripture links
    for kind, idx in placeholders:
        if kind != "S":
            continue
        link = marked.links[idx]
        ref = parse_scripture_href(link.href)
        cits.append(Cit(tier="scripture", relation=relation, raw_text=link.text, href=link.href,
                        work_type="scripture", scripture_book=ref.get("book") or book_name_from_href(link.href, link.text),
                        chapter=ref.get("chapter"), verse_start=ref.get("verse_start"), verse_end=ref.get("verse_end"),
                        work_title=ref.get("book") or book_name_from_href(link.href, link.text), parser="href"))

    # What remains after scripture links?
    residue = re.sub(r"⟦S\d+⟧", "", seg)
    residue_clean = grammar.QUOTE_RE.sub(lambda m: m.group(0), residue)
    if GLUE.match(re.sub(r"⟦[XU]\d+⟧", "", residue_clean) or ""):
        if not any(k in ("X", "U") for k, _ in placeholders):
            return cits

    known = frozenset(n.split()[-1].lower().strip(".,") for c in memory for n in (c.author_name, c.person_quoted) if n and len(n.split()) > 1)
    parsed = grammar.parse_segment(residue, context, known_surnames=known)
    xs = [(k, i) for k, i in placeholders if k in ("X", "U")]

    # "in Conference Report, Apr. 1935, 116" after another citation in the same footnote is its location, not a new citation
    if not xs and re.match(r"^(?:in|or in|or)\s+(?:Conference Report|Ensign|Liahona|Improvement Era|New Era|Tambuli)\b", seg.strip(), re.I):
        prev = next((c for c in reversed(memory) if c.tier in ("freetext", "crossref")), None)
        if prev is not None and prev.container_title is None:
            prev.container_title = parsed.container_title
            prev.locator = prev.locator or parsed.locator
        return cits

    if xs:
        # Tier 2: one citation per cross-ref link, enriched by the grammar parse of the whole segment
        for kind, idx in xs:
            link = marked.links[idx]
            info = classify_crossref(link.href, link.text) if kind == "X" else {"work_type": "web", "container_title": None, "cited_talk_uri": None, "work_title_hint": None}
            c = Cit(tier="crossref", relation=parsed.relation if parsed.relation != "quoted" else relation,
                    raw_text=_segment_plain(seg, marked), href=link.href,
                    author_name=parsed.author, person_quoted=parsed.person_quoted,
                    work_title=(link.text if info["work_type"] in ("talk", "article", "hymn", "speech", "web") and re.search(r"[A-Za-z]{3,}", link.text) else parsed.work_title or info["work_title_hint"] or link.text),
                    work_type=info["work_type"] if info["work_type"] != "other" else (parsed.work_type or "other"),
                    container_title=parsed.container_title or info["container_title"],
                    locator=parsed.locator or (link.text if info["work_type"] in ("manual", "study_help") else None),
                    year=parsed.year, cited_talk_uri=info["cited_talk_uri"], parser="href+rules",
                    confidence=max(0.6, parsed.confidence))
            if info["work_type"] == "talk" and info["cited_talk_uri"]:
                m = re.match(r"/general-conference/(\d{4})/(\d{2})", info["cited_talk_uri"])
                if m and not c.year:
                    c.year = int(m.group(1))
                if c.work_title and c.work_title == parsed.work_title and link.text and link.text != parsed.work_title and parsed.work_title not in link.text:
                    pass
                if not c.work_title:
                    c.work_title = link.text
            if info["work_type"] == "manual" and not parsed.work_title:
                c.work_title = info["work_title_hint"]
            if c.work_title and re.fullmatch(r"[\d\s,–\-:]+", c.work_title):
                c.locator = c.locator or c.work_title
                c.work_title = None
            if info["work_type"] in ("manual", "study_help") and re.search(r"[A-Za-z]{3,}", link.text) and len(link.text) > 12:
                c.work_title = parsed.work_title or link.text
                c.locator = parsed.locator
                m4 = re.match(r"^Teachings of Presidents of the Church:\s*(.+)$", link.text, re.I)
                if m4:
                    c.person_quoted = c.person_quoted or grammar.clean_name(m4.group(1))
            if info["work_type"] in ("talk", "article", "speech") and local_ctx and not c.person_quoted:
                c.person_quoted = grammar.attribution_from_context(local_ctx, window=0)
            cits.append(c)
        return _resolve_short_forms(cits, memory)

    # Tier 3: free text
    if parsed.work_title == "__IBID__":
        prev = next((c for c in reversed(memory) if c.tier in ("freetext", "crossref")), None)
        if prev:
            c = Cit(tier=prev.tier, relation=relation, raw_text=_segment_plain(seg, marked), author_name=prev.author_name,
                    person_quoted=prev.person_quoted, work_title=prev.work_title, work_type=prev.work_type,
                    container_title=prev.container_title, locator=parsed.locator, year=prev.year,
                    cited_talk_uri=prev.cited_talk_uri, href=prev.href, parser="ibid", confidence=0.7)
            cits.append(c)
        return cits

    c = Cit(tier="freetext" if parsed.is_citation else "note", relation=parsed.relation if parsed.relation != "quoted" else relation,
            raw_text=_segment_plain(seg, marked), author_name=parsed.author, person_quoted=parsed.person_quoted,
            work_title=parsed.work_title, work_type=parsed.work_type, container_title=parsed.container_title,
            locator=parsed.locator, year=parsed.year, parser="rules", confidence=parsed.confidence)
    if c.tier == "note" and cits:
        return cits          # scripture + trailing commentary: keep only the scripture
    cits.append(c)
    return _resolve_short_forms(cits, memory)


def _segment_plain(seg: str, marked: Marked) -> str:
    def repl(m: re.Match) -> str:
        return marked.links[int(m.group(2))].text
    s = re.sub(r"⟦([SXU])(\d+)⟧", repl, seg)
    return s.replace("⟪", "").replace("⟫", "").strip()


def _resolve_short_forms(cits: list[Cit], memory: list[Cit]) -> list[Cit]:
    """Fill 'Lewis, Mere Christianity, 12' and 'Discourses, 46' from fuller citations earlier in the same talk."""
    for c in cits:
        if c.tier not in ("freetext", "crossref"):
            continue
        name = c.author_name or c.person_quoted
        if name and len(name.split()) == 1:
            surname = name.lower()
            for prev in reversed(memory):
                for full in (prev.author_name, prev.person_quoted):
                    if full and len(full.split()) > 1 and full.split()[-1].lower().strip(",.") == surname:
                        if c.author_name == name:
                            c.author_name = full
                        if c.person_quoted == name:
                            c.person_quoted = full
                        break
                else:
                    continue
                break
        if c.work_title and not c.author_name and not c.person_quoted and c.work_type in ("book", "manual", None):
            key = c.work_title.lower()
            for prev in reversed(memory):
                if prev.work_title and prev.work_title.lower() != key and prev.work_title.lower().startswith(key):
                    c.work_title = prev.work_title; c.author_name = prev.author_name
                    c.person_quoted = c.person_quoted or prev.person_quoted; c.work_type = prev.work_type
                    c.parser += "+shortform"
                    break
        if c.work_title and len(c.work_title.split()) <= 3 and not c.author_name:
            for prev in reversed(memory):
                if prev.work_title and prev.work_title.lower() == c.work_title.lower() and prev.author_name:
                    c.author_name = prev.author_name; c.person_quoted = c.person_quoted or prev.person_quoted
                    c.work_type = c.work_type or prev.work_type
                    break
    return cits


def extract_talk(con: sqlite3.Connection, talk_id: int) -> int:
    cur = con.cursor()
    cur.execute("DELETE FROM citations WHERE talk_id=?", (talk_id,))
    rows = cur.execute("SELECT id, raw_html, context FROM footnotes WHERE talk_id=? ORDER BY inline, ord", (talk_id,)).fetchall()
    memory: list[Cit] = []
    n = 0
    for fn in rows:
        cits = extract_footnote(fn["raw_html"], fn["context"] or "", memory)
        for pos, c in enumerate(cits):
            cur.execute("""INSERT INTO citations(footnote_id, talk_id, position, tier, relation, raw_text, author_name, person_quoted,
                           work_title, work_type, container_title, locator, year, cited_talk_uri, href, scripture_book, chapter,
                           verse_start, verse_end, parser, confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (fn["id"], talk_id, pos, c.tier, c.relation, c.raw_text[:1000], c.author_name, c.person_quoted, c.work_title,
                         c.work_type, c.container_title, c.locator, c.year, c.cited_talk_uri, c.href, c.scripture_book, c.chapter,
                         c.verse_start, c.verse_end, c.parser, c.confidence))
            n += 1
        memory.extend(cits)
    cur.execute("UPDATE talks SET extracted_at=? WHERE id=?", (dt.datetime.now().isoformat(timespec="seconds"), talk_id))
    con.commit()
    return n


def extract_many(con: sqlite3.Connection, talk_ids: list[int], log=print) -> int:
    total = 0
    for i, tid in enumerate(talk_ids, 1):
        total += extract_talk(con, tid)
        if i % 100 == 0:
            log(f"  extracted {i}/{len(talk_ids)} talks, {total} citations")
    from .parse import update_coverage
    update_coverage(con)
    return total
