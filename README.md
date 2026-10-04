# General Conference Reverse Bibliography

Who gets quoted in LDS general conference? This project crawls every talk published online
(April 1971 to the present), pulls apart every footnote and inline citation, and turns the result
inside out: for each author and work, which talks cited it, when, and how often.

It answers questions like *How many times has C. S. Lewis been quoted, by decade?*,
*Which of Shakespeare's plays are cited most?*, and *Who were the most-quoted authors in a given
session or year?* See `PLAN.md` for the design and the investigation that led to it.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install beautifulsoup4 lxml pyyaml requests pytest anthropic
```

## Commands

Every command takes the same **scope selector** so you can work on one talk, one session,
one conference, a year range, or everything:

```sh
.venv/bin/python -m gcbib list    2026/04 --session saturday-morning   # what a selector matches
.venv/bin/python -m gcbib run     2026/04/13kearon                     # one talk, all stages
.venv/bin/python -m gcbib run     2019..2026                           # a range of years
.venv/bin/python -m gcbib run     all                                  # the whole archive (~10 min)
.venv/bin/python -m gcbib run     --speaker holland                    # every talk by one speaker
.venv/bin/python -m gcbib status                                       # coverage per conference
.venv/bin/python -m gcbib serve                                        # dashboard at http://127.0.0.1:8765/
```

`run` is `crawl` → `parse` → `extract` → `resolve` → `aggregate`. Each stage is also its own
command and takes the same selector. `resolve` and `aggregate` always work on the whole database.

| Stage | What it does | Writes |
|---|---|---|
| `crawl` | Fetches conference tables of contents and talk JSON from the Gospel Library API | `raw/YYYY-MM/*.json` (cached; `--refresh` refetches) |
| `parse` | Talk metadata, paragraphs, numbered footnotes, and inline parenthetical citations | `talks`, `paragraphs`, `footnotes` tables |
| `extract` | Splits each footnote into citations: scripture (from hrefs), cross-references to other talks and manuals (from hrefs), and free text (rule-based grammar) | `citations` table |
| `resolve` | Merges spelling variants of names and titles; applies `data/overrides.yaml` | `authors`, `works`, alias tables |
| `aggregate` | Precomputes everything the dashboard needs | `site/data/*.json` |

Add `--llm` to `extract` or `run` to re-parse low-confidence free-text citations with Claude
(Haiku 4.5, cached in the database; needs `ANTHROPIC_API_KEY` or `ant auth login`).

## Layout

```
gcbib/
  crawl.py       Gospel Library API client and on-disk cache
  selectors.py   scope selector grammar and the non-talk filter (sustainings, audit reports)
  parse.py       raw JSON -> SQLite (talks, paragraphs, footnotes incl. inline citations)
  extract.py     footnote -> citation segments -> tiers (scripture / crossref / freetext / note)
  grammar.py     rule-based parser for Chicago-style free-text citations
  scripture.py   scripture href parsing and book names
  resolve.py     author and work normalization, overrides
  aggregate.py   static JSON for the dashboard
  llm.py         optional Claude fallback for low-confidence citations
  cli.py, cli_more.py
data/
  gcbib.sqlite   the database (source of truth; gitignored)
  overrides.yaml hand-curated aliases for authors and works
site/
  index.html     the dashboard (single page, vanilla JS + Chart.js)
  data/          generated JSON (gitignored)
tests/           grammar regression tests (`.venv/bin/python -m pytest -q tests`)
```

## How a citation is counted

- A **citation** is one reference inside one footnote (or inline parenthetical). A footnote listing
  eight scripture passages yields eight scripture citations.
- `tier` is `scripture`, `crossref` (a hyperlink to another talk, manual, or hymn), `freetext`
  (parsed from the words), or `note` (explanatory prose; excluded from counts).
- `person_quoted` is whose words are used; `author_name` is who wrote the cited work. For
  "Gandhi, in Larry Chang, comp., *Wisdom for the Soul*" they differ. Leaderboards use `person_quoted`.
- `relation` is `quoted`, `see` (introduced by "See"), or `secondary` (quoted via another source).
- `confidence` is the parser's self-assessment; the dashboard flags anything under 0.6.

## Inspecting the data

The SQLite file works with any tool. For faceted browsing without writing SQL:

```sh
.venv/bin/pip install datasette && .venv/bin/datasette data/gcbib.sqlite
```

Useful queries live in `PLAN.md`'s data-model section; for example, C. S. Lewis by decade:

```sql
SELECT (c.year/10)*10 AS decade, COUNT(*) FROM citations ci
JOIN authors a ON a.id = ci.person_quoted_id
JOIN talks t ON t.id = ci.talk_id JOIN conferences c ON c.id = t.conference_id
WHERE a.canonical_name = 'C. S. Lewis' AND ci.tier != 'note' GROUP BY decade;
```

## Publishing the dashboard

`aggregate` also writes `site/artifact.html`, the same page without the document wrapper. To publish or
refresh the shared copy on claude.ai, ask Claude to publish `site/artifact.html` with `site/data/index.json`
and `site/data/citations.json` as its files (the existing artifact URL keeps the same link). The page and
both data files total about 10 MB, well under the artifact limits.

## Keeping it current

After each conference:

```sh
.venv/bin/python -m gcbib run 2026/10 --refresh
```

Only the new conference is fetched; `resolve` and `aggregate` rebuild from the whole database.
