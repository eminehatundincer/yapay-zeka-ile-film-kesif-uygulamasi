import json
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Backend kök dizinini sys.path'e ekle
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents import tools
from app.database import Movie, VibeTag


def test_log_agent_appends_to_active_logs():
    """log_agent çağrıldığında active_logs listesine saat damgalı olarak eklediğini test eder."""
    tools.active_logs.set([])

    tools.log_agent("Test log mesajı 1")
    tools.log_agent("Test log mesajı 2")

    logs = tools.active_logs.get()
    assert len(logs) == 2
    assert "Test log mesajı 1" in logs[0]
    assert "Test log mesajı 2" in logs[1]
    assert logs[0].startswith("[")  # Zaman damgası formatı [HH:MM:SS]


@pytest.mark.asyncio
async def test_fetch_movie_poster_url_success():
    """Wikipedia API'den afiş URL'i başarıyla çekildiğinde doğru linkin döndüğünü test eder."""
    tools.active_logs.set([])
    mock_poster_link = "https://upload.wikimedia.org/wikipedia/en/thumb/test_poster.jpg"

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "thumbnail": {"source": mock_poster_link}
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    poster_url = await tools.fetch_movie_poster_url("Inception", client=mock_client)
    assert poster_url == mock_poster_link


@pytest.mark.asyncio
async def test_fetch_movie_poster_url_fallback():
    """Wikipedia API 404 döndürdüğünde veya hata aldığında varsayılan mock görselin döndüğünü test eder."""
    tools.active_logs.set([])

    mock_response = MagicMock()
    mock_response.status_code = 404

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    poster_url = await tools.fetch_movie_poster_url("BilinmeyenFilm999", client=mock_client)
    assert poster_url == tools.DEFAULT_POSTER_URL


def test_normalize_vibe_keywords():
    """Hashtag ve CamelCase etiketlerinin esnek arama terimlerine dönüştürüldüğünü test eder."""
    terms = tools._normalize_vibe_keywords(["#ZihinBükücü", "#KaranlıkAtmosfer"])
    assert "ZihinBükücü" in terms
    assert "Zihin Bükücü" in terms
    assert "Karanlık" in terms


@pytest.mark.asyncio
async def test_get_movies_by_vibe_returns_matching_movies():
    """get_movies_by_vibe aracının eşleşen ORM Movie kayıtlarını döndürdüğünü test eder."""
    tools.active_logs.set([])

    fake_movie = Movie(
        id=uuid.uuid4(),
        title="Inception",
        overview="Rüya içinde rüya bilim kurgusu.",
        poster_path="https://example.com/inception.jpg",
        release_year=2010,
        vibes=[VibeTag(tag_name="Zihin Bükücü")],
    )

    mock_unique = MagicMock()
    mock_unique.all.return_value = [fake_movie]
    mock_scalars = MagicMock()
    mock_scalars.unique.return_value = mock_unique
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    movies = await tools.get_movies_by_vibe(mock_session, ["#ZihinBükücü"])

    assert len(movies) == 1
    assert movies[0].title == "Inception"
    mock_session.execute.assert_awaited_once()
    assert len(tools.active_logs.get()) > 0


