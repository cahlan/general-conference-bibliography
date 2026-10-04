"""Registers the parse / extract / resolve / aggregate / run / status / serve commands."""
from __future__ import annotations

import http.server
import json
import os
import sys
from pathlib import Path

from .db import connect

SITE_DIR = Path(__file__).resolve().parent.parent / "site"


def _talk_ids(con, refs):
    uris = [r.uri for r in refs]
    ids = []
    for i in range(0, len(uris), 500):
        chunk = uris[i:i + 500]
        q = f"SELECT id FROM talks WHERE uri IN ({','.join('?' * len(chunk))})"
        ids += [r[0] for r in con.execute(q, chunk)]
    return ids


def register(sub, add_scope, scope):
    def cmd_parse(args):
        from .parse import parse_many
        refs = scope(args)
        con = connect()
        n = parse_many(con, refs)
        print(f"parsed {n} talks", file=sys.stderr)

    def cmd_extract(args):
        from .extract import extract_many
        refs = scope(args)
        con = connect()
        ids = _talk_ids(con, refs)
        n = extract_many(con, ids)
        print(f"extracted {n} citations from {len(ids)} talks", file=sys.stderr)
        if getattr(args, "llm", False):
            from .llm import refine_low_confidence
            refine_low_confidence(con, ids)
        print("note: the dashboard reads site/data; run `gcbib resolve && gcbib aggregate` (or use `gcbib run`) to refresh it,"
              " then reload the page", file=sys.stderr)

    def cmd_resolve(args):
        from .resolve import resolve_all
        con = connect()
        resolve_all(con)

    def cmd_aggregate(args):
        from .aggregate import build_site_data
        con = connect()
        build_site_data(con, SITE_DIR / "data")

    def cmd_run(args):
        from . import crawl as crawl_mod
        from .parse import parse_many
        from .extract import extract_many
        from .resolve import resolve_all
        from .aggregate import build_site_data
        refs = scope(args)
        crawl_mod.crawl(refs, refresh=getattr(args, "refresh", False))
        con = connect()
        parse_many(con, refs)
        ids = _talk_ids(con, refs)
        extract_many(con, ids)
        if getattr(args, "llm", False):
            from .llm import refine_low_confidence
            refine_low_confidence(con, ids)
        resolve_all(con)
        build_site_data(con, SITE_DIR / "data")

    def cmd_status(args):
        con = connect()
        rows = con.execute("""SELECT c.year, c.month, cv.talks_total, cv.talks_parsed, cv.talks_extracted,
                                     (SELECT COUNT(*) FROM citations ci JOIN talks t ON t.id=ci.talk_id WHERE t.conference_id=c.id AND ci.tier!='note') n
                              FROM conferences c LEFT JOIN coverage cv ON cv.conference_id=c.id ORDER BY c.year, c.month""").fetchall()
        for r in rows:
            print(f"{r['year']}/{r['month']:02d}  talks={r['talks_total'] or 0:3d} parsed={r['talks_parsed'] or 0:3d} extracted={r['talks_extracted'] or 0:3d} citations={r['n']}")
        tot = con.execute("SELECT tier, COUNT(*) FROM citations GROUP BY tier").fetchall()
        print("citations by tier:", {r[0]: r[1] for r in tot})

    def cmd_sample(args):
        """Print random free-text citations with their parse, for eyeballing quality."""
        con = connect()
        where = "c.tier IN ('freetext','crossref')" if args.tier == "all" else f"c.tier='{args.tier}'"
        if args.low:
            where += " AND c.confidence < 0.6"
        rows = con.execute(f"""SELECT c.raw_text, c.person_quoted, c.author_name, c.work_title, c.work_type, c.container_title,
                                      c.locator, c.year, c.relation, c.confidence, t.uri FROM citations c JOIN talks t ON t.id=c.talk_id
                               WHERE {where} ORDER BY random() LIMIT ?""", (args.n,)).fetchall()
        for r in rows:
            print(f"‹{r['raw_text'][:160]}›")
            print(f"    person={r['person_quoted']!r} author={r['author_name']!r} work={r['work_title']!r} type={r['work_type']} "
                  f"in={r['container_title']!r} loc={r['locator']!r} year={r['year']} rel={r['relation']} conf={r['confidence']:.1f}  {r['uri']}")

    def cmd_serve(args):
        os.chdir(SITE_DIR)
        handler = http.server.SimpleHTTPRequestHandler
        with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as httpd:
            print(f"serving {SITE_DIR} at http://127.0.0.1:{args.port}/")
            httpd.serve_forever()

    for name, fn, help_ in [("parse", cmd_parse, "raw JSON -> SQLite talks/paragraphs/footnotes"),
                            ("extract", cmd_extract, "footnotes -> citations"),
                            ("run", cmd_run, "crawl + parse + extract + resolve + aggregate")]:
        p = sub.add_parser(name, help=help_); add_scope(p)
        p.add_argument("--llm", action="store_true", help="refine low-confidence free-text citations with Claude")
        if name == "run":
            p.add_argument("--refresh", action="store_true")
        p.set_defaults(fn=fn)
    p = sub.add_parser("resolve", help="normalize authors and works (whole database)"); p.set_defaults(fn=cmd_resolve)
    p = sub.add_parser("aggregate", help="write site/data/*.json (whole database)"); p.set_defaults(fn=cmd_aggregate)
    p = sub.add_parser("status", help="coverage per conference"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("sample", help="print random parsed citations for quality review")
    p.add_argument("-n", type=int, default=30); p.add_argument("--tier", default="freetext", choices=["freetext", "crossref", "note", "all"])
    p.add_argument("--low", action="store_true", help="only low-confidence parses"); p.set_defaults(fn=cmd_sample)
    p = sub.add_parser("serve", help="serve the dashboard locally"); p.add_argument("--port", type=int, default=8765); p.set_defaults(fn=cmd_serve)
