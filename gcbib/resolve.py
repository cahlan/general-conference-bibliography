"""Stage 4: collapse name and title variants into canonical authors and works.

    "C. S. Lewis", "C.S. Lewis", "Lewis" (resolved short form)  ->  one author row
    "Mere Christianity", "Mere Christianity (1952)"             ->  one work row

Automatic normalization first, then data/overrides.yaml (hand-curated aliases) wins.
"""
from __future__ import annotations

import collections
import re
import sqlite3
from pathlib import Path

import yaml

from .grammar import clean_name

OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "data" / "overrides.yaml"

# Church presidents and other leaders who never spoke in the 1971+ archive but are cited constantly.
HISTORIC_LEADERS = {
    "Joseph Smith", "Brigham Young", "John Taylor", "Wilford Woodruff", "Lorenzo Snow", "Joseph F. Smith",
    "Heber J. Grant", "George Albert Smith", "David O. McKay", "Hyrum Smith", "Oliver Cowdery", "Parley P. Pratt",
    "Orson Pratt", "Heber C. Kimball", "George Q. Cannon", "Orson F. Whitney", "James E. Talmage", "B. H. Roberts",
    "John A. Widtsoe", "J. Reuben Clark Jr.", "J. Reuben Clark", "Melvin J. Ballard", "Charles W. Penrose",
    "Anthon H. Lund", "Francis M. Lyman", "Matthew Cowley", "Stephen L Richards", "Stephen L. Richards",
    "Hugh B. Brown", "Richard L. Evans", "Marion G. Romney", "N. Eldon Tanner", "Harold B. Lee", "Joseph Fielding Smith",
    "Spencer W. Kimball", "Ezra Taft Benson", "Howard W. Hunter", "Gordon B. Hinckley", "Thomas S. Monson",
    "Russell M. Nelson", "Eliza R. Snow", "Emma Smith", "Lucy Mack Smith", "Zina D. H. Young", "Emmeline B. Wells",
    "Bathsheba W. Smith", "Belle S. Spafford", "Amy Brown Lyman", "Louise Y. Robison", "Clarissa S. Williams",
    "Erastus Snow", "Lorenzo Snow", "Franklin D. Richards", "Moses Thatcher", "Rudger Clawson", "Reed Smoot",
    "Hyrum M. Smith", "George F. Richards", "David A. Smith", "Sylvester Q. Cannon", "LeGrand Richards",
    "Mark E. Petersen", "Delbert L. Stapley", "Marion D. Hanks", "S. Dilworth Young", "Sterling W. Sill",
    "Bruce R. McConkie", "Neal A. Maxwell", "Boyd K. Packer", "L. Tom Perry", "David B. Haight", "James E. Faust",
    "Joseph B. Wirthlin", "Richard G. Scott", "Robert D. Hales", "Jeffrey R. Holland", "Henry B. Eyring",
    "Dieter F. Uchtdorf", "Dallin H. Oaks", "M. Russell Ballard", "Russell M. Nelson",
    "George A. Smith", "Orson Hyde", "Willard Richards", "Daniel H. Wells", "Jedediah M. Grant", "Amasa Lyman",
    "Joseph Smith Sr.", "Samuel H. Smith", "William Clayton", "Charles C. Rich", "Abraham O. Woodruff", "Marriner W. Merrill",
    "John W. Taylor", "Matthias F. Cowley", "Abraham H. Cannon", "Brigham Young Jr.", "Anthony W. Ivins", "Richard R. Lyman",
    "Joseph F. Merrill", "Charles A. Callis", "Alonzo A. Hinckley", "Albert E. Bowen", "Henry D. Moyle", "Adam S. Bennion",
    "George Q. Morris", "Marvin J. Ashton", "Louie B. Felt", "May Anderson", "Aurelia S. Rogers", "Ruth May Fox",
    "Lucy Grant Cannon", "Barbara B. Smith", "Camilla E. Kimball", "Marjorie Pay Hinckley", "Elaine L. Jack",
    "Ardeth G. Kapp", "Patricia T. Holland", "Chieko N. Okazaki", "Sheri L. Dew", "Bonnie D. Parkin", "Julie B. Beck",
    "Elaine S. Dalton", "Linda K. Burton", "Bonnie L. Oscarson", "Jean B. Bingham", "Joy D. Jones", "Camille N. Johnson",
    "Susa Young Gates", "Karl G. Maeser", "Jesse Knight", "Truman O. Angell", "Jacob Hamblin", "Porter Rockwell",
    "Edward Partridge", "Newel K. Whitney", "Sidney Rigdon", "Martin Harris", "David Whitmer", "Thomas B. Marsh",
    "Lyman Wight", "William W. Phelps", "W. W. Phelps", "John Whitmer", "Frederick G. Williams", "Oliver Granger",
}
SCRIPTURE_FIGURES = {
    "Nephi", "Lehi", "Jacob", "Enos", "Mosiah", "Benjamin", "King Benjamin", "Abinadi", "Alma", "Amulek", "Ammon",
    "Helaman", "Samuel the Lamanite", "Mormon", "Moroni", "Captain Moroni", "Ether", "Jared", "Brother of Jared",
    "Adam", "Eve", "Enoch", "Noah", "Abraham", "Sarah", "Isaac", "Rebekah", "Jacob", "Joseph", "Moses", "Aaron",
    "Joshua", "Ruth", "Samuel", "David", "Solomon", "Elijah", "Elisha", "Isaiah", "Jeremiah", "Ezekiel", "Daniel",
    "Hosea", "Joel", "Amos", "Jonah", "Micah", "Malachi", "Job", "Esther", "Nehemiah", "Ezra", "Jesus", "Jesus Christ",
    "Christ", "The Savior", "Savior", "Mary", "Joseph", "John the Baptist", "Peter", "James", "John", "Andrew",
    "Philip", "Thomas", "Matthew", "Mark", "Luke", "Paul", "Stephen", "Barnabas", "Timothy", "Titus", "Jude",
    "Martha", "Mary Magdalene", "Lazarus", "Nicodemus", "Zacchaeus", "Pilate", "Herod", "The Lord", "Lord",
    "Heavenly Father", "God", "The Apostle Paul", "Apostle Paul", "The Prophet Nephi", "The Psalmist", "Psalmist",
}
AMBIGUOUS_FIRST_LAST = {("joseph", "smith"), ("john", "smith"), ("john", "taylor"), ("george", "smith"),
                        ("hyrum", "smith"), ("william", "smith"), ("samuel", "smith"), ("don", "smith")}