@pytest.mark.asyncio
async def test_get_movies_by_vibe_empty_tags():
    """Etiket listesi boşsa veritabanına sorgu atılmadan boş liste döndüğünü test eder."""
    mock_session = AsyncMock()
    movies = await tools.get_movies_by_vibe(mock_session, [])
    assert movies == []
    mock_session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_omdb_movie_details_success(monkeypatch):
    """OMDb API'den IMDb ID, IMDb puanı ve afiş URL'inin başarıyla çekildiğini test eder."""
    tools.active_logs.set([])
    monkeypatch.setattr(tools.settings, "OMDB_API_KEY", "dummy_omdb_key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "Response": "True",
        "Title": "Inception",
        "imdbID": "tt1375666",
        "imdbRating": "8.8",
        "Poster": "https://m.media-amazon.com/images/inception.jpg",
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    details = await tools.fetch_omdb_movie_details("Inception", release_year=2010, client=mock_client)
    assert details["imdb_id"] == "tt1375666"
    assert details["imdb_rating"] == 8.8
    assert details["poster_url"] == "https://m.media-amazon.com/images/inception.jpg"


@pytest.mark.asyncio
async def test_fetch_omdb_movie_details_no_key(monkeypatch):
    """OMDB_API_KEY tanımlı değilse boş metadata sözlüğü döndüğünü test eder."""
    monkeypatch.setattr(tools.settings, "OMDB_API_KEY", None)
    monkeypatch.delenv("OMDB_API_KEY", raising=False)

    details = await tools.fetch_omdb_movie_details("Inception")
    assert details == {"imdb_id": None, "imdb_rating": None, "poster_url": None}


@pytest.mark.asyncio
async def test_discover_new_movies_from_web_with_duplicate_check(monkeypatch):
    """discover_new_movies_from_web aracının 3 film keşfedip OMDb/Wikipedia afişi çektiğini ve mükerrer kaydı atladığını test eder."""
    tools.active_logs.set([])
    monkeypatch.setattr(tools.settings, "GEMINI_API_KEY", "dummy_key_123")
    monkeypatch.setattr(tools.settings, "OMDB_API_KEY", None)
    monkeypatch.delenv("OMDB_API_KEY", raising=False)

    gemini_payload = {
        "movies": [
            {
                "title": "Inception",
                "overview": "Rüya katmanları üzerine zihin bükücü bir macera.",
                "release_year": 2010,
                "vibes": ["Zihin Bükücü", "Gerilim"],
            },
            {
                "title": "Arrival",
                "overview": "Dilbilimci bir akademisyenin uzaylılarla iletişim çabası.",
                "release_year": 2016,
                "vibes": ["Felsefi", "Duygusal"],
            },
            {
                "title": "Ex Machina",
                "overview": "Yapay zeka bilincini sınayan karanlık bir Turing testi.",
                "release_year": 2014,
                "vibes": ["Felsefi", "Karanlık"],
            },
        ]
    }

    fake_response = MagicMock()
    fake_response.text = json.dumps(gemini_payload)

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    # Inception zaten DB'de mevcut, Arrival ve Ex Machina yeni!
    existing_inception = Movie(
        id=uuid.uuid4(),
        title="Inception",
        overview="Mevcut kayıt.",
        poster_path="https://example.com/existing.jpg",
        release_year=2010,
        vibes=[VibeTag(tag_name="Zihin Bükücü")],
    )
    existing_felsefi_tag = VibeTag(id=5, tag_name="Felsefi")

    def _make_scalar_first(obj):
        res = MagicMock()
        res.scalars.return_value.first.return_value = obj
        return res

    # Sırayla yapılan execute çağrıları:
    # 1) Movie check: Inception -> existing_inception (duplicate -> skip tag queries)
    # 2) Movie check: Arrival -> None
    # 3) Tag check: Felsefi -> existing_felsefi_tag (cached)
    # 4) Tag check: Duygusal -> None (new VibeTag, cached)
    # 5) Movie check: Ex Machina -> None
    #    (Felsefi comes from cache, no DB query!)
    # 6) Tag check: Karanlık -> None (new VibeTag)
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=[
            _make_scalar_first(existing_inception),
            _make_scalar_first(None),
            _make_scalar_first(existing_felsefi_tag),
            _make_scalar_first(None),
            _make_scalar_first(None),
            _make_scalar_first(None),
        ]
    )

    with patch("app.agents.tools.genai.Client", return_value=mock_client), \
         patch("app.agents.tools.fetch_movie_poster_url", new=AsyncMock(return_value="https://wiki.org/poster.jpg")):

        movies = await tools.discover_new_movies_from_web(mock_session, "Felsefi ve zihin bükücü bilim kurgu")

        assert len(movies) == 3
        titles = [m.title for m in movies]
        assert titles == ["Inception", "Arrival", "Ex Machina"]

        # Sadece 2 yeni film (Arrival, Ex Machina) session.add ile eklenmeli
        assert mock_session.add.call_count == 2
        mock_session.commit.assert_awaited_once()

        # Yeni filmlere Wikipedia afişi atanmış olmalı
        assert movies[1].poster_path == "https://wiki.org/poster.jpg"
        assert movies[2].poster_path == "https://wiki.org/poster.jpg"
        # 'Felsefi' etiketi iki yeni film arasında paylaşılmış olmalı (UNIQUE ihlali yok)
        assert movies[1].vibes[0] is existing_felsefi_tag
        assert movies[2].vibes[0] is existing_felsefi_tag
