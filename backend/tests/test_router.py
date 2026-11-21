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

from app.agents import router
from app.database import Movie, UserQuery, VibeTag
from app.schemas import (
    AnalyticsResponse,
    ContentType,
    IntentAnalysisResponse,
    IntentType,
    SearchResponse,
    TrendItem,
)


def test_get_gemini_client_missing_key(monkeypatch):
    """API anahtarı bulunmadığında ValueError fırlatıldığını test eder."""
    monkeypatch.setattr(router.settings, "GEMINI_API_KEY", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="GEMINI_API_KEY bulunamadı"):
        router.get_gemini_client()


def test_get_gemini_client_with_key(monkeypatch):
    """API anahtarı sağlandığında geçerli bir genai.Client nesnesi döndürüldüğünü test eder."""
    monkeypatch.setattr(router.settings, "GEMINI_API_KEY", "dummy_test_api_key_123")
    client = router.get_gemini_client()
    assert client is not None


@pytest.mark.asyncio
async def test_test_gemini_connection_success(monkeypatch):
    """test_gemini_connection fonksiyonunun mock client ile asenkron olarak başarılı çalıştığını test eder."""
    monkeypatch.setattr(router.settings, "GEMINI_API_KEY", "dummy_test_api_key_123")

    fake_response = MagicMock()
    fake_response.text = "Merhaba! Bağlantı başarılı, film ve dizi keşfine hazırız."

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    with patch("app.agents.router.get_gemini_client", return_value=mock_client):
        result_text = await router.test_gemini_connection(model="gemini-2.5-flash")

        assert result_text == fake_response.text
        mock_client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_analyze_intent_success(monkeypatch):
    """analyze_intent fonksiyonunun Structured JSON çıktısını başarıyla IntentAnalysisResponse şemasına dönüştürdüğünü test eder."""
    monkeypatch.setattr(router.settings, "GEMINI_API_KEY", "dummy_test_api_key_123")

    mock_analysis_payload = {
        "intent": "search",
        "mood": "Yorgun, kafa dağıtmak isteyen neşeli bir ruh hali",
        "content_type": "movie",
        "tags": ["#KafaDağıtmalık", "#AbsürtKomedi", "#KahkahaTufanı"],
        "genres": ["Komedi", "Macera"],
        "explanation": "Kullanıcı zihinsel yorgunluğu giderecek eğlenceli ve kasmayan yapımlar arıyor.",
        "needs_web_discovery": False
    }

    fake_response = MagicMock()
    fake_response.text = json.dumps(mock_analysis_payload)

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    with patch("app.agents.router.get_gemini_client", return_value=mock_client):
        query = "Bugün çok yorgunum, kafa dağıtacak komik bir şeyler izlemek istiyorum"
        analysis = await router.analyze_intent(query, model="gemini-2.5-flash")

        assert analysis.intent.value == "search"
        assert analysis.mood == "Yorgun, kafa dağıtmak isteyen neşeli bir ruh hali"
        assert analysis.content_type.value == "movie"
        assert "#KafaDağıtmalık" in analysis.tags
        assert "Komedi" in analysis.genres
        assert analysis.needs_web_discovery is False
        assert len(analysis.explanation) > 0


@pytest.mark.asyncio
async def test_analyze_intent_fallback_on_parse_error(monkeypatch):
    """analyze_intent fonksiyonunun JSON ayrıştırma hatasında güvenli fallback şeması döndürdüğünü test eder."""
    monkeypatch.setattr(router.settings, "GEMINI_API_KEY", "dummy_test_api_key_123")

    fake_response = MagicMock()
    fake_response.text = "Geçersiz serbest metin yanıtı (JSON değil)"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    with patch("app.agents.router.get_gemini_client", return_value=mock_client):
        analysis = await router.analyze_intent("Herhangi bir arama")

        assert analysis.intent.value == "search"
        assert analysis.content_type.value == "movie"
        assert len(analysis.tags) > 0


