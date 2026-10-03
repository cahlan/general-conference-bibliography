"""Rule-based parser for free-text citations in Church-magazine house style.

Input is a "marked" segment produced by extract.tokenize(): hyperlinks have been replaced
by placeholders (⟦S0⟧ scripture, ⟦X1⟧ cross-ref, ⟦U2⟧ external URL) and <cite> titles are
wrapped in ⟪…⟫. Curly quotes “…” wrap article / poem / hymn / talk titles.

<cite> markup is only present in the early 1970s and from 2019 on, so the parser mostly
works from the comma-separated structure of the citation:

    Author, Book Title (Year), page.
    Author, Book Title, City: Publisher, Year, p. 12.
    Author, “Article Title,” Periodical, Month Year, page.
    Person, in Compiler, comp., Anthology (Year), page.       <- person quoted vs. work author
    “Hymn Title,” Hymns, no. 250.
    William Shakespeare, The Merchant of Venice, act 4, scene 1, line 184.
    Journal of Discourses, 15:249.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

PERIODICALS = {
    "ensign", "liahona", "new era", "improvement era", "friend", "the friend", "church news", "deseret news",
    "deseret news church news", "conference report", "journal of discourses", "times and seasons",
    "millennial star", "latter-day saint millennial star", "relief society magazine", "byu studies",
    "byu studies quarterly", "juvenile instructor", "instructor", "the instructor", "elders' journal",
    "elders’ journal", "evening and morning star", "the evening and the morning star", "messenger and advocate",
    "latter day saints' messenger and advocate", "deseret weekly", "deseret evening news",
    "salt lake tribune", "salt lake daily herald", "salt lake herald", "new york times", "the new york times",
    "guardian", "the guardian", "wall street journal", "the wall street journal", "washington post",
    "the washington post", "time", "newsweek", "reader's digest", "reader’s digest", "readers digest",
    "harvard business review", "atlantic", "the atlantic", "atlantic monthly", "the economist", "forbes", "fortune",
    "usa today", "los angeles times", "chicago tribune", "christian science monitor", "the christian science monitor",
    "national geographic", "scientific american", "psychology today", "u.s. news & world report", "imprimis",
    "first things", "christianity today", "the annals of iowa", "annals of iowa", "church history", "dialogue",
    "sunstone", "the saturday evening post", "saturday evening post", "ladies' home journal", "harper's",
    "harper's magazine", "the new yorker", "new yorker", "life", "look", "newsroom", "tambuli", "children's friend",
    "the children's friend", "young woman's journal", "contributor", "the contributor", "woman's exponent",
    "relief society bulletin", "church section", "deseret news church section", "ensign or liahona",
    "liahona or ensign", "new york times magazine", "journal of the american medical association", "jama",
    "the lancet", "nature", "science", "the week", "the times", "london times", "daily telegraph", "bbc news",
    "cnn", "npr", "associated press", "reuters", "church news and events", "meridian magazine", "byu speeches",
    "speeches", "brigham young university speeches", "byu devotional", "religious educator", "the religious educator",
}
HYMNALS = {"hymns", "hymns of the church of jesus christ of latter-day saints", "children's songbook",
           "children’s songbook", "deseret sunday school songs", "latter-day saint hymns", "hymns for home and church",
           "sacred hymns and spiritual songs"}
MANUAL_HINTS = ("teachings of presidents of the church", "general handbook", "handbook", "preach my gospel",
                "gospel principles", "true to the faith", "for the strength of youth", "come, follow me",
                "doctrines of the gospel", "gospel topics", "guide to the scriptures", "bible dictionary",
                "topical guide", "student manual", "institute", "seminary", "melchizedek priesthood", "relief society",
                "primary", "sunday school", "young women", "young men", "aaronic priesthood", "lesson manual")
KNOWN_SERIALS = {   # multi-volume serials cited as "Title, vol:page": containers, words belong to the person quoted
    "journal of discourses", "conference report", "times and seasons", "millennial star", "messenger and advocate",
    "the joseph smith papers", "joseph smith papers", "encyclopedia of mormonism", "church history in the fulness of times",
    "history of the church", "documentary history of the church", "dhc", "hc",
}
IMPLIED_PERSON = {   # compilations whose words belong to one person
    "teachings of the prophet joseph smith": "Joseph Smith", "words of joseph smith": "Joseph Smith",
    "the words of joseph smith": "Joseph Smith", "the personal writings of joseph smith": "Joseph Smith",
    "personal writings of joseph smith": "Joseph Smith", "lectures on faith": "Joseph Smith",
    "discourses of brigham young": "Brigham Young", "gospel doctrine": "Joseph F. Smith",
    "doctrines of salvation": "Joseph Fielding Smith", "answers to gospel questions": "Joseph Fielding Smith",
    "gospel ideals": "David O. McKay", "the miracle of forgiveness": "Spencer W. Kimball",
    "faith precedes the miracle": "Spencer W. Kimball", "the teachings of spencer w. kimball": "Spencer W. Kimball",
    "teachings of ezra taft benson": "Ezra Taft Benson", "the teachings of ezra taft benson": "Ezra Taft Benson",
    "teachings of gordon b. hinckley": "Gordon B. Hinckley", "the teachings of harold b. lee": "Harold B. Lee",
    "the teachings of lorenzo snow": "Lorenzo Snow", "the teachings of george albert smith": "George Albert Smith",
    "mere christianity": "C. S. Lewis", "the screwtape letters": "C. S. Lewis", "the weight of glory": "C. S. Lewis",
    "the great divorce": "C. S. Lewis", "the problem of pain": "C. S. Lewis", "the four loves": "C. S. Lewis",
    "surprised by joy": "C. S. Lewis", "a grief observed": "C. S. Lewis", "the abolition of man": "C. S. Lewis",
    "the pilgrim's progress": "John Bunyan", "the pilgrim’s progress": "John Bunyan", "paradise lost": "John Milton",
    "the divine comedy": "Dante Alighieri", "les misérables": "Victor Hugo", "les miserables": "Victor Hugo",
    "a christmas carol": "Charles Dickens", "the imitation of christ": "Thomas à Kempis",
    "man's search for meaning": "Viktor E. Frankl", "man’s search for meaning": "Viktor E. Frankl",
    "the little prince": "Antoine de Saint-Exupéry", "the book of mormon": None, "the holy bible": None,
    **{'hamlet': 'William Shakespeare', 'macbeth': 'William Shakespeare', 'king lear': 'William Shakespeare', 'othello': 'William Shakespeare', 'the tempest': 'William Shakespeare', 'julius caesar': 'William Shakespeare', 'romeo and juliet': 'William Shakespeare', 'the merchant of venice': 'William Shakespeare', 'as you like it': 'William Shakespeare', 'measure for measure': 'William Shakespeare', 'henry v': 'William Shakespeare', 'henry the fifth': 'William Shakespeare', 'king henry v': 'William Shakespeare', 'the life of king henry v': 'William Shakespeare', 'richard iii': 'William Shakespeare', 'richard the third': 'William Shakespeare', 'henry viii': 'William Shakespeare', 'king henry viii': 'William Shakespeare', 'the two gentlemen of verona': 'William Shakespeare', 'two gentlemen of verona': 'William Shakespeare', 'much ado about nothing': 'William Shakespeare', 'twelfth night': 'William Shakespeare', "a midsummer night's dream": 'William Shakespeare', 'a midsummer night’s dream': 'William Shakespeare', 'the taming of the shrew': 'William Shakespeare', 'coriolanus': 'William Shakespeare', 'antony and cleopatra': 'William Shakespeare', 'troilus and cressida': 'William Shakespeare', 'timon of athens': 'William Shakespeare', 'cymbeline': 'William Shakespeare', "the winter's tale": 'William Shakespeare', 'the winter’s tale': 'William Shakespeare', 'richard ii': 'William Shakespeare', 'henry iv': 'William Shakespeare', 'henry iv, part 1': 'William Shakespeare', 'henry iv, part 2': 'William Shakespeare', 'henry vi': 'William Shakespeare', 'king john': 'William Shakespeare', "love's labour's lost": 'William Shakespeare', 'love’s labour’s lost': 'William Shakespeare', 'the comedy of errors': 'William Shakespeare', 'titus andronicus': 'William Shakespeare', 'pericles': 'William Shakespeare', "all's well that ends well": 'William Shakespeare', 'all’s well that ends well': 'William Shakespeare', 'the merry wives of windsor': 'William Shakespeare', 'the rape of lucrece': 'William Shakespeare', 'sonnets': 'William Shakespeare', "shakespeare's sonnets": 'William Shakespeare', 'shakespeare’s sonnets': 'William Shakespeare', 'the tragedy of hamlet': 'William Shakespeare', 'the tragedy of macbeth': 'William Shakespeare', 'the tragedy of king lear': 'William Shakespeare', 'the tragedy of julius caesar': 'William Shakespeare', 'the tragedy of romeo and juliet': 'William Shakespeare', 'the complete works of william shakespeare': 'William Shakespeare', 'the complete works of shakespeare': 'William Shakespeare', 'the divine comedy': 'Dante Alighieri', 'inferno': 'Dante Alighieri', 'paradiso': 'Dante Alighieri', 'purgatorio': 'Dante Alighieri', 'the odyssey': 'Homer', 'the iliad': 'Homer', 'the aeneid': 'Virgil', 'the republic': 'Plato', 'the brothers karamazov': 'Fyodor Dostoevsky', 'crime and punishment': 'Fyodor Dostoevsky', 'war and peace': 'Leo Tolstoy', 'anna karenina': 'Leo Tolstoy', 'a tale of two cities': 'Charles Dickens', 'great expectations': 'Charles Dickens', 'david copperfield': 'Charles Dickens', 'oliver twist': 'Charles Dickens', 'the chronicles of narnia': 'C. S. Lewis', 'the lion, the witch and the wardrobe': 'C. S. Lewis', 'the lion, the witch, and the wardrobe': 'C. S. Lewis', "the magician's nephew": 'C. S. Lewis', 'the magician’s nephew': 'C. S. Lewis', 'the last battle': 'C. S. Lewis', 'the silver chair': 'C. S. Lewis', 'prince caspian': 'C. S. Lewis', 'the voyage of the dawn treader': 'C. S. Lewis', 'the horse and his boy': 'C. S. Lewis', 'the lord of the rings': 'J. R. R. Tolkien', 'the hobbit': 'J. R. R. Tolkien', 'the fellowship of the ring': 'J. R. R. Tolkien', 'the two towers': 'J. R. R. Tolkien', 'the return of the king': 'J. R. R. Tolkien', 'walden': 'Henry David Thoreau', 'self-reliance': 'Ralph Waldo Emerson', 'leaves of grass': 'Walt Whitman', 'the road not taken': 'Robert Frost', 'the hound of heaven': 'Francis Thompson', 'invictus': 'William Ernest Henley', 'if—': 'Rudyard Kipling', 'if': 'Rudyard Kipling', 'the prophet': 'Kahlil Gibran', 'the alchemist': 'Paulo Coelho', 'the art of war': 'Sun Tzu', 'the analects': 'Confucius', 'meditations': 'Marcus Aurelius', 'the confessions': 'Saint Augustine', 'confessions': 'Saint Augustine', 'the city of god': 'Saint Augustine', 'summa theologica': 'Thomas Aquinas', 'the institutes of the christian religion': 'John Calvin', 'the cost of discipleship': 'Dietrich Bonhoeffer', 'the imitation of christ': 'Thomas à Kempis', 'the practice of the presence of god': 'Brother Lawrence', 'pensées': 'Blaise Pascal', 'pensees': 'Blaise Pascal', 'the screwtape letters': 'C. S. Lewis'}
}
PLAY_HINT = re.compile(r"\b(act|scene)\s+[\divxlc]+", re.I)
POEM_HINT = re.compile(r"\b(lines?|stanza|canto|verse)\s+\d", re.I)
ROLE_RE = re.compile(r"^(?:(?P<role>ed|eds|comp|comps|trans|rev|sel|arr|adapt)\.?\s+(?P<name>.+)|(?P<name2>.+?),?\s+(?P<role2>ed|eds|comp|comps|trans|rev|sel|arr|adapt)\.?|(?P<bare>ed|eds|comp|comps|trans|rev|sel|arr|adapt|editor|editors|compiler|compilers|translator|translators)\.?)$", re.I)
EDITION_RE = re.compile(r"^(?:\d+(?:st|nd|rd|th)|rev\.?|revised|new|enl\.?|enlarged|abridged|centennial|deluxe|collector's|collector’s|illustrated|updated|expanded|classic|anniversary|paperback|reprint|facsimile|standard|authorized)\s+(?:and\s+\w+\s+)?ed(?:ition|\.)?$|^ed\.$", re.I)
MONTHS = r"(?:Jan|Feb|Mar|Apr|May|June?|July?|Aug|Sept?|Oct|Nov|Dec|Spring|Summer|Fall|Autumn|Winter)[a-z]*\.?"
DATE_RE = re.compile(rf"^(?:{MONTHS}(?:\s*[–/-]\s*{MONTHS})?\s*(?:\d{{1,2}}(?:\s*[–-]\s*\d{{1,2}})?,?\s*)?(1[5-9]\d\d|20[0-2]\d)|\d{{1,2}}\s+{MONTHS}\s+(1[5-9]\d\d|20[0-2]\d))\.?$", re.I)
YEAR_RE = re.compile(r"\b(1[5-9]\d\d|20[0-2]\d)\b")
YEAR_ONLY_RE = re.compile(r"^[\[(]?\s*(?:c\.|ca\.|circa)?\s*(1[5-9]\d\d|20[0-2]\d)(?:\s*[–-]\s*\d{2,4})?\s*[\])]?\.?$")
LOCATOR_START = re.compile(r"^(?:pp?|vol|vols|no|nos|chap|chapter|chs?|sec|section|act|scene|lines?|stanza|bk|book|part|pt|verse|vv?|par|para|paragraph|note|n|fn|col|column|entry|canto|letter|lesson|unit|lecture|session|disc|track)(?:\.\s*|\s+)[\divxlcIVXLC]+\b", re.I)
NUMERIC_LOC = re.compile(r"^\d+(?:[:.–-]\d+)*(?:\s*,\s*\d+(?:[:.–-]\d+)*)*\.?$|^[ivxlc]+(?:[–-][ivxlc]+)?\.?$")
PAREN_YEAR = re.compile(r"\s*[\[(]\s*(?:c\.|ca\.|circa)?\s*(1[5-9]\d\d|20[0-2]\d)(?:\s*[–-]\s*\d{2,4})?\s*[\])]")
PUB_KEYWORD = re.compile(r"\b(Press|Books?|Publish\w*|House|Co\.|Company|Inc\.?|Ltd\.?|Sons|University|Office|Center|Centre|Society|Union|Board|Club|Library|Institute|Foundation|Association|Deseret Book|Bookcraft|Harper\w*|Random House|Penguin|Macmillan|Scribner\w*|Doubleday|Norton|Zondervan|Eerdmans|Collier|Knopf|Viking|Bantam|Dover|Ballantine|Signet|Dell|Putnam\w*|Dutton|Holt|Lippincott|Little, Brown|Houghton|Mifflin|Crowell|Revell|Baker|Moody|Nelson|Crossway|Tyndale|InterVarsity|Augsburg|Fortress|Westminster|Abingdon|Beacon|Basic Books|Free Press|Crown|Hachette|Hyperion|Simon|Schuster|Wiley|McGraw|Prentice|Pearson|Routledge|Blackwell|Vintage|Anchor|Mentor|Everyman|Bobbs|Grosset|Rinehart|Harcourt|Brace|Collins|Fontana|Faber|Hodder|Methuen|Longman\w*|Bles|Hendrickson|Kregel|Bethany|Multnomah|Shadow Mountain|Covenant|Cedar Fort|Signature|Intellectual Reserve|Religious Studies Center|Church Historian|Juvenile Instructor|Sunday School Union|Shambhala|Jossey-Bass|Portfolio|Public Affairs|Palgrave|Springer|Elsevier|Academic|Gallimard|Seuil|Mondadori|Planeta|Alfaguara|Paulist|Orbis|Ignatius|Regnery|Encounter|Modern Library|Loeb|World Publishing|Meridian|Oxford|Cambridge|Yale|Harvard|Princeton|Chicago|Columbia|Stanford|BYU|Brigham Young University|Religious Tract|Bible Society)\b")
KNOWN_CITIES = re.compile(r"^(?:Salt Lake City|New York|Provo|Boston|London|Chicago|San Francisco|Grand Rapids|Philadelphia|Princeton|Cambridge|Oxford|New Haven|Los Angeles|Washington|Nashville|Wheaton|Downers Grove|Minneapolis|Garden City|Englewood Cliffs|Harmondsworth|Toronto|Edinburgh|Dublin|Paris|Berlin|Independence|Logan|Ogden|Orem|American Fork|Springville|Bountiful|Sandy|St\. Louis|Kansas City|Cleveland|Detroit|Atlanta|Dallas|Houston|Denver|Seattle|Portland|Baltimore|Pittsburgh|Cincinnati|Indianapolis|Milwaukee|Richmond|Hartford|Ithaca|Berkeley|Stanford|Chapel Hill|Durham|Ann Arbor|Urbana|Madison|Lincoln|Norman|Austin|Tucson|Albuquerque|Boulder|Lawrence|Iowa City|Baton Rouge|Louisville|Lexington|Columbus|Bloomington|Notre Dame|Colorado Springs|Carol Stream|Eugene|Peabody|Old Tappan|Westwood|Waco|Macon|Mahwah|Maryknoll|Collegeville|Fort Worth|Charlotte|Sydney|Melbourne|Auckland|Mexico City|Tokyo|Geneva|Rome|Madrid|Amsterdam|Vienna|Stockholm|Jerusalem|Liverpool|Manchester|Glasgow|Bristol|Westport|Lanham|Lincolnwood|Franklin|Brentwood|Ventura|Glendale|Pasadena|Santa Barbara|San Diego|Sacramento|Oakland|Palo Alto|Menlo Park|Reading|Totowa|Hoboken|Newark|Trenton|Camden|Albany|Buffalo|Rochester|Syracuse|Brooklyn|Bronx|Queens|Hollywood|Burbank|Anaheim|Irvine|Riverside|Fresno|Spokane|Tacoma|Boise|Helena|Billings|Cheyenne|Casper|Laramie|Omaha|Wichita|Topeka|Tulsa|Oklahoma City|Little Rock|Memphis|Knoxville|Chattanooga|Birmingham|Montgomery|Mobile|Jacksonville|Tampa|Orlando|Miami|Savannah|Charleston|Raleigh|Norfolk|Arlington|Alexandria|Annapolis|Wilmington|Dover|Harrisburg|Scranton|Allentown|Bethlehem|Lancaster|Gettysburg|Erie|Akron|Toledo|Dayton|Youngstown|Grand Forks|Fargo|Sioux Falls|Des Moines|Davenport|Cedar Rapids|Springfield|Peoria|Rockford|Evanston|Oak Park|Naperville|Joliet|Gary|South Bend|Fort Wayne|Evansville|Terre Haute|Lafayette|Muncie|Kalamazoo|Lansing|Flint|Saginaw|Dearborn|Green Bay|Oshkosh|Eau Claire|La Crosse|Duluth|St\. Paul|Rochester|Mankato|Winona|Northfield|Moorhead|Bismarck|Pierre|Rapid City|Aberdeen|Brookings|Vermillion|Yankton|Mitchell|Huron|Watertown)(?:,\s*[A-Z][a-z.]+)?$")
PUBLISHER_RE = re.compile(r"^(?:[A-Z][\w.’' -]+(?:,\s*[A-Z][\w.]+)?):\s*[A-Z][\w.,’'& -]+$|^(?:Deseret Book|Bookcraft|Shadow Mountain|Covenant Communications|Cedar Fort|Signature Books|Harper|HarperCollins|Random House|Penguin|Macmillan|Simon (?:&|and) Schuster|Oxford University Press|Cambridge University Press|BYU Press|Brigham Young University Press|University of \w+ Press|\w+ University Press|Zondervan|Doubleday|Houghton Mifflin|Little, Brown|Knopf|Viking|Scribner|W\. ?W\. Norton|Norton|Bantam|Dover|Ballantine|Collier|Eerdmans|Baker|Thomas Nelson|Crossway|Tyndale|InterVarsity|Beacon|Basic Books|Free Press|Crown|Hachette|Hyperion|Deseret News Press|Juvenile Instructor Office|Religious Studies Center|Church Historian's Press|Intellectual Reserve)\b.*$")
URL_RE = re.compile(r"⟦U\d+⟧|\b(?:www\.|https?://)|\.(?:org|com|edu|net|gov|co\.uk|io)\b", re.I)
HONORIFIC = re.compile(
    r"^(president|elder|sister|brother|bishop|dr|the rev|rev|reverend|sir|lord|lady|dame|"
    r"pope|rabbi|professor|prof|general|gen|king|queen|prophet|the prophet|apostle|mr|mrs|ms|miss|"
    r"captain|capt|colonel|col|judge|justice|chief justice|senator|governor|cardinal|archbishop|"
    r"presiding bishop|patriarch|the apostle|the venerable|his holiness|the honorable|hon|lieutenant|lt|major|maj|"
    r"admiral|commander|sergeant|sgt|private|pvt|coach|chancellor|secretary|ambassador|mayor|first lady|"
    r"brigadier|marshal|commodore|corporal|a sister|a brother|the late|the great)\.?\s+",
    re.I,
)
TITLE_WORDS = {   # capitalized words that indicate a title or organization, not a person
    "sourcebook", "poetry", "poems", "book", "books", "history", "teachings", "discourses", "journal", "writings",
    "gospel", "doctrine", "doctrines", "church", "report", "story", "stories", "ideals", "letters", "lectures",
    "hymns", "songs", "encyclopedia", "dictionary", "quotations", "treasury", "collected", "complete", "works",
    "essays", "sermons", "readings", "chronicles", "testament", "covenants", "scriptures", "messages", "addresses",
    "conference", "era", "news", "magazine", "review", "press", "company", "inc", "inc.", "publishing", "university",
    "college", "institute", "center", "society", "association", "foundation", "library", "archives", "department",
    "office", "union", "board", "committee", "volume", "edition", "selected", "saints", "principles", "manual",
    "guide", "handbook", "lessons", "study", "studies", "papers", "documents", "minutes", "proceedings", "anthology",
    "reminiscences", "memoirs", "autobiography", "biography", "diary", "diaries", "journals", "records", "annals",
    "times", "seasons", "kingdom", "prophets", "apostles", "revelation", "revelations", "commandments", "salvation",
    "atonement", "mormonism", "temple", "temples", "priesthood", "families", "marriage", "children", "youth",
    "women", "mothers", "fathers", "parents", "sunday", "school", "primary", "relief", "spirit", "ghost", "world",
    "nation", "america", "american", "england", "english", "british", "united", "states", "pilgrim's", "pilgrim’s",
    "progress", "paradise", "divine", "comedy", "tale", "tales", "carol", "introduction", "preface", "foreword",
    "chapter", "part", "section", "article", "psalm", "hymn", "song", "ode", "sonnet", "poem", "prayer", "sermon",
    "address", "speech", "talk", "devotional", "fireside", "broadcast", "interview", "letter", "statement",
    "proclamation", "declaration", "testimony", "answers", "questions", "deseret", "utah", "nauvoo", "kirtland",
    "jerusalem", "christmas", "christianity", "screwtape", "narnia", "wardrobe", "savior", "saviour", "heavenly",
    "eternal", "mere", "lord", "god", "jesus", "christ", "topics", "background", "newsroom", "website", "web",
    "online", "video", "podcast", "star", "translation", "songbook", "exponent", "digest", "masterpieces", "verse", "greater", "call", "record", "index", "catalog", "almanac", "atlas", "bibliography", "concordance", "commentary", "lexicon", "grammar", "primer", "reader", "companion", "guidebook", "workbook", "textbook", "yearbook", "notebook", "correspondence", "message", "messages", "blessing", "blessings", "covenant", "ordinance", "ordinances", "sacrament", "baptism", "confirmation", "endowment", "sealing", "celestial", "terrestrial", "telestial", "millennial", "restoration", "apostasy", "dispensation", "pioneer", "handcart", "trek", "exodus", "harvest", "kingdom", "zion", "babylon", "israel", "gentile", "gentiles", "lamanite", "lamanites", "nephite", "nephites", "jaredite", "jaredites", "words", "sayings", "life", "lives", "selections", "best", "wit", "wisdom", "thoughts", "reflections", "meditations", "prayers", "promises", "parables", "stories", "episode", "series", "collection", "selections", "excerpts", "comp", "ed", "eds",
    "trans", "the", "a", "an", "in", "to", "for", "on", "from", "with", "by", "at", "or", "into", "upon", "unto",
    "handcart", "pioneer", "pioneers", "company", "companies", "wagon", "journey", "trail", "camp", "monument",
    "museum", "memorial", "cemetery", "visitors", "historic", "site", "national", "international", "general",
    "annual", "semiannual", "worldwide", "regional", "stake", "ward", "mission", "area", "district", "branch",
    "quorum", "presidency", "bishopric", "council", "committee", "department", "program", "project", "fund",
    "service", "services", "welfare", "humanitarian", "education", "seminary", "institute", "byu", "lds", "ensign",
    "liahona", "newsroom", "gospel", "library", "topics", "essay", "essays", "faq", "handbook",
}
IGNORED_CHUNKS = {"gospel library", "gospel library app", "churchofjesuschrist.org", "lds.org", "newsroom.churchofjesuschrist.org",
                  "gospel topics", "topics and questions", "topics and background", "see", "see also", "ibid", "id", "n.d", "n.p",
                  "in gospel library", "available at gospel library", "gospel library edition"}
KNOWN_MONONYMS = {
    "shakespeare", "dante", "voltaire", "plato", "aristotle", "socrates", "confucius", "michelangelo", "augustine",
    "aquinas", "homer", "virgil", "ovid", "cicero", "seneca", "epictetus", "plutarch", "herodotus", "euripides",
    "sophocles", "aeschylus", "pythagoras", "archimedes", "euclid", "galileo", "newton", "darwin", "einstein",
    "tolstoy", "dostoevsky", "dostoyevsky", "chekhov", "goethe", "schiller", "nietzsche", "kant", "hegel",
    "kierkegaard", "spinoza", "descartes", "pascal", "montaigne", "rousseau", "molière", "moliere", "hugo", "dumas",
    "balzac", "flaubert", "proust", "camus", "sartre", "cervantes", "petrarch", "machiavelli", "erasmus", "luther",
    "calvin", "wesley", "spurgeon", "tennyson", "wordsworth", "coleridge", "keats", "shelley", "byron", "blake",
    "milton", "chaucer", "spenser", "donne", "dryden", "swift", "burns", "dickens", "thackeray", "hardy", "kipling",
    "yeats", "joyce", "orwell", "huxley", "tolkien", "chesterton", "bunyan", "emerson", "thoreau", "whitman",
    "dickinson", "longfellow", "whittier", "hawthorne", "melville", "poe", "twain", "frost", "sandburg", "faulkner",
    "hemingway", "steinbeck", "lincoln", "jefferson", "franklin", "churchill", "gandhi", "mandela", "buddha",
    "muhammad", "rumi", "tagore", "maimonides", "josephus", "origen", "tertullian", "jerome", "chrysostom",
    "athanasius", "irenaeus", "eusebius", "bede", "anselm", "bonaventure", "eckhart", "savonarola", "zwingli",
    "knox", "baxter", "whitefield", "cowper", "watts", "livingstone", "nouwen", "merton", "bonhoeffer", "barth",
    "tillich", "niebuhr", "buber", "heschel", "wiesel", "frankl", "jung", "freud", "maslow", "aesop", "sappho",
    "horace", "juvenal", "lucretius", "tacitus", "livy", "suetonius", "boethius", "avicenna", "averroes", "ibsen",
    "strindberg", "kafka", "rilke", "brecht", "mann", "hesse", "borges", "neruda", "lorca", "unamuno", "pushkin",
    "gogol", "turgenev", "solzhenitsyn", "pasternak", "akhmatova", "nephi", "alma", "moroni", "mormon", "helaman",
    "jacob", "enos", "benjamin", "abinadi", "ammon", "amulek", "lehi", "paul", "peter", "james", "john", "jude",
    "matthew", "mark", "luke", "isaiah", "jeremiah", "ezekiel", "daniel", "hosea", "amos", "micah", "malachi",
    "moses", "abraham", "isaac", "job", "david", "solomon", "joshua", "samuel", "elijah", "elisha", "jonah",
    "lewis", "macdonald", "longfellow", "teresa", "lao-tzu", "laozi", "mencius", "zoroaster", "hafiz", "ovid",
}
NAME_PARTICLES = {"de", "da", "di", "van", "von", "der", "den", "la", "le", "du", "y", "el", "al", "bin", "ibn",
                  "del", "della", "des", "ten", "ter", "af", "av", "zu", "and", "&", "jr.", "sr.", "ii", "iii", "iv", "jr", "sr", "of"}
QUOTE_RE = re.compile(r"“([^”]{1,260})”")
CITE_RE = re.compile(r"⟪([^⟫]{1,260})⟫")
PLACEHOLDER_RE = re.compile(r"⟦([SXU])(\d+)⟧")
SEE_RE = re.compile(r"^(see also|see|cf\.|compare|also|quoted in|as quoted in|in|from|adapted from|citing|quoting|"
                    r"see, for example,|see for example|e\.g\.,?|for example,?|paraphrasing|paraphrased from|"
                    r"translated from|attributed to|as cited in|cited in)\s+", re.I)
TRAILING_PUNCT = re.compile(r"[\s,;:.]+$")


@dataclass
class Parsed:
    author: str | None = None            # author/editor of the work as cited
    person_quoted: str | None = None     # whose words are used; defaults to author
    work_title: str | None = None
    work_type: str | None = None
    container_title: str | None = None
    year: int | None = None
    locator: str | None = None
    relation: str = "quoted"             # quoted | see | secondary
    is_citation: bool = True
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------- names

def clean_name(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    s = re.sub(r"^[\s,;:.(“”]+|[\s,;:.)“”]+$", "", s)
    s = re.sub(r"^\s*(by|and|from|with)\s+", "", s, flags=re.I)
    prev = None
    while prev != s:
        prev = s
        s = HONORIFIC.sub("", s).strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*[\[(](?:\d{4}|b\.|d\.|c\.|ca\.)[^)\]]*[\])]\s*$", "", s)   # trailing dates
    s = re.sub(r"\b([A-Z])\.([A-Z])\.", r"\1. \2.", s)                          # C.S. -> C. S.
    s = re.sub(r"\b([A-Z])\.(?=[A-Z][a-z])", r"\1. ", s)
    s = re.sub(r"\s+(Jr|Sr)$", r" \1.", s)
    return s or None


def looks_like_name(s: str | None) -> bool:
    if not s:
        return False
    s = s.strip()
    if len(s) > 60 or len(s) < 3 or re.search(r"[\d:⟦⟪“”]", s):
        return False
    low = s.lower()
    if low in {"ibid", "id", "in", "see", "also", "anonymous", "anon", "author unknown", "unknown"}:
        return False
    words = s.replace("&", "and").split()
    if not 1 <= len(words) <= 7:
        return False
    # must contain at least one capitalized surname-like token and no title words
    caps = 0
    for w in words:
        wl = w.lower().strip(".,")
        if wl in NAME_PARTICLES:
            continue
        if wl in TITLE_WORDS and not re.fullmatch(r"[A-Z]\.", w):
            return False
        if re.fullmatch(r"[A-ZÀ-Þ][\w’'\-À-ÿ]*\.?", w) or re.fullmatch(r"[A-Z]\.", w) or re.fullmatch(r"(?:Mc|Mac|O’|O')[A-Z]\w+", w):
            caps += 1
        else:
            return False
    if caps == 0:
        return False
    if len(words) == 1 and len(s) < 4:
        return False
    return True


# ----------------------------------------------------------------------------- chunking

def _split_top_level(s: str, sep: str = ",") -> list[str]:
    out, depth, in_q, in_c, buf = [], 0, False, False, []
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "“":
            in_q = True
        elif ch == "”":
            in_q = False
        elif ch == "⟪":
            in_c = True
        elif ch == "⟫":
            in_c = False
        if ch == sep and depth == 0 and not in_q and not in_c:
            out.append("".join(buf)); buf = []
        else:
            buf.append(ch)
    out.append("".join(buf))
    return [x.strip() for x in out if x.strip()]


def _strip_markup(s: str) -> str:
    s = PLACEHOLDER_RE.sub("", s)
    return s.replace("⟪", "").replace("⟫", "").strip()


def _title(t: str) -> str:
    t = _strip_markup(t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^[,;:\s]+|[,;:\s]+$", "", t)
    t = re.sub(r"[.,]$", "", t) if not re.search(r"\b(?:Jr|Sr|Inc|Co|etc|vol|ed)\.$", t) else t
    return t


def classify_cite_title(title: str) -> str:
    t = _strip_markup(title).strip().rstrip(",.").lower()
    t = re.sub(r"^the\s+", "", t)
    if t in HYMNALS or ("the " + t) in HYMNALS:
        return "hymnal"
    if t in PERIODICALS or ("the " + t) in PERIODICALS:
        return "periodical"
    if re.search(r"\b(news|gazette|herald|tribune|times|journal|magazine|review|quarterly|post|bulletin|monthly|weekly|daily|chronicle|register|observer|star|era|digest|tabloid|dispatch|courier|examiner|inquirer|sentinel|globe|mirror|sun|telegraph|advertiser|monitor|periodical)\b", t) and len(t.split()) <= 6:
        return "periodical"
    if any(h in t for h in MANUAL_HINTS):
        return "manual"
    return "book"


def _is_prose(text: str) -> bool:
    """A sentence masquerading as a title: many lowercase non-stopword words."""
    words = [w for w in re.findall(r"[A-Za-zÀ-ÿ’']+", text)]
    if len(words) < 6:
        return False
    stop = {"of", "the", "and", "in", "to", "for", "a", "an", "on", "with", "by", "from", "at", "or", "as", "into", "upon", "unto", "vs", "de", "la", "le", "du", "des", "von", "van"}
    lower = [w for w in words if w.islower() and w not in stop]
    return len(lower) / max(1, len(words)) >= 0.45


PROSE_VERBS = re.compile(r"\b(?:was|were|is|are|had|has|have|left|came|went|became|did|taught|told|made|took|gave|said|arrived|"
                         r"traveled|travelled|dedicated|emphasized|began|died|lived|served|wrote|spoke|called|needed|wanted|"
                         r"would|could|should|will|can|may|might|must|been|being|does|do|also|not|never|always|later|then|when|while|"
                         r"because|although|that|which|who|whom|whose|this|these|those|there|here|very|much|many|some|any|all|each|"
                         r"every|both|either|neither|another|other|such|only|just|even|still|yet|already|soon|now|today|tomorrow|"
                         r"yesterday|often|sometimes|usually|about|after|before|during|since|until|while|where|whether|if|unless|"
                         r"so|but|nor|than|too|also)\b")
PRONOUN_OPEN = re.compile(r"^(?:My|He|She|They|We|I|It|This|These|Those|Our|His|Her|Their|Its|You|Your|Most|Many|Some|Several|Both|All|Each|One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Hundreds|Thousands|Millions|Nearly|About|Almost|Over|Approximately|More|Less|Fewer|At|During|After|Before|In|On|When|While|Although|Because|If|As|For|With|Without|Since|Until|Today|Later|Earlier|Here|There|Then|Now|Years|Months|Weeks|Days)\s+[a-z]")


def _looks_like_sentence(text: str) -> bool:
    words = re.findall(r"[A-Za-zÀ-ÿ’']+", text)
    if PRONOUN_OPEN.match(text) and len(words) >= 2:
        return True
    if len(words) < 4:
        return False
    lower_verbs = [w for w in words if w.islower() and (PROSE_VERBS.fullmatch(w) or (len(w) > 4 and w.endswith("ed") and w not in {"need", "seed", "deed", "feed", "indeed", "reed", "weed", "bleed", "breed", "creed", "freed", "greed", "speed", "steed", "tweed", "agreed", "exceed", "proceed", "succeed", "red", "bed", "wed", "fed", "led", "shed", "sled", "fled", "sped", "bred", "hundred", "sacred", "kindred", "hatred", "naked", "wicked", "beloved", "blessed", "learned", "aged", "ragged", "rugged", "crooked", "wretched", "jagged", "dogged", "legged", "wretched", "unlearned", "united", "selected", "collected"}))]
    return len(lower_verbs) >= 2 or (len(lower_verbs) >= 1 and len(words) >= 7)


def _chunk_type(c: str, known_surnames: frozenset[str] = frozenset(), next_chunk: str | None = None) -> str:
    raw = c.strip()
    plain_c = _strip_markup(raw).strip()
    if not plain_c and "⟦U" in raw:
        return "URL"
    if not plain_c and "⟦X" in raw:
        return "TITLE"
    if raw.startswith("⟪") and raw.endswith("⟫"):
        return "CITE"
    if raw.startswith("“") or ("“" in raw and "”" in raw and raw.index("“") < 3):
        return "QUOTED"
    if re.match(r"^(?:in|from)\s+", plain_c, re.I):
        return "IN"
    if ROLE_RE.match(plain_c):
        return "ROLE"
    if YEAR_ONLY_RE.match(plain_c):
        return "YEAR"
    if DATE_RE.match(plain_c):
        return "DATE"
    if EDITION_RE.match(plain_c):
        return "EDITION"
    if LOCATOR_START.match(plain_c) or NUMERIC_LOC.match(plain_c):
        return "LOCATOR"
    if URL_RE.search(raw):
        return "URL"
    if KNOWN_CITIES.match(plain_c.rstrip(".")):
        return "PUBLISHER"
    if ":" in plain_c:
        left, right = plain_c.split(":", 1)
        if len(left.split()) <= 4 and (PUB_KEYWORD.search(right) or KNOWN_CITIES.match(left.strip()) or (next_chunk and YEAR_ONLY_RE.match(_strip_markup(next_chunk)))):
            if not re.search(r"\d", left) and not re.match(r"^\s*(?:The|A|An)\b", left):
                return "PUBLISHER"
    if re.search(r"\b(?:Press|Books?|Publishing|Publishers|House|Co\.|Company|Inc\.?|Ltd\.?|Sons|Office|Center|Centre|Society|Union|Board|Club|Foundation|Association)\.?$", plain_c) and len(plain_c.split()) <= 6 and next_chunk is not None and YEAR_ONLY_RE.match(_strip_markup(next_chunk)):
        return "PUBLISHER"
    if classify_cite_title(plain_c) in ("periodical", "hymnal", "manual") or plain_c.lower().strip(" .,") in IGNORED_CHUNKS \
            or plain_c.lower().strip(" .,") in IMPLIED_PERSON:
        return "TITLE"
    name = clean_name(plain_c)
    if looks_like_name(name):
        words = [w for w in name.split() if w.lower().strip(".,") not in NAME_PARTICLES]
        if len(words) <= 1:
            key = (words[0] if words else name).lower().strip(".,")
            return "NAME" if key in known_surnames or key in KNOWN_MONONYMS else "TITLE"
        return "NAME"
    if plain_c[:1].islower() and plain_c.split()[0].lower() not in NAME_PARTICLES:
        return "PROSE"   # house-style titles start with a capital
    if re.search(r"[A-ZÀ-Þ]", plain_c) and not re.search(r"\d{3,}", plain_c):
        return "PROSE" if (_is_prose(plain_c) or _looks_like_sentence(plain_c)) else "TITLE"
    if re.search(r"[A-ZÀ-Þ]", plain_c) and _looks_like_sentence(plain_c):
        return "PROSE"
    return "OTHER"


def _prepare(s: str) -> str:
    """House-style normalizations that make comma chunking reliable."""
    s = s.replace(",”", "”,").replace(".”", "”.")                       # move punctuation outside quotes
    s = s.replace(",⟫", "⟫,").replace(".⟫", "⟫.").replace(";⟫", "⟫;")   # … and outside <cite>
    s = re.sub(rf"\b({MONTHS}\s+\d{{1,2}}),\s+((?:1[5-9]|20)\d\d)\b", r"\1 \2", s)   # Oct. 15, 1856 -> Oct. 15 1856
    s = re.sub(r"([A-Z][a-z]+),\s+((?:Ala|Ariz|Ark|Calif|Colo|Conn|Del|Fla|Ga|Ill|Ind|Kans|Ky|La|Md|Mass|Mich|Minn|Miss|Mo|Mont|Nebr|Nev|N\.H|N\.J|N\.Mex|N\.Y|N\.C|N\.Dak|Okla|Oreg|Pa|R\.I|S\.C|S\.Dak|Tenn|Tex|Vt|Va|Wash|W\.Va|Wis|Wyo|D\.C|Ont|B\.C|Que|U\.K|Eng|Scot|Ire)\.?|Utah|Idaho|Ohio|Iowa|Maine|Texas|England|Scotland|Ireland|Canada|Australia|UK|DC):\s", r"\1 \2: ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_segment(seg: str, context: str = "", known_surnames: frozenset[str] = frozenset()) -> Parsed:
    """Parse one marked citation segment. Never raises."""
    p = Parsed()
    s = _prepare(seg.strip().strip("()[]"))
    if not s:
        p.is_citation = False
        return p

    lead = ""
    m = SEE_RE.match(s)
    if m:
        lead = m.group(1).lower()
        s = s[m.end():]
        if lead.startswith(("see", "cf", "compare", "also", "e.g", "for example")):
            p.relation = "see"
        elif lead in ("quoted in", "as quoted in", "citing", "quoting", "as cited in", "cited in"):
            p.relation = "secondary"

    if re.match(r"^ibid\b", s, re.I):
        p.work_title = "__IBID__"
        p.locator = TRAILING_PUNCT.sub("", s[5:]).strip(" ,.") or None
        p.confidence = 0.5
        return p

    # "David O. McKay quoting J. E. McCulloch, Home: …" -> the words are McCulloch's
    mq = re.match(r"^(.{3,60}?)\s+(?:quoting|citing|as quoted by|as cited by)\s+(.{3,60}?),", s)
    if mq and looks_like_name(clean_name(mq.group(1))) and looks_like_name(clean_name(mq.group(2))):
        s = s[mq.start(2):]
        p.relation = "secondary"
        p.person_quoted = clean_name(mq.group(2))
        p.notes.append(f"via {clean_name(mq.group(1))}")

    years: list[int] = []
    # Publisher blocks in brackets/parens: "(Salt Lake City: Deseret Book, 1998)" -> year
    def _pub(mm: re.Match) -> str:
        y = YEAR_RE.findall(mm.group(0))
        if y:
            years.append(int(y[-1]))
        return " "
    s = re.sub(r"[\[(][^()\[\]]*?:[^()\[\]]*?(?:1[5-9]\d\d|20[0-2]\d)[^()\[\]]*?[\])]", _pub, s)
    venue = re.search(r"\(((?:address|speech|devotional|fireside|lecture|remarks|talk|sermon|commencement|baccalaureate|broadcast|interview|statement|letter|message|presentation|seminar|symposium|conference|meeting|worldwide|video|podcast|unpublished|manuscript|typescript|transcript)[^()]*)\)", s, re.I)
    if venue:
        y = YEAR_RE.findall(venue.group(1))
        if y:
            years.append(int(y[-1]))
        s = s[:venue.start()] + " " + s[venue.end():]
        p.notes.append("venue: " + venue.group(1)[:60])
        venue_type = "speech"
    else:
        venue_type = None

    chunks = _split_top_level(s, ",")
    # Pull "(1924)" / "[2020]" out of chunks, recording the year
    cleaned: list[str] = []
    for c in chunks:
        def _yr(mm: re.Match) -> str:
            years.append(int(mm.group(1))); return " "
        c2 = PAREN_YEAR.sub(_yr, c)
        c2 = re.sub(r"\s+", " ", c2).strip(" ,")
        if c2:
            cleaned.append(c2)
    chunks = cleaned
    typed = [(c, _chunk_type(c, known_surnames, chunks[i + 1] if i + 1 < len(chunks) else None)) for i, c in enumerate(chunks)]
    # Merge consecutive TITLE chunks ("Everest, the West Ridge")
    merged: list[tuple[str, str]] = []
    for c, t in typed:
        if merged and t == "TITLE" and merged[-1][1] == "TITLE" and classify_cite_title(c) == "book" and classify_cite_title(merged[-1][0]) == "book":
            merged[-1] = (merged[-1][0] + ", " + c, "TITLE")
        elif merged and t == "PROSE" and merged[-1][1] == "TITLE" and re.match(r"^(?:the|a|an|or)\s", c) and len(c.split()) <= 6 and not PROSE_VERBS.search(c):
            merged[-1] = (merged[-1][0] + ", " + c, "TITLE")      # "Everest, the West Ridge"
        else:
            merged.append((c, t))
    typed = merged

    names: list[tuple[int, str]] = []
    editors: list[str] = []
    quoted: list[tuple[int, str]] = []
    cites: list[tuple[int, str]] = []
    titles: list[tuple[int, str]] = []
    containers_in: list[tuple[int, str]] = []
    locs: list[str] = []
    prose = 0

    def _role_is_bare(idx: int) -> bool:
        if idx < len(typed) and typed[idx][1] == "ROLE":
            mm = ROLE_RE.match(_strip_markup(typed[idx][0]))
            return mm is not None and mm.group("name") is None and mm.group("name2") is None
        return False

    # "Words of Joseph Smith, Andrew F. Ehat and Lyndon W. Cook, comps., …": a leading name-like chunk
    # followed by editors is a title.
    if len(typed) >= 3 and typed[0][1] == "NAME" and typed[1][1] == "NAME" and _role_is_bare(2):
        typed[0] = (typed[0][0], "TITLE")

    for i, (c, t) in enumerate(typed):
        pc = _strip_markup(c)
        if t == "NAME":
            if _role_is_bare(i + 1):
                editors.append(clean_name(pc)); continue
            names.append((i, clean_name(pc)))
        elif t == "ROLE":
            mm = ROLE_RE.match(pc)
            nm = mm.group("name") or mm.group("name2")
            if nm and looks_like_name(clean_name(nm)):
                editors.append(clean_name(nm))
        elif t == "QUOTED":
            qm = QUOTE_RE.search(c)
            qtext = qm.group(1) if qm else c.strip("“”")
            if len(qtext.split()) > 16 or "…" in qtext or re.search(r"[.!?;]\s+[A-Z]", qtext) or _looks_like_sentence(qtext):
                prose += len(qtext.split()); continue     # a quotation, not a title
            quoted.append((i, qtext))
            tail = c[c.find("”") + 1:].strip(" ,") if "”" in c else ""
            if tail:
                tt = _chunk_type(tail, known_surnames)
                if tt == "IN":
                    containers_in.append((i, re.sub(r"^(?:in|from)\s+", "", tail, flags=re.I)))
                elif tt in ("TITLE", "CITE"):
                    titles.append((i, tail))
                elif tt == "NAME":
                    names.append((i, clean_name(_strip_markup(tail))))
        elif t == "CITE":
            cites.append((i, c))
        elif t == "IN":
            containers_in.append((i, re.sub(r"^(?:in|from)\s+", "", c, flags=re.I)))
        elif t == "TITLE":
            if pc.lower().strip(" .,") in IGNORED_CHUNKS or len(re.sub(r"[^A-Za-z]", "", pc)) < 2:
                continue
            titles.append((i, c))
        elif t == "PROSE":
            prose += len(pc.split())
        elif t == "LOCATOR":
            locs.append(pc)
        elif t in ("YEAR", "DATE", "PUBLISHER"):
            ym = YEAR_RE.search(pc)
            if ym:
                years.append(int(ym.group(1)))

    # "Person, in Compiler, comp., Anthology" / "Person, in Author, Title": the IN chunk names a person
    in_name_idx = None
    for i, inner in list(containers_in):
        inner_plain = _strip_markup(inner)
        nm = clean_name(inner_plain)
        if looks_like_name(nm) and (len(nm.split()) > 1 or nm.lower() in known_surnames):
            in_name_idx = i
            if names and names[0][0] < i and p.person_quoted is None:
                p.person_quoted = names[0][1]
                p.relation = "secondary" if p.relation != "see" else "see"
                names = names[1:]
            if _role_is_bare(i + 1):
                editors.append(nm)
            else:
                names.append((i, nm))
            containers_in = [x for x in containers_in if x[0] != i]

    names.sort(key=lambda x: x[0])
    if not quoted and not cites and not titles and len(names) >= 2:
        titles.append(names[-1]); names = names[:-1]

    def set_container(title: str) -> None:
        p.container_title = _title(title)
        kind = classify_cite_title(title)
        if kind == "hymnal":
            p.work_type = "hymn"
        elif kind == "periodical" and not p.work_type:
            p.work_type = "article"

    if quoted:
        p.work_title = _title(quoted[0][1])
        if venue_type:
            p.work_type = venue_type
        qi = quoted[0][0]
        cont = next((c for i, c in containers_in if i >= qi), None) or next((c for i, c in cites if i > qi), None) \
            or next((c for i, c in titles if i >= qi), None)
        if cont and not venue_type:
            set_container(cont)
            ck = classify_cite_title(cont)
            cl = _strip_markup(cont).lower()
            if ck == "hymnal":
                p.work_type = "hymn"
            elif ck == "periodical":
                p.work_type = "talk" if ("conference report" in cl or (re.search(r"ensign|liahona|improvement era", cl) and "⟦X" in quoted[0][1])) else "article"
            elif ck == "manual":
                p.work_type = "chapter"
            else:
                p.work_type = "poem" if POEM_HINT.search(s) else "chapter"
        elif not venue_type:
            if re.search(r"\b(devotional|address|speech|speeches\.byu\.edu|fireside|commencement|lecture)\b", s, re.I):
                p.work_type = "speech"
            elif re.search(r"\bgeneral conference\b|\bconference report\b", s, re.I) or "⟦X" in quoted[0][1]:
                p.work_type = "talk"
            elif POEM_HINT.search(s):
                p.work_type = "poem"
            elif re.search(r"\bhymns?\b|\bsongbook\b", s, re.I):
                p.work_type = "hymn"
            else:
                p.work_type = "article"
    else:
        cand = None
        for i, c in sorted(cites + titles + containers_in, key=lambda x: x[0]):
            cand = (i, c); break
        if cand:
            i, c = cand
            kind = classify_cite_title(c)
            low = re.sub(r"^the\s+", "", _strip_markup(c).lower().strip(" .,"))
            if kind in ("periodical", "hymnal") or low in KNOWN_SERIALS:
                set_container(c)
                p.work_type = "hymn" if kind == "hymnal" else ("talk" if "conference report" in low else "periodical")
            else:
                p.work_title = _title(c)
                p.work_type = "manual" if kind == "manual" else "book"
                if PLAY_HINT.search(s):
                    p.work_type = "play"
                elif POEM_HINT.search(s) and not re.search(r"\bpp?\.", s):
                    p.work_type = "poem"
                later_in = next((cc for j, cc in containers_in if j > i), None)
                if later_in:
                    set_container(later_in)
                    if p.work_type == "book":
                        p.work_type = "chapter"

    # Author
    author_is_editor = False
    if names:
        first_title_idx = min([i for i, _ in quoted + cites + titles] or [10**6])
        before = [n for i, n in names if i < first_title_idx]
        after = [n for i, n in names if i >= first_title_idx]
        p.author = (before or after)[0]
    elif editors:
        p.author = editors[0]
        author_is_editor = True
        p.notes.append("author is editor")

    for t_ in [p.work_title, p.container_title]:
        if t_ and (m3 := re.match(r"^Teachings of Presidents of the Church:\s*(.+)$", t_, re.I)):
            p.person_quoted = p.person_quoted or clean_name(m3.group(1))
            p.work_type = "manual"
        if t_ and not p.person_quoted and not names:
            implied = IMPLIED_PERSON.get(re.sub(r"\s+", " ", t_.lower().strip(" .,")))
            if implied:
                p.person_quoted = implied
                p.notes.append("implied person")
                if implied == "William Shakespeare" and t_ == p.work_title and not re.search(r"sonnet|lucrece|complete works", t_, re.I):
                    p.work_type = "play"

    # "In John Wesley Hill, Abraham Lincoln, Man of God" -> the words are usually someone else's (see the running text)
    if p.person_quoted is None and lead in ("in", "from") and context:
        who = attribution_from_context(context)
        if who:
            p.person_quoted = who
            p.notes.append("person from context")
    if p.person_quoted is None and not author_is_editor and p.relation != "secondary":
        p.person_quoted = p.author
    if p.person_quoted is None and context and p.work_type not in ("hymn",):
        who = attribution_from_context(context)
        if who:
            p.person_quoted = who
            p.notes.append("person from context")
    if p.work_title and re.search(r"\b(correspondence|letter|letters|email|e-mail|interview|conversation|journal|diary|diaries|manuscript|typescript|notes|minutes|unpublished|remarks|personal communication|statement|press release|news release)\b", p.work_title, re.I) \
            and p.work_type in ("book", "chapter", None) and p.work_title.lower() not in IMPLIED_PERSON:
        p.work_type = "other"

    p.year = years[-1] if years else _year_fallback(s)
    p.locator = _locator(locs, s, typed)

    has_signal = bool(p.work_title or p.container_title or p.author or p.person_quoted or "⟦U" in s)
    if not has_signal:
        p.is_citation = False
    elif prose >= 4 and not (cites or quoted or names):
        p.is_citation = False
        p.notes.append("prose")
    elif not (p.work_title or p.container_title) and not (p.author or p.person_quoted):
        p.is_citation = False
    if p.work_title and _is_prose(p.work_title) and not (cites or quoted):
        p.is_citation = False
        p.notes.append("prose title")

    score = 0.0
    if p.author or p.person_quoted:
        score += 0.4
    if p.work_title:
        score += 0.35
    elif p.container_title:
        score += 0.2
    if p.year or p.locator:
        score += 0.15
    if cites or quoted:
        score += 0.1
    p.confidence = min(score, 1.0)
    return p


def attribution_from_context(context: str, window: int = 900) -> str | None:
    """Find 'Name wrote/said/taught …' in the paragraph text preceding a note. Returns the last match."""
    tail = context[-window:] if window else context
    verbs = (r"wrote|writes|said|says|taught|teaches|observed|explained|declared|noted|described|counseled|"
             r"warned|stated|penned|put it|once said|has written|reminded|testified|promised|asked|pleaded|"
             r"prayed|urged|suggested|added|continued|concluded|affirmed|insisted|recorded|expressed|offered|"
             r"shared|related|recounted|told|remarked|cautioned|encouraged|invited|proclaimed|announced|lamented|"
             r"wondered|mused|reflected|confessed|admitted|acknowledged|prophesied|foretold|preached|exclaimed|"
             r"responded|replied|answered|instructed|advised|reasoned|argued|contended|maintained|emphasized|"
             r"summarized|captured|expressed it|phrased it|penned these words|wrote these words|spoke|speaks")
    best = None
    for m in re.finditer(r"\b(?:words|teachings?|counsel|advice|wisdom|sayings?|poem|hymn|lines|verse|prayer|observation|insight|phrase|language|testimony|example|story|parable|words? of the (?:poet|hymn|song))\s+of\s+(?:the\s+)?((?:[A-Z][\w’'.\-]*\s+){0,4}[A-Z][\w’'.\-]*)", tail):
        nm = clean_name(m.group(1))
        if looks_like_name(nm) and (len(nm.split()) >= 2 or nm.lower() in KNOWN_MONONYMS):
            best = nm
    pat = re.compile(rf"((?:[A-Z][\w’'.\-]*\s+){{1,5}}[A-Z][\w’'.\-]*)(?:,\s*(?:who|a|an|the|then|our|my|his|her)[^,]{{0,70}},)?\s+(?:once\s+|has\s+|also\s+|then\s+|later\s+|famously\s+|wisely\s+|simply\s+|eloquently\s+|beautifully\s+|poignantly\s+|rightly\s+|correctly\s+|aptly\s+)?(?:{verbs})\b")
    for m in pat.finditer(tail):
        name = clean_name(m.group(1)) or ""
        name = re.sub(r"^(?:And|But|As|Then|When|Later|Finally|Once|In|On|The|A|An|Our|My|His|Her|Their|This|That|Recently|Years|Ago|Author|Poet|Writer|Scholar|Historian|Philosopher|Theologian|Scientist|Psychologist|Novelist|Playwright|Essayist|Journalist|Columnist|Educator|Professor|Doctor|Coach|Pastor|Minister|Preacher|Reverend|Brother|Sister|Elder|President|Bishop|Prophet|Apostle)\s+(?=[A-Z])", "", name)
        if looks_like_name(name) and (len(name.split()) >= 2 or name.lower() in KNOWN_MONONYMS):
            best = name
    if best is None:
        # a lone famous name anywhere in the tail ("Shakespeare’s Hamlet voiced the question…")
        for m in re.finditer(r"\b([A-Z][a-zé]+)(?:’s|'s)?\b", tail[-350:]):
            if m.group(1).lower() in KNOWN_MONONYMS and m.group(1).lower() not in {"paul", "peter", "james", "john", "mark", "luke", "matthew", "david", "job", "daniel", "jacob", "joseph", "benjamin", "samuel", "mormon", "moroni", "nephi", "alma", "lehi", "enos", "helaman", "ammon", "abinadi", "amulek", "jude", "isaiah", "jeremiah", "ezekiel", "hosea", "amos", "micah", "malachi", "moses", "abraham", "isaac", "solomon", "joshua", "elijah", "elisha", "jonah", "teresa", "lewis", "newton", "jung", "mann", "frost", "burns", "scott", "hardy", "pope", "watts", "knox", "young", "smith", "swift", "hugo", "gogol", "poe"}:
                best = m.group(1)
    return best


def _year_fallback(s: str) -> int | None:
    yrs = YEAR_RE.findall(_strip_markup(s))
    return int(yrs[-1]) if yrs else None


def _locator(locs: list[str], s: str, typed: list[tuple[str, str]]) -> str | None:
    if locs:
        out = ", ".join(TRAILING_PUNCT.sub("", x) for x in locs)
        return out[:80] or None
    # trailing page number on the last chunk: "Ensign, May 2013, 94" handled as LOCATOR already; try "…, 94."
    last = _strip_markup(typed[-1][0]) if typed else ""
    m = re.search(r"(?:^|[\s,])(\d{1,4}(?:[–-]\d{1,4})?)\.?$", last)
    if m and typed[-1][1] not in ("YEAR", "DATE", "NAME", "QUOTED", "CITE", "TITLE"):
        return m.group(1)
    return None
