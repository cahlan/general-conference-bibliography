# General Conference Reverse Bibliography — Plan

## Why

General conference talks cite thousands of outside sources: scripture, earlier talks, Church manuals, hymns, and
a long tail of books, poems, plays, and articles (C. S. Lewis, Shakespeare, Wordsworth, Saint-Exupéry, Gandhi…).
Nobody has flipped that index around. This project builds a **reverse bibliography**: for every cited author and
work, who cited it, when, and how often. It should answer questions like:

- How many times has C. S. Lewis been quoted, and how has that changed by decade?
- Which of Shakespeare's works are cited most?
- Who were the most-cited non-scripture authors in a given session or year?
- Which earlier conference talks are cited most by later talks?

## What we learned about the source (investigated 2026-10-03)

### There is a clean JSON API behind every page

The talk URL `https://www.churchofjesuschrist.org/study/general-conference/2026/04/13kearon?lang=eng` is a React
app. The same server exposes the content as JSON, which is far easier to parse than the rendered HTML:

| Purpose | Endpoint |
|---|---|
| Table of contents for one conference | `https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/toc?lang=eng&uri=/general-conference/2026/04` |
| One talk | `https://www.churchofjesuschrist.org/study/api/v3/language-pages/type/content?lang=eng&uri=/general-conference/2026/04/13kearon` |

Both respond in ~0.5 s with no auth, no rate limiting observed across ~120 requests. Send a browser-like
`User-Agent`. The JSON contains a few raw control characters, so parse with `json.loads(raw, strict=False)`.

**TOC response** (`entries[]`): each `section` is a session (`title` = "Saturday Morning Session",
`uri`) with `entries[].content = { uri, title, subtitle }`, where `subtitle` is the speaker's name.
Sustainings, audit reports, and statistical reports appear as ordinary entries and need filtering.

**Content response**:

```
meta.title                      talk title
meta.structuredData             JSON string with datePublished and author { name, url }  (recent talks)
content.body                    full talk HTML (header, paragraphs, and a <footer class="notes"> copy of the notes)
content.footnotes               { "note1": { id, marker, pid, text (HTML), referenceUris[] }, ... }
pids                            ordered paragraph ids
```

Each footnote's `pid` is the id of the body paragraph it hangs off, so we can always recover the sentence that
introduced the quote ("C. S. Lewis wrote, …").

`referenceUris[]` is the gift: every hyperlinked reference inside a footnote is already extracted as
`{ type, href, text }`, where `type` is `scripture-ref` or `cross-ref` (links to other talks, manuals, hymns),
and a few untyped entries are external URLs (newsroom articles).

### Markup inside a footnote

| Markup | Meaning | Example |
|---|---|---|
| `<a class="scripture-ref" href="/study/scriptures/nt/eph/2?lang=eng&id=p19-p22#p19">` | Scripture | Ephesians 2:19–22 (book, chapter, verses all in the href) |
| `<a class="cross-ref" href="/study/general-conference/2013/04/lord-i-believe?…">` | Another talk, manual section, hymn | Resolvable to a known talk via our own TOC data |
| `<cite>…</cite>` | Title of a book or periodical | `<cite>Mere Christianity</cite>`, `<cite>Ensign</cite>` |
| `“…”` (curly quotes) | Title of an article, poem, hymn, or chapter | `“Top Five Regrets of the Dying”` |
| Leading `See` | Cited for support rather than quoted | |
| `in` / `as quoted in` / `quoting` | Secondary source | `Mahatma Gandhi, in Larry Chang, comp., <cite>Wisdom for the Soul</cite> (2006), 356.` |

Citations follow Church-magazine house style (a Chicago variant) very consistently:

```
Author, <cite>Book Title</cite> (Year), page.
Author, “Article Title,” <cite>Periodical</cite>, Month Year, page.
Speaker, “Talk Title,” <cite>Liahona</cite>, May 2013, 94.           (cross-ref link on the talk title)
Speaker, in Conference Report, Apr. 1935, 116.
“Hymn Title,” <cite>Hymns</cite>, no. 250.
William Shakespeare, <cite>The Merchant of Venice</cite>, act 4, scene 1, line 184.
```

### Two eras of citation formatting

Sampling one talk per conference from 1971 to 2026:

| Era | How citations appear | Parse strategy |
|---|---|---|
| 1971 – 1995 | **Inline parentheses in the body**: `(C. S. Lewis, <cite>At the Breakfast Table</cite>, p. xxv)`. No footnotes. `<cite>` and `scripture-ref` markup is still present. | Scan body paragraphs for `( … )` groups containing a `<cite>`, a `scripture-ref`, or a quoted title. |
| 1996 – today | **Numbered footnotes** (`content.footnotes`). | Parse each footnote. |
| Mixed | Even post-1996, some talks have zero footnotes and use inline parentheses (e.g. 2006–2010 and 2013 samples). Some talks use both. | Always run both passes on every talk. |

The archive online starts at **April 1971**. Earlier conferences are not on this site. From April 2019 the talk
slugs changed from title-based (`the-gift-of-grace`) to numbered (`16bednar`); the TOC handles this for us.