@pytest.mark.asyncio
async def test_route_and_execute_analytics_intent():
    """Niyet analytics olduğunda AnalysisService.get_analytics_report çağrıldığını ve UserQuery kaydedildiğini test eder."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_analysis = IntentAnalysisResponse(
        intent=IntentType.ANALYTICS,
        mood="Meraklı ve istatistik odaklı",
        content_type=ContentType.ALL,
        tags=["#TrendAnalizi"],
        genres=[],
        explanation="Kullanıcı platform trendlerini öğrenmek istiyor.",
        needs_web_discovery=False,
    )
    mock_report = AnalyticsResponse(
        total_queries=15,
        top_moods=[TrendItem(mood="#ZihinBükücü", count=6)],
        ai_summary="Toplam 15 aramada en popüler etiket #ZihinBükücü olarak öne çıkıyor.",
    )

    with patch("app.agents.router.analyze_intent", new=AsyncMock(return_value=mock_analysis)), \
         patch("app.agents.router.AnalysisService.get_analytics_report", new=AsyncMock(return_value=mock_report)) as mock_get_report:

        result = await router.route_and_execute(mock_session, "En popüler mod etiketleri neler?")

        assert result["matched_tool"] == "AnalysisService.get_analytics_report"
        assert result["response_text"] == mock_report.ai_summary
        assert result["movies"] == []
        assert "#TrendAnalizi" in result["detected_mood"]
        assert len(result["logs"]) > 0

        # UserQuery veritabanına eklendi ve commit edildi mi?
        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[0][0]
        assert isinstance(added_obj, UserQuery)
        assert added_obj.query_text == "En popüler mod etiketleri neler?"
        mock_session.commit.assert_awaited_once()
        mock_get_report.assert_awaited_once_with(mock_session)

        # SearchResponse şemasıyla tam uyumlu olduğunu doğrula
        validated = SearchResponse(**result)
        assert validated.matched_tool == "AnalysisService.get_analytics_report"


@pytest.mark.asyncio
async def test_route_and_execute_search_db_hit():
    """Niyet search olup DB'de eşleşen film bulunduğunda web keşfine gitmeden sinematik yanıt döndüğünü test eder."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_analysis = IntentAnalysisResponse(
        intent=IntentType.SEARCH,
        mood="Zihin bükücü ve sürükleyici bir gece",
        content_type=ContentType.MOVIE,
        tags=["#ZihinBükücü", "#Gerilim"],
        genres=["Bilim Kurgu"],
        explanation="Derinlikli bilim kurgu arayışı.",
        needs_web_discovery=False,
    )
    db_movie = Movie(
        id=uuid.uuid4(),
        title="Inception",
        overview="Rüya içinde rüya temalı zihin bükücü yapım.",
        poster_path="https://example.com/inception.jpg",
        release_year=2010,
        vibes=[VibeTag(tag_name="Zihin Bükücü")],
    )

    with patch("app.agents.router.analyze_intent", new=AsyncMock(return_value=mock_analysis)), \
         patch("app.agents.router.get_movies_by_vibe", new=AsyncMock(return_value=[db_movie])) as mock_db_search, \
         patch("app.agents.router._filter_and_rank_movies", new=AsyncMock(return_value=[db_movie])), \
         patch("app.agents.router.discover_new_movies_from_web", new=AsyncMock()) as mock_web_discover, \
         patch("app.agents.router._synthesize_recommendation_text", new=AsyncMock(return_value="Zihnini zorlayacak harika bir gece seni bekliyor. Inception tam bu ruh haline göre!")):

        result = await router.route_and_execute(mock_session, "Zihin bükücü bir film öner")

        assert result["matched_tool"] == "get_movies_by_vibe"
        assert len(result["movies"]) == 1
        assert result["movies"][0]["title"] == "Inception"
        assert "Inception" in result["response_text"]
        assert result["detected_mood"] == ["#ZihinBükücü", "#Gerilim"]
        assert len(result["logs"]) > 0

        mock_db_search.assert_awaited_once()
        mock_web_discover.assert_not_awaited()

        validated = SearchResponse(**result)
        assert len(validated.movies) == 1