def name_key(name: str) -> str:
    n = clean_name(name) or name
    n = n.lower()
    n = re.sub(r"[.,’'\"()\[\]]", "", n)
    n = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def title_key(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[“”\"‘’'.,:;!?()\[\]—–-]", " ", t)
    t = re.sub(r"\b(the|a|an)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def load_overrides() -> dict:
    if not OVERRIDES_PATH.exists():
        return {"authors": [], "works": []}
    data = yaml.safe_load(OVERRIDES_PATH.read_text()) or {}
    data.setdefault("authors", []); data.setdefault("works", [])
    return data


def resolve_all(con: sqlite3.Connection, log=print) -> None:
    ov = load_overrides()
    cur = con.cursor()

    # ---------------------------------------------------------------- authors
    log("resolve: authors")
    counts: collections.Counter[str] = collections.Counter()
    for (name, n) in cur.execute("SELECT person_quoted, COUNT(*) FROM citations WHERE person_quoted IS NOT NULL GROUP BY person_quoted"):
        counts[name] += n
    for (name, n) in cur.execute("SELECT author_name, COUNT(*) FROM citations WHERE author_name IS NOT NULL GROUP BY author_name"):
        counts[name] += n
    speakers = {r[0] for r in cur.execute("SELECT DISTINCT speaker_name FROM talks WHERE speaker_name != ''")}
    for s in speakers:
        counts[s] += 0

    # Group by normalized key; canonical = most frequent spelling in the group
    groups: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for name, n in counts.items():
        groups[name_key(name)][name] += n

    # Merge "First Last" into a unique "First M. Last" (never for ambiguous pairs like Joseph Smith)
    by_first_last: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for key in groups:
        toks = key.split()
        if len(toks) >= 2:
            by_first_last[(toks[0], toks[-1])].append(key)
    merge_into: dict[str, str] = {}
    for (first, last), keys in by_first_last.items():
        if (first, last) in AMBIGUOUS_FIRST_LAST or len(keys) < 2:
            continue
        shorts = [k for k in keys if len(k.split()) == 2]
        fulls = [k for k in keys if len(k.split()) > 2]
        if len(fulls) == 1 and shorts:
            for s in shorts:
                merge_into[s] = fulls[0]
    for s, f in merge_into.items():
        groups[f].update(groups.pop(s))

    # Overrides: alias -> canonical
    alias_to_canonical: dict[str, str] = {}
    kind_override: dict[str, str] = {}
    for a in ov["authors"]:
        canon = a["canonical"]
        kind_override[name_key(canon)] = a.get("kind")
        for al in [canon] + list(a.get("aliases", [])):
            alias_to_canonical[name_key(al)] = canon
    merged: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    canonical_name: dict[str, str] = {}
    for key, ctr in groups.items():
        canon = alias_to_canonical.get(key)
        target = name_key(canon) if canon else key
        merged[target].update(ctr)
        if canon:
            canonical_name[target] = canon
    speaker_keys = {name_key(s) for s in speakers} | {name_key(h) for h in HISTORIC_LEADERS}
    scripture_keys = {name_key(f) for f in SCRIPTURE_FIGURES}

    # works reference authors, so clear works first (they are rebuilt below)
    cur.execute("UPDATE citations SET work_id=NULL, container_work_id=NULL, author_id=NULL, person_quoted_id=NULL")
    cur.execute("DELETE FROM work_aliases"); cur.execute("DROP TABLE IF EXISTS works")
    cur.execute("UPDATE talks SET speaker_id=NULL")
    cur.execute("DELETE FROM author_aliases"); cur.execute("DELETE FROM authors")
    key_to_id: dict[str, int] = {}
    for key, ctr in merged.items():
        canon = canonical_name.get(key) or ctr.most_common(1)[0][0]
        kind = kind_override.get(key) or ("church_leader" if key in speaker_keys else "scripture_figure" if key in scripture_keys else "external")
        cur.execute("INSERT OR IGNORE INTO authors(canonical_name, kind) VALUES (?,?)", (canon, kind))
        aid = cur.execute("SELECT id FROM authors WHERE canonical_name=?", (canon,)).fetchone()[0]
        key_to_id[key] = aid
        for alias in ctr:
            cur.execute("INSERT OR REPLACE INTO author_aliases(alias, author_id) VALUES (?,?)", (alias, aid))
    for a in ov["authors"]:
        aid = key_to_id.get(name_key(a["canonical"]))
        if aid:
            for al in a.get("aliases", []):
                cur.execute("INSERT OR REPLACE INTO author_aliases(alias, author_id) VALUES (?,?)", (al, aid))

    def author_id_for(name: str | None) -> int | None:
        if not name:
            return None
        row = cur.execute("SELECT author_id FROM author_aliases WHERE alias=?", (name,)).fetchone()
        if row:
            return row[0]
        k = name_key(name)
        k = merge_into.get(k, k)
        k = name_key(alias_to_canonical[k]) if k in alias_to_canonical else k
        return key_to_id.get(k)

    # Fill talk cross-references from our own talks table (speaker + title), then assign ids
    log("resolve: cross-referenced talks")
    cur.execute("""UPDATE citations SET work_title = (SELECT title FROM talks t WHERE t.uri = citations.cited_talk_uri)
                   WHERE cited_talk_uri IS NOT NULL AND (work_title IS NULL OR work_title GLOB '*[0-9]*' AND length(work_title) < 6)
                   AND EXISTS (SELECT 1 FROM talks t WHERE t.uri = citations.cited_talk_uri)""")
    cur.execute("""UPDATE citations SET person_quoted = COALESCE(person_quoted, (SELECT speaker_name FROM talks t WHERE t.uri = citations.cited_talk_uri)),
                                        author_name = COALESCE(author_name, (SELECT speaker_name FROM talks t WHERE t.uri = citations.cited_talk_uri))
                   WHERE cited_talk_uri IS NOT NULL AND EXISTS (SELECT 1 FROM talks t WHERE t.uri = citations.cited_talk_uri)""")
    cur.execute("UPDATE talks SET speaker_id = NULL")
    for (tid, sp) in cur.execute("SELECT id, speaker_name FROM talks").fetchall():
        cur.execute("UPDATE talks SET speaker_id=? WHERE id=?", (author_id_for(sp), tid))

    log("resolve: assigning author ids")
    rows = cur.execute("SELECT id, author_name, person_quoted FROM citations").fetchall()
    cache: dict[str, int | None] = {}
    def cached(name):
        if name not in cache:
            cache[name] = author_id_for(name)
        return cache[name]
    cur.executemany("UPDATE citations SET author_id=?, person_quoted_id=? WHERE id=?",
                    [(cached(a), cached(p), cid) for cid, a, p in rows])

    # ---------------------------------------------------------------- works
    log("resolve: works")
    from .db import SCHEMA
    cur.executescript(SCHEMA)
    work_alias_to_canon: dict[str, dict] = {}
    for w in ov["works"]:
        for al in [w["canonical"]] + list(w.get("aliases", [])):
            work_alias_to_canon[title_key(al)] = w

    # Scripture books
    book_ids: dict[str, int] = {}
    for (book,) in cur.execute("SELECT DISTINCT scripture_book FROM citations WHERE tier='scripture' AND scripture_book IS NOT NULL").fetchall():
        cur.execute("INSERT INTO works(canonical_title, author_id, work_type) VALUES (?,?,?)", (book, None, "scripture"))
        book_ids[book] = cur.lastrowid
    cur.executemany("UPDATE citations SET work_id=? WHERE tier='scripture' AND scripture_book=?", [(i, b) for b, i in book_ids.items()])

    # Talks cited by URI
    talk_work_ids: dict[str, int] = {}
    for (uri, title, speaker_id) in cur.execute("""SELECT DISTINCT c.cited_talk_uri, t.title, t.speaker_id FROM citations c
                                                   LEFT JOIN talks t ON t.uri=c.cited_talk_uri WHERE c.cited_talk_uri IS NOT NULL""").fetchall():
        title = title or (cur.execute("SELECT work_title FROM citations WHERE cited_talk_uri=? AND work_title IS NOT NULL LIMIT 1", (uri,)).fetchone() or [uri])[0]
        cur.execute("INSERT INTO works(canonical_title, author_id, work_type, cited_talk_uri) VALUES (?,?,?,?)", (title, speaker_id, "talk", uri))
        talk_work_ids[uri] = cur.lastrowid
    cur.executemany("UPDATE citations SET work_id=? WHERE cited_talk_uri=?", [(i, u) for u, i in talk_work_ids.items()])

    # Everything else: group by normalized title (+ author for books so two "Poems" don't merge)
    groups_w: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    meta_w: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    rows = cur.execute("""SELECT id, work_title, work_type, author_id, person_quoted_id, container_title FROM citations
                          WHERE tier IN ('freetext','crossref') AND work_id IS NULL""").fetchall()
    assign: list[tuple[tuple, int]] = []
    for cid, wt, wtype, aid, pid, cont in rows:
        title = wt or cont
        if not title:
            continue
        is_container_only = wt is None
        ovr = work_alias_to_canon.get(title_key(title))
        if ovr:
            gkey = ("ovr", ovr["canonical"])
        elif is_container_only or (wtype in ("periodical", "hymn", "manual", "talk", "study_help", "web", "play", "poem")) \
                or len(title_key(title).split()) >= 3:
            gkey = ("t", title_key(title))     # long titles are unambiguous without an author
        else:
            gkey = ("ta", title_key(title), aid or pid or 0)
        groups_w[gkey][title] += 1
        meta_w[gkey][(wtype if not is_container_only else "periodical", aid if not is_container_only else None)] += 1
        assign.append((gkey, cid))
    # Merge author-keyed groups that share a title with an authorless group (e.g. "Mere Christianity" cited without Lewis)
    title_only = {k[1]: k for k in groups_w if k[0] == "ta" and k[2] == 0}
    remap: dict[tuple, tuple] = {}
    for k in list(groups_w):
        if k[0] == "ta" and k[2] != 0 and k[1] in title_only:
            others = [kk for kk in groups_w if kk[0] == "ta" and kk[1] == k[1] and kk[2] != 0]
            if len(others) == 1:
                remap[title_only[k[1]]] = k
    for src, dst in remap.items():
        groups_w[dst].update(groups_w.pop(src)); meta_w[dst].update(meta_w.pop(src))
    gid: dict[tuple, int] = {}
    for gkey, ctr in groups_w.items():
        canon = gkey[1] if gkey[0] == "ovr" else ctr.most_common(1)[0][0]
        wtype, aid = meta_w[gkey].most_common(1)[0][0]
        if gkey[0] == "ovr":
            ovr = work_alias_to_canon[title_key(canon)]
            wtype = ovr.get("type", wtype)
            if ovr.get("author"):
                aid = author_id_for(ovr["author"]) or aid
        cur.execute("INSERT INTO works(canonical_title, author_id, work_type) VALUES (?,?,?)", (canon, aid, wtype))
        gid[gkey] = cur.lastrowid
        for alias in ctr:
            cur.execute("INSERT OR IGNORE INTO work_aliases(alias, work_id) VALUES (?,?)", (alias, gid[gkey]))
    cur.executemany("UPDATE citations SET work_id=? WHERE id=?", [(gid[remap.get(g, g)], cid) for g, cid in assign])

    # Container works (periodicals / anthologies) for citations that have both a work and a container
    cont_ids: dict[str, int] = {}
    for (cont,) in cur.execute("SELECT DISTINCT container_title FROM citations WHERE container_title IS NOT NULL AND work_title IS NOT NULL").fetchall():
        k = title_key(cont)
        row = cur.execute("SELECT work_id FROM work_aliases WHERE alias=?", (cont,)).fetchone()
        if row:
            cont_ids[cont] = row[0]; continue
        existing = next((w for w in cont_ids if title_key(w) == k), None)
        if existing:
            cont_ids[cont] = cont_ids[existing]; continue
        cur.execute("INSERT INTO works(canonical_title, author_id, work_type) VALUES (?,?,?)", (cont, None, "periodical"))
        cont_ids[cont] = cur.lastrowid
        cur.execute("INSERT OR IGNORE INTO work_aliases(alias, work_id) VALUES (?,?)", (cont, cont_ids[cont]))
    cur.executemany("UPDATE citations SET container_work_id=? WHERE container_title=? AND work_title IS NOT NULL", [(i, c) for c, i in cont_ids.items()])

    # A work's author: if the work row has no author, take the most common person_quoted among its citations
    for (wid,) in cur.execute("SELECT id FROM works WHERE author_id IS NULL AND work_type NOT IN ('scripture','periodical','hymn','manual','study_help')").fetchall():
        row = cur.execute("""SELECT person_quoted_id, COUNT(*) n FROM citations WHERE work_id=? AND person_quoted_id IS NOT NULL
                             GROUP BY person_quoted_id ORDER BY n DESC LIMIT 1""", (wid,)).fetchone()
        if row:
            cur.execute("UPDATE works SET author_id=? WHERE id=?", (row[0], wid))
    con.commit()
    n_a = cur.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
    n_w = cur.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    log(f"resolve: {n_a} authors, {n_w} works")