### Scale

| | |
|---|---|
| Conferences | 111 (Apr 1971 – Apr 2026) |
| TOC entries | 4,267 (roughly 3,800 are actual talks) |
| Footnotes (sample of 111 talks) | 884, about 8 per talk, more like 20 in modern talks |
| Linked references in those footnotes | 697 scripture, 111 cross-ref, 21 external URL |
| Footnotes that are fully machine-linked | 59 % |
| Footnotes with free text to parse (book, article, person) | 41 % |
| Estimated total footnotes | ~30,000, of which ~12,000 need free-text parsing |
| Raw JSON on disk | ~40 KB per talk, ~170 MB total |
| Crawl time, serial at 0.5 s | ~35 minutes |

## Architecture

Five stages, each writing to disk so any stage can be rerun without re-fetching.

```
1. crawl      TOC + content JSON  →  raw/{year}-{month}/{slug}.json         (idempotent cache)
2. parse      raw JSON            →  talks, paragraphs, footnotes (SQLite)
3. extract    footnote / inline   →  citation records: who, what work, where, how (quoted vs see)
4. resolve    citation records    →  canonical authors + works (alias tables)
5. serve      SQLite              →  aggregates JSON  +  simple web UI
```

### Scope selection (works at every stage)

Nothing is all-or-nothing. Every stage takes the same selector and operates only on matching talks, because
the talk URI already encodes the hierarchy and every stage writes to disk keyed by that URI.

```
gcbib crawl   2026/04                       # one conference
gcbib crawl   2026/04 --session saturday-morning
gcbib crawl   2026/04/13kearon              # one talk
gcbib crawl   2019..2026                    # a range of years
gcbib crawl   --speaker holland             # every talk by one speaker (needs TOCs for the range)
gcbib parse   <same selectors>
gcbib extract <same selectors>
gcbib run     <same selectors>              # all stages end to end
```

- The TOC is always fetched per conference (one cached request) and then filtered, so session and speaker
  selectors cost nothing extra.
- A `coverage` table records which conferences are fully parsed. Aggregates and the UI read it and label partial
  coverage, so a half-crawled archive never shows "3 citations all time" as if it were complete.
- Cross-references to talks not yet crawled keep the target URI and resolve to a speaker and title once that
  conference is parsed. Nothing is lost by crawling out of order.
- Running one talk end to end is the intended development loop: pick one talk per decade, run, read the
  `citations` rows, fix the parser, rerun.

### Stage 1 — Crawl

Python script. For each (year, month) from 1971-04 to the current conference, fetch the TOC, then each talk's
content. Cache everything; a `--refresh` flag refetches only the most recent conference (the only one that changes).
Filter out non-talk entries by title pattern (`Sustaining of`, `Audit`, `Statistical Report`, `Church Finance`)
and keep a flag rather than dropping them, so counts can be audited.

### Stage 2 — Parse

Per talk, pull:

- `conference` (year, month), `session` (from the TOC section), `order_in_session`
- `speaker_name` (TOC subtitle), `speaker_role` (`<p class="author-role">`), `title`, `uri`, `date`
- paragraphs with their `id` and plain text
- footnotes: `marker`, `pid`, raw HTML, plain text, and `referenceUris`
- inline parenthetical citation groups from body paragraphs (pre-1996 style), tagged `inline=true`

### Stage 3 — Extract citations

A footnote is not one citation. `note8` in the Kearon talk contains eight scripture references and one manual
reference. Split on `;` and on sentence boundaries, then classify each piece into one of three tiers:

1. **Scripture** (`scripture-ref` href). Parse book/chapter/verse directly from the href. Nothing to guess.
2. **Internal cross-reference** (`cross-ref` href). Parse the target URI. If it is a conference talk we already
   have, link to that talk row (speaker + title come free). If it is a manual or hymn, record the collection and
   section. This gives a **talk-to-talk citation graph** for almost nothing.
3. **Free text** (everything else). Two-pass:
   - **Rule-based grammar** for the house style above: author = text before the first comma that is not inside
     quotes; work = `<cite>` content; container title = quoted text; year = `(\d{4})`; locator = trailing
     `act/scene/line/p./no./vol.` pattern. Detect `See` (support) vs no prefix (quoted). Detect `in` /
     `as quoted in` / `quoting` to split *person quoted* from *source work*. Resolve short forms within a talk
     (`<cite>Discourses</cite>, p. 46` after a full citation of *Discourses of Brigham Young*; `Ibid.`).
   - **LLM fallback** for whatever the grammar cannot confidently parse (expect 20–30 % of free-text items,
     so ~3,000 strings). Use Claude Haiku 4.5 with a strict JSON schema:
     `{ persons_quoted[], author, work_title, container_title, work_type, year, locator, relation: quoted|see|background, is_citation: bool }`.
     Many footnotes are explanatory prose, not citations (`The Casper Wyoming Temple was dedicated on …`);
     `is_citation=false` keeps them out of the counts. Cost is a few dollars.

Keep the raw footnote text and the parser's confidence on every citation row so bad parses are findable.

