"""SQLite schema and connection helpers. One file, data/gcbib.sqlite, is the source of truth."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "gcbib.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS conferences (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL, month INTEGER NOT NULL, title TEXT,
    UNIQUE(year, month)
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    conference_id INTEGER NOT NULL REFERENCES conferences(id),
    title TEXT NOT NULL, uri TEXT, ord INTEGER,
    UNIQUE(conference_id, title)
);
CREATE TABLE IF NOT EXISTS talks (
    id INTEGER PRIMARY KEY,
    uri TEXT NOT NULL UNIQUE,
    conference_id INTEGER NOT NULL REFERENCES conferences(id),
    session_id INTEGER REFERENCES sessions(id),
    ord INTEGER,
    title TEXT, speaker_name TEXT, speaker_role TEXT, speaker_id INTEGER,
    date TEXT, is_talk INTEGER NOT NULL DEFAULT 1,
    parsed_at TEXT, extracted_at TEXT
);
CREATE TABLE IF NOT EXISTS paragraphs (
    id INTEGER PRIMARY KEY,
    talk_id INTEGER NOT NULL REFERENCES talks(id) ON DELETE CASCADE,
    pid TEXT, ord INTEGER, text TEXT,
    UNIQUE(talk_id, pid)
);
CREATE TABLE IF NOT EXISTS footnotes (
    id INTEGER PRIMARY KEY,
    talk_id INTEGER NOT NULL REFERENCES talks(id) ON DELETE CASCADE,
    marker TEXT, ord INTEGER, pid TEXT,
    raw_html TEXT, text TEXT, context TEXT,
    inline INTEGER NOT NULL DEFAULT 0,
    UNIQUE(talk_id, marker)
);
CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY,
    footnote_id INTEGER NOT NULL REFERENCES footnotes(id) ON DELETE CASCADE,
    talk_id INTEGER NOT NULL REFERENCES talks(id) ON DELETE CASCADE,
    position INTEGER,
    tier TEXT NOT NULL,          -- scripture | crossref | freetext | note
    relation TEXT,               -- quoted | see | secondary
    raw_text TEXT,
    author_name TEXT,            -- as written (author of the work)
    person_quoted TEXT,          -- as written (person whose words are used; often = author)
    work_title TEXT,             -- as written
    work_type TEXT,              -- book | play | poem | hymn | article | talk | manual | scripture | periodical | speech | other
    container_title TEXT,        -- periodical / anthology / manual the work appears in
    locator TEXT, year INTEGER,
    cited_talk_uri TEXT,         -- for talk-to-talk citations
    href TEXT,
    scripture_book TEXT, chapter INTEGER, verse_start INTEGER, verse_end INTEGER,
    parser TEXT, confidence REAL,
    author_id INTEGER, person_quoted_id INTEGER, work_id INTEGER, container_work_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_citations_talk ON citations(talk_id);
CREATE INDEX IF NOT EXISTS ix_citations_author ON citations(author_id);
CREATE INDEX IF NOT EXISTS ix_citations_person ON citations(person_quoted_id);
CREATE INDEX IF NOT EXISTS ix_citations_work ON citations(work_id);
CREATE INDEX IF NOT EXISTS ix_citations_tier ON citations(tier);

CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL UNIQUE,
    kind TEXT                    -- church_leader | external | scripture_figure
);
CREATE TABLE IF NOT EXISTS author_aliases (
    alias TEXT PRIMARY KEY, author_id INTEGER NOT NULL REFERENCES authors(id)
);
CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY,
    canonical_title TEXT NOT NULL,
    author_id INTEGER REFERENCES authors(id),
    work_type TEXT,
    cited_talk_uri TEXT
);
CREATE INDEX IF NOT EXISTS ix_works_title ON works(canonical_title);
CREATE TABLE IF NOT EXISTS work_aliases (
    alias TEXT PRIMARY KEY, work_id INTEGER NOT NULL REFERENCES works(id)
);
CREATE TABLE IF NOT EXISTS llm_cache (
    input_hash TEXT PRIMARY KEY, model TEXT, output_json TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS coverage (
    conference_id INTEGER PRIMARY KEY REFERENCES conferences(id),
    talks_total INTEGER, talks_parsed INTEGER, talks_extracted INTEGER, updated_at TEXT
);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA)
    return con
