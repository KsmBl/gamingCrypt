"""Movie info from Wikidata / Wikipedia - against a fake of both (no network in tests)."""

import pytest
import requests

from gamingcrypt.movies import library, metadata
from gamingcrypt.movies.library import MovieInfo


class Response:
    def __init__(self, data=None, content=b"", status=200):
        self.data, self.content, self.status_code = data, content, status

    def json(self):
        if self.data is None:
            raise ValueError("no json")
        return self.data


def item(qid):
    return {"mainsnak": {"datavalue": {"value": {"id": qid}}}, "rank": "normal"}


def film(qid, label, years=(), minutes=None, fsk=None, genres=(), directors=(), cast=(), voices=(), wiki=None,
         aliases=(), de=None):
    claims = {"P577": [{"mainsnak": {"datavalue": {"value": {"time": f"+{y}-03-31T00:00:00Z"}}}} for y in years]}
    if minutes:
        claims["P2047"] = [{"mainsnak": {"datavalue": {"value": {
            "amount": f"+{minutes}", "unit": "http://www.wikidata.org/entity/Q7727"}}}}]
    if fsk:
        claims["P1981"] = [item(fsk)]
    claims["P136"] = [item(g) for g in genres]
    claims["P57"] = [item(d) for d in directors]
    for prop, people in (("P161", cast), ("P725", voices)):
        claims[prop] = []
        for person in people:
            actor, role, order = (person + (None, None))[:3]
            claim = item(actor)
            claim["qualifiers"] = {}
            if role and role.startswith("Q"):
                claim["qualifiers"]["P453"] = [{"datavalue": {"value": {"id": role}}}]
            elif role:
                claim["qualifiers"]["P4633"] = [{"datavalue": {"value": role}}]
            if order is not None:
                claim["qualifiers"]["P1545"] = [{"datavalue": {"value": str(order)}}]
            claims[prop].append(claim)
    labels = {"en": {"value": label}}
    if de:
        labels["de"] = {"value": de}
    return {"id": qid, "labels": labels, "aliases": {"en": [{"value": a} for a in aliases]}, "claims": claims,
            "sitelinks": {f"{lang}wiki": {"title": title} for lang, title in (wiki or {}).items()}}


LABELS = {"Q16": "FSK 16", "Q0": "FSK 0", "Qthr": "thriller film", "Qsf": "science fiction film",
          "Qkr": "Keanu Reeves", "Qcm": "Carrie-Anne Moss", "Qlf": "Laurence Fishburne", "Qneo": "Neo",
          "Qtri": "Trinity", "Qmor": "Morpheus", "Qlw": "Lana Wachowski", "Qab": "Albert Brooks",
          "Qed": "Ellen DeGeneres", "Qdl": "David Lynch", "Qdv": "Denis Villeneuve"}


class Web:
    """Wikidata, Wikipedia and the image server."""

    def __init__(self, films, pages=None, images=None):
        self.films, self.pages, self.images = {f["id"]: f for f in films}, pages or {}, images or {}
        self.calls = []
        self.offline = False

    def __call__(self, url, params):
        self.calls.append((url, dict(params)))
        if self.offline:
            raise requests.ConnectionError("no network")
        if "wikidata.org" in url:
            assert params["format"] == "json"
            if params["action"] == "query":
                text = params["srsearch"].split(" haswbstatement:")[0].casefold()
                assert "P31=Q11424" in params["srsearch"]
                hits = [q for q, f in self.films.items()
                        if any(text in n.casefold() for n in metadata.names(f))]
                return Response({"query": {"search": [{"title": q} for q in hits]}})
            ids = params["ids"].split("|")
            if params["props"] == "labels":
                return Response({"entities": {q: {"id": q, "labels": {"en": {"value": LABELS[q]}}}
                                              for q in ids if q in LABELS}})
            return Response({"entities": {q: self.films[q] for q in ids if q in self.films}})
        if "wikipedia.org" in url:
            lang = url.split("//")[1].split(".")[0]
            page = self.pages.get((lang, params["titles"]), {})
            return Response({"query": {"pages": [page]}})
        return self.images.get(url, Response(status=404))


