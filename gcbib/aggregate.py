"""Stage 5: SQLite -> static JSON for the dashboard (site/data/).

index.json               everything the home page and search need
person/{id}.json         one author/person: citations over time, works, every citing talk
work/{id}.json           one work
conference/{yyyy-mm}.json one conference: sessions, talks, leaderboards, all citations
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path

NON_COUNTED = ("scripture", "note")


def decade(year: int) -> str:
    return f"{year // 10 * 10}s"


def build_site_data(con: sqlite3.Connection, out: Path, log=print) -> None:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "person").mkdir(parents=True); (out / "work").mkdir(); (out / "conference").mkdir()
    cur = con.cursor()

    confs = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM conferences ORDER BY year, month")}
    for c in confs.values():
        c["key"] = f"{c['year']}-{c['month']:02d}"
    sessions = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM sessions")}
    talks = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM talks WHERE is_talk=1")}
    for t in talks.values():
        t["conf"] = confs[t["conference_id"]]["key"]
        t["session"] = sessions[t["session_id"]]["title"] if t["session_id"] in sessions else ""
        t["year"] = confs[t["conference_id"]]["year"]
    authors = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM authors")}
    works = {r["id"]: dict(r) for r in cur.execute("SELECT * FROM works")}
    coverage = {r["conference_id"]: dict(r) for r in cur.execute("SELECT * FROM coverage")}

    log("aggregate: loading citations")
    cits = [dict(r) for r in cur.execute("""SELECT c.*, f.context, f.marker, f.inline FROM citations c
                                             JOIN footnotes f ON f.id=c.footnote_id
                                             JOIN talks t ON t.id=c.talk_id WHERE t.is_talk=1""")]
    counted = [c for c in cits if c["tier"] not in NON_COUNTED]
    scripture = [c for c in cits if c["tier"] == "scripture"]

    def talk_ref(t: dict) -> dict:
        return {"uri": t["uri"], "title": t["title"], "speaker": t["speaker_name"], "speaker_id": t["speaker_id"],
                "conf": t["conf"], "session": t["session"], "year": t["year"]}

    def cit_ref(c: dict) -> dict:
        t = talks[c["talk_id"]]
        w = works.get(c["work_id"]) if c["work_id"] else None
        return {"talk": talk_ref(t), "person_id": c["person_quoted_id"], "person": c["person_quoted"],
                "author_id": c["author_id"], "work_id": c["work_id"], "work": (w["canonical_title"] if w else c["work_title"]) or c["container_title"],
                "work_type": c["work_type"], "container": c["container_title"], "relation": c["relation"],
                "locator": c["locator"], "year": c["year"], "tier": c["tier"], "raw": c["raw_text"],
                "context": (c["context"] or "")[-240:], "confidence": c["confidence"], "cited_talk_uri": c["cited_talk_uri"]}

    # ------------------------------------------------------------- persons
    log("aggregate: persons")
    by_person: dict[int, list[dict]] = collections.defaultdict(list)
    for c in counted:
        if c["person_quoted_id"]:
            by_person[c["person_quoted_id"]].append(c)
    persons_index = []
    for aid, lst in by_person.items():
        a = authors[aid]
        talk_ids = {c["talk_id"] for c in lst}
        by_dec = collections.Counter(decade(talks[c["talk_id"]]["year"]) for c in lst)
        by_conf = collections.Counter(talks[c["talk_id"]]["conf"] for c in lst)
        work_ctr = collections.Counter(c["work_id"] for c in lst if c["work_id"])
        rel = collections.Counter(c["relation"] for c in lst)
        aliases = [r[0] for r in cur.execute("SELECT alias FROM author_aliases WHERE author_id=?", (aid,))]
        persons_index.append({"id": aid, "name": a["canonical_name"], "kind": a["kind"], "total": len(lst),
                              "quoted": rel.get("quoted", 0) + rel.get("secondary", 0), "see": rel.get("see", 0),
                              "talks": len(talk_ids), "works": len(work_ctr), "by_decade": dict(by_dec),
                              "first_year": min(talks[c["talk_id"]]["year"] for c in lst),
                              "last_year": max(talks[c["talk_id"]]["year"] for c in lst)})
        detail = {"id": aid, "name": a["canonical_name"], "kind": a["kind"], "aliases": aliases, "total": len(lst),
                  "by_conference": [{"conf": k, "n": by_conf[k]} for k in sorted(by_conf)],
                  "works": sorted([{"id": wid, "title": works[wid]["canonical_title"], "type": works[wid]["work_type"], "n": n}
                                   for wid, n in work_ctr.items()], key=lambda x: -x["n"]),
                  "speakers": sorted(collections.Counter(talks[c["talk_id"]]["speaker_name"] for c in lst).items(), key=lambda x: -x[1])[:25],
                  "citations": sorted((cit_ref(c) for c in lst), key=lambda x: (x["talk"]["conf"], x["talk"]["uri"]))}
        (out / "person" / f"{aid}.json").write_text(json.dumps(detail, ensure_ascii=False))
    persons_index.sort(key=lambda x: -x["total"])

    # Speakers (who gave talks) index for the speaker view
    speakers = collections.Counter(t["speaker_id"] for t in talks.values() if t["speaker_id"])
    speakers_index = [{"id": sid, "name": authors[sid]["canonical_name"], "talks": n,
                       "citations": sum(1 for c in counted if talks[c["talk_id"]]["speaker_id"] == sid)}
                      for sid, n in speakers.items() if sid in authors]
    speakers_index.sort(key=lambda x: -x["talks"])

    # ------------------------------------------------------------- works
    log("aggregate: works")
    by_work: dict[int, list[dict]] = collections.defaultdict(list)
    for c in counted:
        if c["work_id"]:
            by_work[c["work_id"]].append(c)
    works_index = []
    for wid, lst in by_work.items():
        w = works[wid]
        by_dec = collections.Counter(decade(talks[c["talk_id"]]["year"]) for c in lst)
        by_conf = collections.Counter(talks[c["talk_id"]]["conf"] for c in lst)
        author = authors.get(w["author_id"]) if w["author_id"] else None
        persons = collections.Counter(c["person_quoted_id"] for c in lst if c["person_quoted_id"])
        aliases = [r[0] for r in cur.execute("SELECT alias FROM work_aliases WHERE work_id=?", (wid,))]
        works_index.append({"id": wid, "title": w["canonical_title"], "type": w["work_type"], "author_id": w["author_id"],
                            "author": author["canonical_name"] if author else None, "total": len(lst),
                            "talks": len({c["talk_id"] for c in lst}), "by_decade": dict(by_dec),
                            "cited_talk_uri": w["cited_talk_uri"]})
        detail = {"id": wid, "title": w["canonical_title"], "type": w["work_type"], "author_id": w["author_id"],
                  "author": author["canonical_name"] if author else None, "aliases": aliases, "total": len(lst),
                  "cited_talk_uri": w["cited_talk_uri"],
                  "by_conference": [{"conf": k, "n": by_conf[k]} for k in sorted(by_conf)],
                  "persons": sorted([{"id": pid, "name": authors[pid]["canonical_name"], "n": n} for pid, n in persons.items()], key=lambda x: -x["n"]),
                  "citations": sorted((cit_ref(c) for c in lst), key=lambda x: (x["talk"]["conf"], x["talk"]["uri"]))}
        (out / "work" / f"{wid}.json").write_text(json.dumps(detail, ensure_ascii=False))
    works_index.sort(key=lambda x: -x["total"])

    # ------------------------------------------------------------- scripture
    log("aggregate: scripture")
    books = collections.defaultdict(list)
    for c in scripture:
        books[c["scripture_book"] or "?"].append(c)
    scripture_index = []
    for book, lst in books.items():
        by_dec = collections.Counter(decade(talks[c["talk_id"]]["year"]) for c in lst)
        chapters = collections.Counter(f"{book} {c['chapter']}" for c in lst if c["chapter"])
        verses = collections.Counter(f"{book} {c['chapter']}:{c['verse_start']}" + (f"–{c['verse_end']}" if c["verse_end"] and c["verse_end"] != c["verse_start"] else "")
                                     for c in lst if c["chapter"] and c["verse_start"])
        scripture_index.append({"book": book, "total": len(lst), "talks": len({c["talk_id"] for c in lst}), "by_decade": dict(by_dec),
                                "top_chapters": chapters.most_common(10), "top_passages": verses.most_common(10)})
    scripture_index.sort(key=lambda x: -x["total"])
    from .scripture import VOLUME_OF_BOOK
    for s_ in scripture_index:
        s_["volume"] = VOLUME_OF_BOOK.get(s_["book"], "Other")

    # ------------------------------------------------------------- conferences
    log("aggregate: conferences")
    conf_index = []
    for cid, conf in confs.items():
        ctalks = [t for t in talks.values() if t["conference_id"] == cid]
        if not ctalks:
            continue
        tids = {t["id"] for t in ctalks}
        c_counted = [c for c in counted if c["talk_id"] in tids]
        c_scrip = [c for c in scripture if c["talk_id"] in tids]
        def leaderboard(lst, key, names, k=15):
            ctr = collections.Counter(c[key] for c in lst if c[key])
            return [{"id": i, "name": names[i], "n": n} for i, n in ctr.most_common(k) if i in names]
        pnames = {i: a["canonical_name"] for i, a in authors.items()}
        wnames = {i: w["canonical_title"] for i, w in works.items()}
        cov = coverage.get(cid, {})
        entry = {"key": conf["key"], "year": conf["year"], "month": conf["month"], "title": conf["title"],
                 "talks": len(ctalks), "talks_parsed": cov.get("talks_parsed", 0), "talks_extracted": cov.get("talks_extracted", 0),
                 "citations": len(c_counted), "scripture": len(c_scrip),
                 "external": sum(1 for c in c_counted if c["person_quoted_id"] and authors[c["person_quoted_id"]]["kind"] == "external"),
                 "top_persons": leaderboard(c_counted, "person_quoted_id", pnames, 10),
                 "top_works": leaderboard(c_counted, "work_id", wnames, 10)}
        conf_index.append(entry)
        sess_out = []
        for sid, s in sorted(((sid, s) for sid, s in sessions.items() if s["conference_id"] == cid), key=lambda x: x[1]["ord"] or 0):
            stalks = sorted((t for t in ctalks if t["session_id"] == sid), key=lambda t: t["ord"] or 0)
            stids = {t["id"] for t in stalks}
            s_counted = [c for c in c_counted if c["talk_id"] in stids]
            sess_out.append({"title": s["title"], "citations": len(s_counted),
                             "scripture": sum(1 for c in c_scrip if c["talk_id"] in stids),
                             "top_persons": leaderboard(s_counted, "person_quoted_id", pnames, 8),
                             "top_works": leaderboard(s_counted, "work_id", wnames, 8),
                             "talks": [{**talk_ref(t), "role": t["speaker_role"],
                                        "citations": sum(1 for c in c_counted if c["talk_id"] == t["id"]),
                                        "scripture": sum(1 for c in c_scrip if c["talk_id"] == t["id"]),
                                        "items": [cit_ref(c) for c in sorted(c_counted, key=lambda c: (c["footnote_id"], c["position"])) if c["talk_id"] == t["id"]],
                                        "scripture_items": [f"{c['scripture_book']} {c['chapter']}" + (f":{c['verse_start']}" if c["verse_start"] else "") for c in c_scrip if c["talk_id"] == t["id"]]}
                                       for t in stalks]})
        (out / "conference" / f"{conf['key']}.json").write_text(json.dumps({**entry, "sessions": sess_out}, ensure_ascii=False))

    totals = {"talks": len(talks), "citations": len(cits), "counted": len(counted), "scripture": len(scripture),
              "by_tier": dict(collections.Counter(c["tier"] for c in cits)),
              "persons": len(persons_index), "works": len(works_index),
              "external_citations": sum(1 for c in counted if c["person_quoted_id"] and authors[c["person_quoted_id"]]["kind"] == "external")}
    by_decade_totals = collections.Counter(decade(talks[c["talk_id"]]["year"]) for c in counted)
    talks_by_decade = collections.Counter(decade(t["year"]) for t in talks.values())
    index = {"generated_at": dt.datetime.now().isoformat(timespec="seconds"), "totals": totals,
             "by_decade": {d: {"citations": by_decade_totals[d], "talks": talks_by_decade[d]} for d in sorted(talks_by_decade)},
             "conferences": conf_index, "persons": persons_index, "works": works_index[:3000],
             "speakers": speakers_index, "scripture": scripture_index}
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False))
    log(f"aggregate: wrote {out} ({len(persons_index)} persons, {len(works_index)} works, {len(conf_index)} conferences)")