@pytest.mark.asyncio
async def test_route_and_execute_search_triggers_web_discovery_when_db_empty():
    """DB'de film bulunamadığında discover_new_movies_from_web aracının tetiklendiğini test eder."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_analysis = IntentAnalysisResponse(
        intent=IntentType.SEARCH,
        mood="Siberpunk ve melankolik",
        content_type=ContentType.MOVIE,
        tags=["#Siberpunk", "#Melankolik"],
        genres=["Bilim Kurgu"],
        explanation="Siberpunk atmosfer arayışı.",
        needs_web_discovery=False,
    )
    discovered_movie = Movie(
        id=uuid.uuid4(),
        title="Her",
        overview="Yakın gelecekte yapay zeka ile kurulan melankolik bağ.",
        poster_path="https://wiki.org/her.jpg",
        release_year=2013,
        vibes=[VibeTag(tag_name="Melankolik")],
    )

    with patch("app.agents.router.analyze_intent", new=AsyncMock(return_value=mock_analysis)), \
         patch("app.agents.router.get_movies_by_vibe", new=AsyncMock(return_value=[])), \
         patch("app.agents.router.discover_new_movies_from_web", new=AsyncMock(return_value=[discovered_movie])) as mock_web_discover, \
         patch("app.agents.router._synthesize_recommendation_text", new=AsyncMock(return_value="Siberpunk melankolisi için Her ruhuna dokunacak.")):

        result = await router.route_and_execute(mock_session, "Siberpunk ve melankolik bir şeyler")

        assert result["matched_tool"] == "discover_new_movies_from_web"
        assert len(result["movies"]) == 1
        assert result["movies"][0]["title"] == "Her"
        mock_web_discover.assert_awaited_once()

        validated = SearchResponse(**result)
        assert validated.movies[0].title == "Her"


@pytest.mark.asyncio
async def test_route_and_execute_filters_irrelevant_db_movies_and_discovers():
    """Anlamsal eleme tüm alakasız DB filmlerini elediğinde (örn. Açlık Oyunları için Western) web keşfini tetiklediğini doğrular."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    mock_analysis = IntentAnalysisResponse(
        intent=IntentType.SEARCH,
        mood="Distopik hayatta kalma gerilimi",
        content_type=ContentType.MOVIE,
        tags=["#Distopik", "#HayattaKalma", "#Macera"],
        genres=["Bilim Kurgu", "Macera"],
        explanation="Açlık Oyunları benzeri hayatta kalma filmi aranıyor.",
        needs_web_discovery=False,
    )
    irrelevant_western = Movie(
        id=uuid.uuid4(),
        title="Batıda Kan Var",
        overview="Vahşi Batı'da bir demiryolu intikam hikayesi.",
        poster_path="https://example.com/west.jpg",
        release_year=1968,
        vibes=[VibeTag(tag_name="Western"), VibeTag(tag_name="Macera")],
    )
    relevant_discovered = Movie(
        id=uuid.uuid4(),
        title="The Maze Runner",
        overview="Gizemli dev bir labirentte hayatta kalmaya çalışan gençlerin distopik mücadelesi.",
        poster_path="https://example.com/maze.jpg",
        release_year=2014,
        vibes=[VibeTag(tag_name="Distopik"), VibeTag(tag_name="Hayatta Kalma")],
    )

    with patch("app.agents.router.analyze_intent", new=AsyncMock(return_value=mock_analysis)), \
         patch("app.agents.router.get_movies_by_vibe", new=AsyncMock(return_value=[irrelevant_western])), \
         patch("app.agents.router._filter_and_rank_movies", new=AsyncMock(return_value=[])), \
         patch("app.agents.router.discover_new_movies_from_web", new=AsyncMock(return_value=[relevant_discovered])) as mock_web, \
         patch("app.agents.router._synthesize_recommendation_text", new=AsyncMock(return_value="Açlık Oyunları heyecanını aratmayacak The Maze Runner tam sana göre!")):

        result = await router.route_and_execute(mock_session, "Açlık Oyunları benzeri bir film öner")

        assert result["matched_tool"] == "discover_new_movies_from_web"
        titles = [m["title"] for m in result["movies"]]
        assert "The Maze Runner" in titles
        assert "Batıda Kan Var" not in titles
        mock_web.assert_awaited_once()

