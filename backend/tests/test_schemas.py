from datetime import datetime, timezone
import uuid
import pytest
from pydantic import ValidationError

from app.database import Movie, VibeTag
from app.schemas import (
    AnalyticsResponse,
    ContentType,
    IntentAnalysisResponse,
    IntentType,
    MovieResponse,
    MovieSchema,
    SearchRequest,
    SearchResponse,
    TrendItem,
)


def test_search_request_valid():
    """Geçerli bir SearchRequest modelinin doğru yüklendiğini test eder."""
    req = SearchRequest(query="Kafa dağıtacak komik filmler", model="gemini-2.5-flash")
    assert req.query == "Kafa dağıtacak komik filmler"
    assert req.model == "gemini-2.5-flash"


def test_search_request_min_length_validation():
    """Çok kısa sorguların (1 karakter) ValidationError verdiğini test eder."""
    with pytest.raises(ValidationError):
        SearchRequest(query="a")


def test_intent_analysis_response_structure():
    """IntentAnalysisResponse modelinin tüm alanlarının ve tiplerinin doğru çalıştığını test eder."""
    analysis = IntentAnalysisResponse(
        intent=IntentType.SEARCH,
        mood="Çok yorgun ve neşelenmek isteyen bir ruh hali",
        content_type=ContentType.MOVIE,
        tags=["#Komedi", "#KafaDağıtmalık"],
        genres=["Komedi", "Macera"],
        explanation="Kullanıcı yorgunluğunu hafifletecek eğlenceli yapımlar arıyor.",
        needs_web_discovery=False,
    )

    assert analysis.intent == IntentType.SEARCH
    assert analysis.content_type == ContentType.MOVIE
    assert len(analysis.tags) == 2
    assert len(analysis.genres) == 2
    assert analysis.needs_web_discovery is False

    json_data = analysis.model_dump_json()
    assert "KafaDağıtmalık" in json_data


def test_movie_schema_from_orm_attributes():
    """MovieSchema modelinin SQLAlchemy Movie ve VibeTag ORM nesnelerinden doğrulandığını test eder."""
    movie_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    orm_movie = Movie(
        id=movie_id,
        title="Inception",
        overview="Rüya içinde rüya temalı bilim kurgu başyapıtı.",
        poster_path="https://example.com/inception.jpg",
        release_year=2010,
        created_at=now,
        vibes=[VibeTag(tag_name="Zihin Bükücü"), VibeTag(tag_name="Felsefi")],
    )

    schema = MovieSchema.model_validate(orm_movie)

    assert schema.id == movie_id
    assert schema.title == "Inception"
    assert schema.release_year == 2010
    assert schema.poster_path == "https://example.com/inception.jpg"
    assert schema.created_at == now
    assert schema.vibes == ["Zihin Bükücü", "Felsefi"]


def test_movie_response_from_dict_and_attributes():
    """MovieResponse modelinin geriye dönük uyumlulukla çalıştığını test eder."""
    test_id = uuid.uuid4()
    movie = MovieResponse(
        id=test_id,
        title="The Grand Budapest Hotel",
        overview="Pastel renklerde nostaljik ve mizahi macera.",
        poster_path="https://example.com/poster.jpg",
        release_year=2014,
        vibes=["Pastel Renkler", "Mizahi", "Nostaljik"],
        genre="Komedi",
    )

    assert movie.id == test_id
    assert movie.title == "The Grand Budapest Hotel"
    assert movie.release_year == 2014
    assert len(movie.vibes) == 3


def test_search_response_structure_and_mood_coercion():
    """SearchResponse modelinin yeni alanlarını (response_text, movies, matched_tool, detected_mood, logs) doğrular."""
    movie = MovieSchema(
        id=uuid.uuid4(),
        title="Amélie",
        overview="İç ısıtan Paris hikayesi.",
        release_year=2001,
        vibes=["İç Isıtan", "Romantik"],
    )

    resp = SearchResponse(
        response_text="Sıcacık bir akşam için Amélie harika bir seçim olacaktır.",
        movies=[movie],
        matched_tool="get_movies_by_vibe",
        detected_mood=["#İçIsıtan", "#Romantik"],
        logs=["[12:00:00] İstek tamamlandı."],
    )

    assert resp.response_text.startswith("Sıcacık")
    assert len(resp.movies) == 1
    assert resp.movies[0].title == "Amélie"
    assert resp.matched_tool == "get_movies_by_vibe"
    assert resp.detected_mood == ["#İçIsıtan", "#Romantik"]
    assert len(resp.logs) == 1

    # Tekil string detected_mood esnek dönüşüm testi
    resp_single_mood = SearchResponse(
        response_text="Analitik özeti.",
        movies=[],
        matched_tool="AnalysisService.get_analytics_report",
        detected_mood="Analitik",
        logs=[],
    )
    assert resp_single_mood.detected_mood == ["Analitik"]


def test_trend_item_and_analytics_response():
    """TrendItem ve AnalyticsResponse şemalarının doğrulama kurallarını test eder."""
    trends = [
        TrendItem(mood="#KafaDağıtmalık", count=12),
        TrendItem(mood="#ZihinBükücü", count=8),
    ]
    analytics = AnalyticsResponse(
        total_queries=25,
        top_moods=trends,
        ai_summary="Kullanıcılar son dönemde en çok kafa dağıtmalık ve zihin bükücü yapımları tercih ediyor.",
    )

    assert analytics.total_queries == 25
    assert len(analytics.top_moods) == 2
    assert analytics.top_moods[0].mood == "#KafaDağıtmalık"
    assert analytics.top_moods[0].count == 12
    assert "kafa dağıtmalık" in analytics.ai_summary.lower()

    with pytest.raises(ValidationError):
        TrendItem(mood="#Komedi", count=-1)
