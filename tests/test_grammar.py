"""Regression tests for the free-text citation grammar. Every case is a real footnote shape from the corpus."""
import pytest

from gcbib import grammar
from gcbib.extract import extract_footnote, tokenize, segments


def parse(s, ctx=""):
    return grammar.parse_segment(s, ctx)


@pytest.mark.parametrize("text,author,person,work,wtype", [
    ("C. S. Lewis, Mere Christianity (1952), 174.", "C. S. Lewis", "C. S. Lewis", "Mere Christianity", "book"),
    ("William Shakespeare, The Merchant of Venice, act 4, scene 1, line 184", "William Shakespeare", "William Shakespeare", "The Merchant of Venice", "play"),
    ("Antoine de Saint-Exupéry, The Little Prince, trans. Richard Howard (2000), 63.", "Antoine de Saint-Exupéry", "Antoine de Saint-Exupéry", "The Little Prince", "book"),
    ("Victor Hugo, Les Misérables, trans. Charles E. Wilbour (1992), 1255.", "Victor Hugo", "Victor Hugo", "Les Misérables", "book"),
    ("Neal A. Maxwell, Wherefore, Ye Must Press Forward (1977), 25.", "Neal A. Maxwell", "Neal A. Maxwell", "Wherefore, Ye Must Press Forward", "book"),
    ("Spencer W. Kimball, The Miracle of Forgiveness (1969), 23.", "Spencer W. Kimball", "Spencer W. Kimball", "The Miracle of Forgiveness", "book"),
])
def test_author_title(text, author, person, work, wtype):
    p = parse(text)
    assert p.author == author and p.person_quoted == person
    assert p.work_title == work and p.work_type == wtype and p.is_citation


@pytest.mark.parametrize("text,person,author,work", [
    ("Mahatma Gandhi, in Larry Chang, comp., Wisdom for the Soul (2006), 356.", "Mahatma Gandhi", "Larry Chang", "Wisdom for the Soul"),
    ("Vince Lombardi, in Donald T. Phillips, Run to Win: Vince Lombardi on Coaching and Leadership (2001), 92.", "Vince Lombardi", "Donald T. Phillips", "Run to Win: Vince Lombardi on Coaching and Leadership"),
    ("Nancy Newhall, in Thomas F. Horbein, Everest, the West Ridge, San Francisco: Sierra Club, 1965, pp. 28, 30.", "Nancy Newhall", "Thomas F. Horbein", "Everest, the West Ridge"),
    ("Mother Teresa, in Malcolm Muggeridge, Something Beautiful for God (1971), 72.", "Mother Teresa", "Malcolm Muggeridge", "Something Beautiful for God"),
    ("David O. McKay quoting J. E. McCulloch, Home: The Savior of Civilization (1924), 42", "J. E. McCulloch", "J. E. McCulloch", "Home: The Savior of Civilization"),
])
def test_secondary_source(text, person, author, work):
    p = parse(text)
    assert p.person_quoted == person and p.author == author and p.work_title == work
    assert p.relation == "secondary"


def test_article_in_periodical():
    p = parse("See Susie Steiner, “Top Five Regrets of the Dying,” Guardian, Feb. 1, 2012, www.guardian.co.uk/x.")
    assert p.author == "Susie Steiner" and p.work_title == "Top Five Regrets of the Dying"
    assert p.container_title == "Guardian" and p.work_type == "article" and p.year == 2012 and p.relation == "see"


def test_newspaper_date_not_container():
    p = parse("Brigham Young, “Sermon,” Deseret News, Oct. 31, 1855, 267")
    assert p.container_title == "Deseret News" and p.year == 1855 and p.locator == "267"


def test_hymn():
    p = parse("“Abide with Me!,” Hymns, no. 166")
    assert p.work_title == "Abide with Me!" and p.container_title == "Hymns" and p.work_type == "hymn" and p.locator == "no. 166"


def test_teachings_of_presidents_implies_person():
    p = parse("Teachings of Presidents of the Church: Joseph Smith (2007), 49.")
    assert p.person_quoted == "Joseph Smith" and p.work_type == "manual" and p.locator == "49"


def test_implied_person_for_known_book():
    p = parse("Mere Christianity, 174.")
    assert p.person_quoted == "C. S. Lewis" and p.work_title == "Mere Christianity"


def test_editor_is_not_person_quoted():
    p = parse("C. S. Lewis at the Breakfast Table and Other Reminiscences, ed. James T. Como, New York: Collier Books, 1985, p. 34.",
              "C. S. Lewis wrote, “We cannot mingle with the splendours”")
    assert p.author == "James T. Como" and p.person_quoted == "C. S. Lewis"
    assert p.work_title == "C. S. Lewis at the Breakfast Table and Other Reminiscences"


def test_compilers_after_title():
    p = parse("Words of Joseph Smith, Andrew F. Ehat and Lyndon W. Cook, comps., Provo: BYU Religious Studies Center, 1980, p. 359.")
    assert p.work_title == "Words of Joseph Smith" and p.person_quoted == "Joseph Smith" and p.year == 1980


