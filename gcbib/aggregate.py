"""Stage 5: SQLite -> two static JSON files for the dashboard (site/data/).

index.json       summaries: totals, coverage, conferences, talks, persons, works, speakers, scripture
citations.json   every counted (non-scripture) citation, compact, so pages can build detail views client-side

Two files instead of thousands so the dashboard can also be published as a claude.ai Artifact.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path

from .scripture import VOLUME_OF_BOOK

NON_COUNTED = ("scripture", "note")


def decade(year: int) -> str:
    return f"{year // 10 * 10}s"


def build_site_data(con: sqlite3.Connection, out: Path, log=print) -> None:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cur = con.cursor()

    confs = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM conferences ORDER BY year, month")}
    for c in confs.values():
        c["key"] = f"{c['year']}-{c['month']:02d}"
    sessions = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM sessions")}
    talks = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM talks WHERE is_talk=1")}
    for t in talks.values():
        t["conf"] = confs[t["conference_id"]]["key"]
        t["year"] = confs[t["conference_id"]]["year"]
        s = sessions.get(t["session_id"])
        t["session"] = s["title"] if s else ""
        t["session_ord"] = (s["ord"] if s else 0) or 0
    authors = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM authors")}
    works = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM works")}
    coverage = {r["conference_id"]: dict(r) for r in cur.execute("SELECT * FROM coverage")}

    log("aggregate: loading citations")
    cits = [dict(r) for r in cur.execute("""SELECT c.*, f.context FROM citations c JOIN footnotes f ON f.id=c.footnote_id
                                             JOIN talks t ON t.id=c.talk_id WHERE t.is_talk=1 ORDER BY c.talk_id, c.footnote_id, c.position""")]
    counted = [c for c in cits if c["tier"] not in NON_COUNTED]
    scripture = [c for c in cits if c["tier"] == "scripture"]
    kind_of = {aid: a["kind"] for aid, a in authors.items()}

    # ------------------------------------------------------------- citations.json (compact)
    log("aggregate: citations.json")
    compact = []
    for c in counted:
        w = works.get(c["work_id"]) if c["work_id"] else None
        compact.append({
            "t": c["talk_id"], "p": c["person_quoted_id"], "a": c["author_id"], "w": c["work_id"], "c": c["container_work_id"],
            "r": c["relation"], "k": c["tier"], "y": c["year"], "l": c["locator"], "wt": c["work_type"],
            "x": (c["raw_text"] or "")[:600], "cx": (c["context"] or "")[-240:], "cf": round(c["confidence"] or 0, 2),
            "u": c["cited_talk_uri"], "pn": c["person_quoted"] if not c["person_quoted_id"] else None,
            "wn": (c["work_title"] or c["container_title"]) if not w else None,
        })
    (out / "citations.json").write_text(json.dumps(compact, ensure_ascii=False, separators=(",", ":")))

    # ------------------------------------------------------------- persons
    log("aggregate: persons")
    by_person: dict[int, list[dict]] = collections.defaultdict(list)
    for c in counted:
        if c["person_quoted_id"]:
            by_person[c["person_quoted_id"]].append(c)
    persons_index = []
    for aid, lst in by_person.items():
        a = authors[aid]
        rel = collections.Counter(c["relation"] for c in lst)
        persons_index.append({"id": aid, "name": a["canonical_name"], "kind": a["kind"], "total": len(lst),
                              "quoted": rel.get("quoted", 0) + rel.get("secondary", 0), "see": rel.get("see", 0),
                              "talks": len({c["talk_id"] for c in lst}), "works": len({c["work_id"] for c in lst if c["work_id"]}),
                              "by_decade": dict(collections.Counter(decade(talks[c["talk_id"]]["year"]) for c in lst)),
                              "first_year": min(talks[c["talk_id"]]["year"] for c in lst),
                              "last_year": max(talks[c["talk_id"]]["year"] for c in lst),
                              "aliases": [r[0] for r in cur.execute("SELECT alias FROM author_aliases WHERE author_id=?", (aid,))][:8]})
    persons_index.sort(key=lambda x: -x["total"])

    speakers = collections.Counter(t["speaker_id"] for t in talks.values() if t["speaker_id"])
    speakers_index = sorted([{"id": sid, "name": authors[sid]["canonical_name"], "talks": n}
                             for sid, n in speakers.items() if sid in authors], key=lambda x: -x["talks"])

    # ------------------------------------------------------------- works
    log("aggregate: works")
    by_work: dict[int, list[dict]] = collections.defaultdict(list)
    for c in counted:
        if c["work_id"]:
            by_work[c["work_id"]].append(c)
    works_index = []
    for wid, lst in by_work.items():
        w = works[wid]
        author = authors.get(w["author_id"]) if w["author_id"] else None
        works_index.append({"id": wid, "title": w["canonical_title"], "type": w["work_type"], "author_id": w["author_id"],
                            "author": author["canonical_name"] if author else None, "total": len(lst),
                            "talks": len({c["talk_id"] for c in lst}),
                            "by_decade": dict(collections.Counter(decade(talks[c["talk_id"]]["year"]) for c in lst)),
                            "cited_talk_uri": w["cited_talk_uri"],
                            "aliases": [r[0] for r in cur.execute("SELECT alias FROM work_aliases WHERE work_id=?", (wid,))][:6]})
    works_index.sort(key=lambda x: -x["total"])
    # containers that are never a "work" themselves still need a name for the UI
    container_names = {wid: works[wid]["canonical_title"] for wid in {c["container_work_id"] for c in counted if c["container_work_id"]} if wid in works}

    # ------------------------------------------------------------- scripture
    log("aggregate: scripture")
    books = collections.defaultdict(list)
    for c in scripture:
        books[c["scripture_book"] or "?"].append(c)
    scripture_index = []
    for book, lst in books.items():
        chapters = collections.Counter(f"{book} {c['chapter']}" for c in lst if c["chapter"])
        verses = collections.Counter(f"{book} {c['chapter']}:{c['verse_start']}" + (f"–{c['verse_end']}" if c["verse_end"] and c["verse_end"] != c["verse_start"] else "")
                                     for c in lst if c["chapter"] and c["verse_start"])
        scripture_index.append({"book": book, "volume": VOLUME_OF_BOOK.get(book, "Other"), "total": len(lst),
                                "talks": len({c["talk_id"] for c in lst}),
                                "by_decade": dict(collections.Counter(decade(talks[c["talk_id"]]["year"]) for c in lst)),
                                "top_chapters": chapters.most_common(10), "top_passages": verses.most_common(10)})
    scripture_index.sort(key=lambda x: -x["total"])

    # ------------------------------------------------------------- talks + conferences
    log("aggregate: talks and conferences")
    n_counted = collections.Counter(c["talk_id"] for c in counted)
    scrip_by_talk: dict[int, list[str]] = collections.defaultdict(list)
    for c in scripture:
        if c["scripture_book"]:
            scrip_by_talk[c["talk_id"]].append(f"{c['scripture_book']} {c['chapter']}" + (f":{c['verse_start']}" if c["verse_start"] else "") if c["chapter"] else c["scripture_book"])
    talks_index = [{"id": t["id"], "uri": t["uri"], "title": t["title"], "speaker": t["speaker_name"], "speaker_id": t["speaker_id"],
                    "role": t["speaker_role"], "conf": t["conf"], "year": t["year"], "session": t["session"], "so": t["session_ord"],
                    "o": t["ord"] or 0, "nc": n_counted.get(t["id"], 0), "s": scrip_by_talk.get(t["id"], [])}
                   for t in sorted(talks.values(), key=lambda t: (t["conf"], t["session_ord"], t["ord"] or 0))]
    conf_index = []
    for cid, conf in confs.items():
        ctids = {t["id"] for t in talks.values() if t["conference_id"] == cid}
        if not ctids:
            continue
        c_counted = [c for c in counted if c["talk_id"] in ctids]
        cov = coverage.get(cid, {})
        top_p = collections.Counter(c["person_quoted_id"] for c in c_counted if c["person_quoted_id"]).most_common(6)
        conf_index.append({"key": conf["key"], "year": conf["year"], "month": conf["month"], "title": conf["title"],
                           "talks": len(ctids), "talks_parsed": cov.get("talks_parsed", 0), "talks_extracted": cov.get("talks_extracted", 0),
                           "citations": len(c_counted), "scripture": sum(1 for c in scripture if c["talk_id"] in ctids),
                           "external": sum(1 for c in c_counted if c["person_quoted_id"] and kind_of.get(c["person_quoted_id"]) == "external"),
                           "top_persons": [{"id": i, "name": authors[i]["canonical_name"], "n": n} for i, n in top_p]})

    totals = {"talks": len(talks), "citations": len(cits), "counted": len(counted), "scripture": len(scripture),
              "by_tier": dict(collections.Counter(c["tier"] for c in cits)), "persons": len(persons_index), "works": len(works_index),
              "external_citations": sum(1 for c in counted if c["person_quoted_id"] and kind_of.get(c["person_quoted_id"]) == "external")}
    by_decade_totals = collections.Counter(decade(talks[c["talk_id"]]["year"]) for c in counted)
    talks_by_decade = collections.Counter(decade(t["year"]) for t in talks.values())
    index = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "totals": totals,
             "by_decade": {d: {"citations": by_decade_totals[d], "talks": talks_by_decade[d]} for d in sorted(talks_by_decade)},
             "conferences": conf_index, "talks": talks_index, "persons": persons_index, "works": works_index,
             "containers": container_names, "speakers": speakers_index, "scripture": scripture_index}
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    write_artifact_page(out.parent)
    sizes = {p.name: round(p.stat().st_size / 1e6, 2) for p in out.iterdir()}
    log(f"aggregate: wrote {out} {sizes} MB ({len(persons_index)} persons, {len(works_index)} works, {len(conf_index)} conferences)")


def write_artifact_page(site_dir: Path) -> None:
    """site/artifact.html: the dashboard without the document wrapper, for publishing as a claude.ai Artifact
    (the Artifact host supplies its own doctype, head, and body)."""
    import re
    src = site_dir / "index.html"
    if not src.exists():
        return
    s = src.read_text()
    s = re.sub(r"^<!doctype html>\s*<html[^>]*>\s*<head>\s*", "", s, flags=re.I)
    s = re.sub(r'<meta charset="utf-8">\s*<meta name="viewport"[^>]*>\s*', "", s)
    s = s.replace("</head>\n<body>\n", "").replace("</body>\n</html>\n", "")
    (site_dir / "artifact.html").write_text(s)
