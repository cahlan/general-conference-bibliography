"""Command-line entry point. Every command takes the same scope selector."""
from __future__ import annotations

import argparse
import sys

from . import crawl as crawl_mod
from .selectors import select


def add_scope(p: argparse.ArgumentParser) -> None:
    p.add_argument("selector", nargs="?", default="all",
                   help="all | 2026 | 2019..2026 | 2026/04 | 2026/04/13kearon")
    p.add_argument("--session", help="filter: session title contains TEXT")
    p.add_argument("--speaker", help="filter: speaker name contains TEXT")
    p.add_argument("--include-non-talks", action="store_true",
                   help="keep sustainings, audit and statistical reports")


def scope(args) -> list:
    return select(args.selector, session=args.session, speaker=args.speaker,
                  include_non_talks=args.include_non_talks,
                  refresh_toc=getattr(args, "refresh", False))


def cmd_list(args):
    refs = scope(args)
    for r in refs:
        print(f"{r.year}/{r.month:02d}  {r.session:28s} {r.speaker:28s} {r.title[:60]}  {r.uri}")
    print(f"{len(refs)} talks", file=sys.stderr)


def cmd_crawl(args):
    refs = scope(args)
    crawl_mod.crawl(refs, refresh=args.refresh, workers=args.workers)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gcbib", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="show the talks a selector matches"); add_scope(p); p.set_defaults(fn=cmd_list)
    p = sub.add_parser("crawl", help="fetch raw JSON into raw/"); add_scope(p)
    p.add_argument("--refresh", action="store_true", help="refetch even if cached")
    p.add_argument("--workers", type=int, default=4)
    p.set_defaults(fn=cmd_crawl)

    try:
        from . import cli_more  # later stages register themselves here
        cli_more.register(sub, add_scope, scope)
    except ImportError:
        pass

    args = ap.parse_args(argv)
    args.fn(args)
