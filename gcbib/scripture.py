"""Scripture href parsing: /study/scriptures/{volume}/{book}/{chapter}?lang=eng&id=p19-p22#p19"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

VOLUMES = {"ot": "Old Testament", "nt": "New Testament", "bofm": "Book of Mormon",
           "dc-testament": "Doctrine and Covenants", "pgp": "Pearl of Great Price"}

BOOKS = {
    # Old Testament
    "gen": "Genesis", "ex": "Exodus", "lev": "Leviticus", "num": "Numbers", "deut": "Deuteronomy", "josh": "Joshua",
    "judg": "Judges", "ruth": "Ruth", "1-sam": "1 Samuel", "2-sam": "2 Samuel", "1-kgs": "1 Kings", "2-kgs": "2 Kings",
    "1-chr": "1 Chronicles", "2-chr": "2 Chronicles", "ezra": "Ezra", "neh": "Nehemiah", "esth": "Esther", "job": "Job",
    "ps": "Psalms", "prov": "Proverbs", "eccl": "Ecclesiastes", "song": "Song of Solomon", "isa": "Isaiah",
    "jer": "Jeremiah", "lam": "Lamentations", "ezek": "Ezekiel", "dan": "Daniel", "hosea": "Hosea", "joel": "Joel",
    "amos": "Amos", "obad": "Obadiah", "jonah": "Jonah", "micah": "Micah", "nahum": "Nahum", "hab": "Habakkuk",
    "zeph": "Zephaniah", "hag": "Haggai", "zech": "Zechariah", "mal": "Malachi",
    # New Testament
    "matt": "Matthew", "mark": "Mark", "luke": "Luke", "john": "John", "acts": "Acts", "rom": "Romans",
    "1-cor": "1 Corinthians", "2-cor": "2 Corinthians", "gal": "Galatians", "eph": "Ephesians", "philip": "Philippians",
    "col": "Colossians", "1-thes": "1 Thessalonians", "2-thes": "2 Thessalonians", "1-tim": "1 Timothy",
    "2-tim": "2 Timothy", "titus": "Titus", "philem": "Philemon", "heb": "Hebrews", "james": "James",
    "1-pet": "1 Peter", "2-pet": "2 Peter", "1-jn": "1 John", "2-jn": "2 John", "3-jn": "3 John", "jude": "Jude",
    "rev": "Revelation",
    # Book of Mormon
    "1-ne": "1 Nephi", "2-ne": "2 Nephi", "jacob": "Jacob", "enos": "Enos", "jarom": "Jarom", "omni": "Omni",
    "w-of-m": "Words of Mormon", "mosiah": "Mosiah", "alma": "Alma", "hel": "Helaman", "3-ne": "3 Nephi",
    "4-ne": "4 Nephi", "morm": "Mormon", "ether": "Ether", "moro": "Moroni", "introduction": "Book of Mormon Introduction",
    "bofm-title": "Book of Mormon Title Page", "three": "Testimony of Three Witnesses", "eight": "Testimony of Eight Witnesses",
    "js": "Testimony of the Prophet Joseph Smith", "explanation": "Brief Explanation about the Book of Mormon",
    # Doctrine and Covenants
    "dc": "Doctrine and Covenants", "od": "Official Declaration",
    # Pearl of Great Price
    "moses": "Moses", "abr": "Abraham", "js-m": "Joseph Smith—Matthew", "js-h": "Joseph Smith—History",
    "a-of-f": "Articles of Faith",
}


def parse_scripture_href(href: str) -> dict:
    """Return {book, chapter, verse_start, verse_end} (any may be None)."""
    out: dict = {"book": None, "chapter": None, "verse_start": None, "verse_end": None}
    u = urlparse(href)
    parts = [p for p in re.sub(r"^/study", "", u.path).split("/") if p]
    if len(parts) < 3 or parts[0] != "scriptures":
        return out
    vol, book = parts[1], parts[2]
    if vol in ("bd", "gs", "tg", "jst", "harmony"):
        return out
    out["book"] = BOOKS.get(book)
    if out["book"] is None:
        out["book"] = book.replace("-", " ").title()
    if len(parts) >= 4 and parts[3].isdigit():
        out["chapter"] = int(parts[3])
    q = parse_qs(u.query)
    ids = unquote(q.get("id", [""])[0])
    nums = [int(n) for n in re.findall(r"p(\d+)", ids)]
    if nums:
        out["verse_start"], out["verse_end"] = min(nums), max(nums)
    return out


def book_name_from_href(href: str, text: str) -> str | None:
    b = parse_scripture_href(href).get("book")
    if b:
        return b
    m = re.match(r"^(.*?)(?:\s+\d+(?::\d+.*)?)?$", text.strip())
    return (m.group(1).strip() if m else text) or None


def _volumes() -> dict[str, str]:
    out, vol = {}, "Old Testament"
    for code, name in BOOKS.items():
        if code == "matt":
            vol = "New Testament"
        elif code == "1-ne":
            vol = "Book of Mormon"
        elif code == "dc":
            vol = "Doctrine and Covenants"
        elif code == "moses":
            vol = "Pearl of Great Price"
        out[name] = vol
    return out


VOLUME_OF_BOOK = _volumes()
