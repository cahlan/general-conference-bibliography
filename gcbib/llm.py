"""Optional LLM fallback: re-parse low-confidence free-text citations with Claude.

Only runs when `gcbib extract --llm` is used. Results are cached in the llm_cache table keyed
by the citation text, so re-runs are free. Requires ANTHROPIC_API_KEY (or `ant auth login`).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3

from pydantic import BaseModel

MODEL = "claude-haiku-4-5"
THRESHOLD = 0.6

SYSTEM = """You extract bibliographic fields from footnotes of religious sermons (LDS general conference talks).
The footnote follows Chicago-style house style. Return the fields exactly as written in the footnote (do not
normalize spelling), or null when absent. `person_quoted` is the person whose words are being quoted (for
"Gandhi, in Larry Chang, comp., Wisdom for the Soul" it is Gandhi and the author is Larry Chang). For
"Teachings of Presidents of the Church: Brigham Young" the person quoted is Brigham Young. `is_citation` is
false for explanatory notes that cite nothing. `relation` is "see" when the note begins with See/Compare,
"secondary" when the words are quoted via another source, else "quoted"."""


class Extraction(BaseModel):
    is_citation: bool
    person_quoted: str | None
    author: str | None
    work_title: str | None
    work_type: str | None          # book | play | poem | hymn | article | talk | manual | speech | web | other
    container_title: str | None
    year: int | None
    locator: str | None
    relation: str                  # quoted | see | secondary


def _client():
    import anthropic
    return anthropic.Anthropic()


def extract_with_claude(client, text: str, context: str) -> Extraction:
    prompt = f"Footnote:\n{text}\n\nSentence in the talk that introduced it (may be empty):\n{context[-500:]}"
    resp = client.messages.parse(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=Extraction,
    )
    return resp.parsed_output


def refine_low_confidence(con: sqlite3.Connection, talk_ids: list[int], threshold: float = THRESHOLD, log=print) -> int:
    client = _client()
    cur = con.cursor()
    q = f"""SELECT c.id, c.raw_text, f.context FROM citations c JOIN footnotes f ON f.id=c.footnote_id
            WHERE c.tier IN ('freetext','note') AND c.confidence < ? AND c.talk_id IN ({','.join('?' * len(talk_ids))})"""
    rows = cur.execute(q, [threshold, *talk_ids]).fetchall()
    log(f"llm: {len(rows)} low-confidence citations to refine with {MODEL}")
    n = 0
    for cid, raw, ctx in rows:
        h = hashlib.sha256((raw + "\n" + (ctx or "")[-500:]).encode()).hexdigest()
        row = cur.execute("SELECT output_json FROM llm_cache WHERE input_hash=?", (h,)).fetchone()
        if row:
            data = json.loads(row[0])
        else:
            try:
                data = extract_with_claude(client, raw, ctx or "").model_dump()
            except Exception as e:  # noqa: BLE001
                log(f"  llm error on citation {cid}: {e}")
                continue
            cur.execute("INSERT OR REPLACE INTO llm_cache(input_hash, model, output_json, created_at) VALUES (?,?,?,?)",
                        (h, MODEL, json.dumps(data), dt.datetime.now().isoformat(timespec="seconds")))
        if not data["is_citation"]:
            cur.execute("UPDATE citations SET tier='note', parser='llm', confidence=0.9 WHERE id=?", (cid,))
        else:
            cur.execute("""UPDATE citations SET tier='freetext', parser='llm', confidence=0.85,
                           person_quoted=COALESCE(?, person_quoted), author_name=COALESCE(?, author_name),
                           work_title=COALESCE(?, work_title), work_type=COALESCE(?, work_type),
                           container_title=COALESCE(?, container_title), year=COALESCE(?, year),
                           locator=COALESCE(?, locator), relation=? WHERE id=?""",
                        (data["person_quoted"], data["author"], data["work_title"], data["work_type"],
                         data["container_title"], data["year"], data["locator"], data["relation"], cid))
        n += 1
        if n % 50 == 0:
            con.commit(); log(f"  refined {n}/{len(rows)}")
    con.commit()
    return n