def test_serial_with_context_attribution():
    p = parse("Journal of Discourses, 15:249.", "As Orson Pratt said about this very matter,")
    assert p.container_title == "Journal of Discourses" and p.locator == "15:249" and p.person_quoted == "Orson Pratt"


def test_conference_report():
    p = parse("Dallin H. Oaks, in Conference Report, Oct. 2007, 113")
    assert p.author == "Dallin H. Oaks" and p.container_title == "Conference Report" and p.year == 2007 and p.relation != "secondary"


def test_cite_tags_with_inner_punctuation():
    p = parse("⟪Rasselas,⟫ ch. 41.")
    assert p.work_title == "Rasselas" and p.locator == "ch. 41"


@pytest.mark.parametrize("text", [
    "The Casper Wyoming Temple was dedicated on November 24, 2024.",
    "The Hodgetts and Hunt wagon companies traveled near the Martin handcart company and also needed to be rescued.",
    "My grandfather Crozier, the son of David Patten, taught me important lessons.",
    "Most of the Willie company left Liverpool, England, on the ship Thornton on May 4, 1856.",
])
def test_prose_is_not_a_citation(text):
    assert not parse(text).is_citation


def test_periodical_is_not_a_person():
    p = parse("Millennial Star, Nov. 15, 1851, 339")
    assert p.author is None and p.container_title == "Millennial Star"
    p = parse("“Love Is Spoken Here,” Children’s Songbook, 190–91")
    assert p.author is None and p.work_type == "hymn"


def test_long_quotation_is_not_a_title():
    p = parse("“I do not think that all who choose wrong roads perish; but their rescue consists in being put back on the right road. … Evil can be undone,” The Great Divorce (1946), 6")
    assert p.work_title == "The Great Divorce"


def test_scripture_links_extracted_from_footnote():
    html = ('<p>See <a class="scripture-ref" href="/study/scriptures/nt/luke/4?lang=eng&amp;id=p18-p19#p18">Luke 4:18–19</a>; '
            '<a class="scripture-ref" href="/study/scriptures/bofm/3-ne/27?lang=eng&amp;id=p14-p16#p14">3 Nephi 27:14–16</a>.</p>')
    cits = extract_footnote(html, "", [])
    assert [c.tier for c in cits] == ["scripture", "scripture"]
    assert cits[0].scripture_book == "Luke" and cits[0].chapter == 4 and cits[0].verse_start == 18 and cits[0].verse_end == 19
    assert cits[1].scripture_book == "3 Nephi" and cits[0].relation == "see"


def test_crossref_talk_uses_link_text_and_uri():
    html = ('<p>Henry B. Eyring, “<a class="cross-ref" href="/study/general-conference/2002/10/rise-to-your-call?lang=eng&amp;id=p9#p9">'
            'Rise to Your Call</a>,” Liahona, Nov. 2002, 76</p>')
    cits = extract_footnote(html, "", [])
    assert len(cits) == 1 and cits[0].tier == "crossref"
    assert cits[0].cited_talk_uri == "/general-conference/2002/10/rise-to-your-call"
    assert cits[0].work_title == "Rise to Your Call" and cits[0].author_name == "Henry B. Eyring" and cits[0].locator == "76"


def test_prose_wrapping_parenthetical_citation_uses_prose_as_context():
    html = ('<p>President Jeffrey R. Holland taught: “Be kind regarding human frailty.” '
            '(“<a class="cross-ref" href="/study/general-conference/2013/04/lord-i-believe?lang=eng">Lord, I Believe</a>,” Liahona, May 2013, 94).</p>')
    cits = extract_footnote(html, "", [])
    assert len(cits) == 1 and cits[0].person_quoted == "Jeffrey R. Holland" and cits[0].work_title == "Lord, I Believe"


def test_short_form_resolves_from_memory():
    first = extract_footnote("<p>C. S. Lewis, Mere Christianity (1952), 174.</p>", "", [])
    second = extract_footnote("<p>Lewis, Mere Christianity, 126.</p>", "", first)
    assert second[0].author_name == "C. S. Lewis" and second[0].person_quoted == "C. S. Lewis"


def test_ibid_copies_previous():
    first = extract_footnote("<p>C. S. Lewis, Mere Christianity (1952), 174.</p>", "", [])
    second = extract_footnote("<p>Ibid., 180.</p>", "", first)
    assert second[0].work_title == "Mere Christianity" and second[0].locator == "180"


def test_editorial_tail_and_alternate_location_are_dropped():
    html = "<p>Thomas S. Monson, in Conference Report, Apr. 1965, 70–71; or Improvement Era, June 1965, 496; emphasis added.</p>"
    cits = extract_footnote(html, "", [])
    assert len(cits) == 1 and cits[0].author_name == "Thomas S. Monson" and cits[0].locator == "70–71"


def test_bare_year_parenthetical_is_not_split_off():
    segs = segments(tokenize("<p>Antoine de Saint-Exupéry, The Little Prince, trans. Richard Howard (2000), 63.</p>"))
    assert len(segs) == 1