def png_bytes():
    from PySide6.QtCore import QBuffer
    from PySide6.QtGui import QColor, QImage

    image = QImage(20, 30, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


MATRIX = film("Q83495", "The Matrix", [1999, 1999], 136, "Q16", ["Qthr", "Qsf"], ["Qlw"],
              cast=[("Qcm", "Qtri", 2), ("Qkr", "Qneo", 1), ("Qlf", "Qmor")],
              wiki={"en": "The Matrix", "de": "Matrix (Film)"}, de="Matrix")
POSTER = "https://upload.wikimedia.org/the_matrix.png"
PAGES = {("en", "The Matrix"): {"extract": "The Matrix is a 1999 film.", "thumbnail": {"source": POSTER}},
         ("de", "Matrix (Film)"): {"extract": "Matrix ist ein Film von 1999."}}


@pytest.fixture
def web():
    dune_old = film("Q1", "Dune", [1984], 137, directors=["Qdl"])
    dune_new = film("Q2", "Dune", [2021], 155, directors=["Qdv"])
    nemo = film("Q3", "Finding Nemo", [2003], 100, "Q0", voices=[("Qab", "Marlin"), ("Qed", "Dory")],
                aliases=["Findet Nemo"])
    return Web([MATRIX, dune_old, dune_new, nemo], PAGES, {POSTER: Response(content=png_bytes())})


def test_finds_the_film_with_everything(web):
    info, poster = metadata.Lookup(web).find("The Matrix", 1999)
    assert info.title == "The Matrix" and info.year == 1999 and info.runtime == 136 and info.fsk == "FSK 16"
    assert info.genres == ["Thriller", "Science fiction"] and info.directors == ["Lana Wachowski"]
    # billed ones first, roles from Wikidata
    assert info.actors == [("Keanu Reeves", "Neo"), ("Carrie-Anne Moss", "Trinity"), ("Laurence Fishburne", "Morpheus")]
    assert info.plot == "The Matrix is a 1999 film." and poster == POSTER and info.wikidata == "Q83495"


def test_german_first_takes_the_german_title_and_text_but_the_english_poster(web):
    info, poster = metadata.Lookup(web, languages=("de", "en")).find("Matrix", 1999)
    assert info.title == "Matrix" and info.plot == "Matrix ist ein Film von 1999." and poster == POSTER


def test_the_year_picks_the_remake(web):
    lookup = metadata.Lookup(web)
    assert lookup.find("Dune", 2021)[0].directors == ["Denis Villeneuve"]
    assert lookup.find("Dune", 1984)[0].directors == ["David Lynch"]


def test_voice_actors_and_other_names(web):
    info, poster = metadata.Lookup(web).find("Findet Nemo", None)  # the German name, an alias
    assert info.title == "Finding Nemo" and info.fsk == "FSK 0" and poster == ""
    assert info.actors == [("Albert Brooks", "Marlin"), ("Ellen DeGeneres", "Dory")]


def test_nothing_alike_is_not_taken(web):
    assert metadata.Lookup(web).find("Matrix Revolutions Extended Fan Edit", None) is None
    assert metadata.Lookup(web).find("Unknown Home Video", None) is None


def test_name_score():
    assert metadata.name_score("The Matrix", ["the matrix"]) == 3
    assert metadata.name_score("Matrix", ["The Matrix"]) == 2
    assert metadata.name_score("Amelie", ["Amélie"]) == 3
    assert metadata.name_score("Fast & Furious", ["Fast and Furious"]) == 3
    assert metadata.name_score("Matrix", ["Matrixx"]) == 0 and metadata.name_score("", ["x"]) == 0
    # the file says it a bit differently
    assert metadata.name_score("Matrix Revolution", ["The Matrix Revolutions"]) == 2
    assert metadata.name_score("Schuh des Manitu", ["Der Schuh des Manitu"]) == 2


def test_lengths_in_other_units_and_genre_names():
    hours = {"claims": {"P2047": [{"mainsnak": {"datavalue": {"value": {
        "amount": "+2", "unit": "http://www.wikidata.org/entity/Q25235"}}}}]}}
    assert metadata.runtime(hours) == 120 and metadata.runtime({"claims": {}}) == 0
    assert metadata.genre_name("thriller film") == "Thriller" and metadata.genre_name("drama") == "Drama"


@pytest.fixture
def matrix_file(tmp_path):
    (tmp_path / "The.Matrix.1999.1080p.mkv").write_bytes(b"v")
    return library.scan(tmp_path)[0]


def test_update_saves_cover_and_info_next_to_the_movie(web, matrix_file):
    assert metadata.update(matrix_file, metadata.Lookup(web), now=lambda: 1750000000)
    cover = matrix_file.path.with_suffix(".jpg")
    assert cover.read_bytes()[:2] == b"\xff\xd8"  # the PNG poster saved as JPEG
    info = library.read_info(matrix_file.path.with_suffix(".nfo"))
    assert info.title == "The Matrix" and info.fsk == "FSK 16" and info.looked_up == 1750000000
    assert matrix_file.info == info and not metadata.needs_lookup(matrix_file, 1750000000 + 10**9)


def test_update_keeps_what_was_watched(web, matrix_file):
    library.set_progress(matrix_file, 1000, 8000)
    metadata.update(matrix_file, metadata.Lookup(web))
    assert library.read_info(matrix_file.info_path).position == 1000


def test_not_found_keeps_the_file_name_and_asks_again_later(web, tmp_path):
    (tmp_path / "Holiday 2019.mp4").write_bytes(b"v")
    movie = library.scan(tmp_path)[0]
    now = metadata.MATCHING_CHANGED + 1000
    assert metadata.needs_lookup(movie, now)
    assert metadata.update(movie, metadata.Lookup(web), now=lambda: now)
    info = library.read_info(movie.info_path)
    assert info.title == "Holiday" and info.year == 2019 and not info.wikidata
    assert not movie.cover_path.exists()
    assert not metadata.needs_lookup(movie, now + 86400)
    assert metadata.needs_lookup(movie, now + 31 * 86400)


def test_not_found_with_the_old_matching_is_asked_again(web, tmp_path):
    (tmp_path / "Matrix Revolution.mp4").write_bytes(b"v")
    movie = library.scan(tmp_path)[0]
    library.set_metadata(movie, MovieInfo(title="Matrix Revolution", looked_up=metadata.MATCHING_CHANGED - 3600))
    assert metadata.needs_lookup(movie, metadata.MATCHING_CHANGED + 3600)


def test_offline_changes_nothing(web, matrix_file):
    web.offline = True
    assert metadata.update(matrix_file, metadata.Lookup(web)) is False
    assert not matrix_file.info_path.exists() and metadata.needs_lookup(matrix_file, 0)


def test_server_errors_count_as_offline(matrix_file):
    assert metadata.update(matrix_file, metadata.Lookup(lambda url, params: Response(status=503))) is False


def test_broken_poster_is_skipped(web, matrix_file):
    web.images[POSTER] = Response(content=b"not an image")
    assert metadata.update(matrix_file, metadata.Lookup(web))
    assert not matrix_file.cover_path.exists() and matrix_file.info.title == "The Matrix"


def test_requests_name_the_app():
    seen = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        seen.update(headers=headers, timeout=timeout)
        return Response({"query": {"search": []}})

    import gamingcrypt.movies.metadata as m

    original = m.requests.get
    m.requests.get = fake_get
    try:
        assert m.Lookup().search("x") == []
    finally:
        m.requests.get = original
    assert "GamingCrypt" in seen["headers"]["User-Agent"] and seen["timeout"]


def test_languages_follow_the_steam_language():
    assert metadata.languages_for({"steam": {"language": "german"}}) == ("de", "en")
    assert metadata.languages_for({"steam": {"language": "english"}}) == ("en", "de")
    assert metadata.languages_for({}) == ("en", "de")


def test_set_metadata_needs_no_info_beforehand(matrix_file):
    info = library.set_metadata(matrix_file, MovieInfo(title="X", looked_up=5))
    assert info.title == "X" and info.looked_up == 5