### Stage 4 — Resolve entities

Counting "C. S. Lewis" requires that `C. S. Lewis`, `C.S. Lewis`, `Lewis` (short form), and `President Gordon B.
Hinckley` vs `Gordon B. Hinckley` collapse to one row each.

- `authors` table with `canonical_name`, `kind` (church_leader | scripture_figure | external), and an
  `author_aliases` table.
- `works` table with `canonical_title`, `author_id`, `work_type` (book | play | poem | hymn | article | talk |
  manual | scripture_book), and `work_aliases`.
- Automatic normalization first (strip titles/honorifics, normalize initials and punctuation, case-fold, drop
  edition/year parentheticals). Then a **hand-curated overrides YAML** for the top ~200 authors and works, which
  is where the real quality comes from. Review the top-500 list by hand once; the long tail can stay noisy.
- Speakers are authors too (so a Holland talk citing Hinckley links two people we already know).

### Stage 5 — Interface

Keep it simple and in two layers:

1. **Datasette over the SQLite file** for exploration while building. Zero front-end code, faceted browsing,
   ad-hoc SQL, CSV export. This is how we check the parse quality.
2. **A static single-page dashboard** (one HTML file plus precomputed JSON aggregates) for the three headline
   questions:
   - **Author page**: citations per conference over time, list of works, every citing talk with the paragraph
     that introduced the quote.
   - **Work page**: same, for a single book/play.
   - **Conference / session view**: pick a year or session; see most-cited authors and works, scripture vs
     non-scripture split.
   - **Leaderboards**: most-cited external authors all-time and by decade; most-cited earlier talks.
   - A search box over author and work names.

   Static means it can be hosted anywhere (GitHub Pages, S3) and rebuilt in seconds after each conference.

Scripture dominates every count (roughly 80 % of linked references), so the UI should default to
**non-scripture** views with scripture available as its own tab, or the answer to every question is "Matthew."

## Data model (SQLite)

```
conferences(id, year, month, title)
sessions(id, conference_id, title, order)
talks(id, uri, conference_id, session_id, order, title, speaker_id, speaker_role, date, is_talk, raw_path)
paragraphs(id, talk_id, pid, order, text)
footnotes(id, talk_id, marker, pid, raw_html, text, inline)
citations(id, footnote_id, talk_id, position, tier, relation, raw_text, author_id, person_quoted_id, work_id,
          container_work_id, locator, year, cited_talk_id, scripture_book, chapter, verse_start, verse_end,
          parser, confidence)
authors(id, canonical_name, kind)       author_aliases(alias, author_id)
works(id, canonical_title, author_id, work_type)   work_aliases(alias, work_id)
```

## Tech choices

- **Python 3** for the pipeline (requests, BeautifulSoup/lxml, sqlite3, pydantic for the LLM schema). Already
  proven against this API during investigation.
- **SQLite** as the one source of truth. Small enough to commit.
- **Claude Haiku 4.5** via the Claude API for free-text fallback, batched, cached by input string.
- **Datasette** for exploration; **plain HTML + a small chart library** for the dashboard.

## Risks and open questions

- **Parse quality is the whole product.** Budget time for a hand-labeled validation set (~200 footnotes across
  eras) and measure precision/recall of author and work extraction before trusting any leaderboard.
- **Quoted-person vs. source-work.** "Gandhi in Larry Chang, comp., Wisdom for the Soul" must count for Gandhi,
  not Chang. The grammar handles the common `in` pattern; the LLM handles the rest.
- **Body-text attributions without a footnote.** Pre-1996 talks sometimes name the author in prose and cite only
  the work in parentheses. Use the paragraph text (via `pid`) as context for both the grammar and the LLM.
- **Multi-language.** Everything here is `lang=eng`. Not a goal.
- **Pre-1971 conferences** are not on this site. If wanted later, the Conference Report scans on archive.org are
  a separate, OCR-heavy project.
- **Terms of use.** This is read-only fetching of public pages for personal research at ~2 requests/second. Cache
  aggressively and never re-crawl what has not changed.

## Build order

1. Crawler + raw cache (half a day, then 35 minutes of fetching).
2. Parser into SQLite, including inline-parenthetical pass. Load Datasette and eyeball a dozen talks per decade.
3. Scripture and cross-ref tiers (purely mechanical; gets us the talk-to-talk graph immediately).
4. Rule-based free-text grammar; measure coverage; label the validation set.
5. LLM fallback for the residue; re-measure.
6. Entity resolution plus the curated overrides file for the top 200.
7. Aggregates JSON and the static dashboard.
8. A `refresh` command to pull the newest conference and rebuild, run twice a year.

## Status (2026-10-03)

Built end to end; see `README.md` for commands. The full archive (4,060 talks, 111 conferences) is crawled,
parsed, and extracted. Remaining quality work, in priority order: hand-label a validation set of ~200 footnotes
and measure author/work precision and recall; run the Claude fallback (`extract --llm`) on low-confidence
free-text parses; grow `data/overrides.yaml` from the top-500 persons and works.
