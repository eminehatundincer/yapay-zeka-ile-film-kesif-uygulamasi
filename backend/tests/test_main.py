from datetime import datetime, timezone
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import active_logs, log_agent
from app.database import db
from app.main import ObservableList, app
from app.schemas import AnalyticsResponse, TrendItem


def test_observable_list_triggers_callback_on_append():
    """ObservableList.append çağrısının elemanı ekleyip callback'i tetiklediğini doğrular."""
    received = []
    obs = ObservableList(callback=received.append)

    obs.append("log-1")
    obs.append("log-2")

    assert list(obs) == ["log-1", "log-2"]
    assert received == ["log-1", "log-2"]


def test_log_agent_preserves_observable_list():
    """log_agent çağrısının active_logs içindeki ObservableList callback'ini tetiklediğini doğrular."""
    streamed = []
    obs = ObservableList(callback=streamed.append)
    token = active_logs.set(obs)

    try:
        log_agent("Canlı ajan adımı 1")
        log_agent("Canlı ajan adımı 2")

        assert len(streamed) == 2
        assert "Canlı ajan adımı 1" in streamed[0]
        assert "Canlı ajan adımı 2" in streamed[1]
        assert active_logs.get() is obs
    finally:
        active_logs.reset(token)


def test_lifespan_connects_inits_and_disconnects():
    """FastAPI lifespan döngüsünün startup'ta connect/init_db ve shutdown'da disconnect çağırdığını doğrular."""
    with patch.object(db, "connect", new=AsyncMock()) as mock_connect, \
         patch.object(db, "init_db", new=AsyncMock()) as mock_init_db, \
         patch.object(db, "disconnect", new=AsyncMock()) as mock_disconnect:

        with TestClient(app):
            mock_connect.assert_awaited_once()
            mock_init_db.assert_awaited_once()
            mock_disconnect.assert_not_awaited()

        mock_disconnect.assert_awaited_once()


def test_cors_middleware_allows_origins():
    """CORS middleware'inin React frontend origin'lerine izin verdiğini doğrular."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock())

    async def _override_get_session():
        yield mock_session

    app.dependency_overrides[db.get_session] = _override_get_session
    try:
        with patch.object(db, "connect", new=AsyncMock()), \
             patch.object(db, "init_db", new=AsyncMock()), \
             patch.object(db, "disconnect", new=AsyncMock()):
            with TestClient(app) as client:
                response = client.options(
                    "/api/health",
                    headers={
                        "Origin": "http://localhost:5173",
                        "Access-Control-Request-Method": "GET",
                    },
                )
                assert response.status_code == 200
                assert response.headers.get("access-control-allow-origin") in ("*", "http://localhost:5173")
    finally:
        app.dependency_overrides.clear()


def test_health_endpoint_healthy_and_unhealthy():
    """GET /api/health uç noktasının veritabanı sağlıklı ve hatalı durumlarında doğru yanıt döndüğünü doğrular."""
    mock_session_ok = AsyncMock()
    mock_session_ok.execute = AsyncMock(return_value=MagicMock())

    async def _override_ok():
        yield mock_session_ok

    app.dependency_overrides[db.get_session] = _override_ok
    try:
        with patch.object(db, "connect", new=AsyncMock()), \
             patch.object(db, "init_db", new=AsyncMock()), \
             patch.object(db, "disconnect", new=AsyncMock()):
            with TestClient(app) as client:
                res_ok = client.get("/api/health")
                assert res_ok.status_code == 200
                assert res_ok.json() == {"status": "healthy", "database": "connected"}
                mock_session_ok.execute.assert_awaited_once()
    finally:
        app.dependency_overrides.clear()

    # Hata durumu (503)
    mock_session_fail = AsyncMock()
    mock_session_fail.execute = AsyncMock(side_effect=RuntimeError("DB bağlantısı koptu"))

    async def _override_fail():
        yield mock_session_fail

    app.dependency_overrides[db.get_session] = _override_fail
    try:
        with patch.object(db, "connect", new=AsyncMock()), \
             patch.object(db, "init_db", new=AsyncMock()), \
             patch.object(db, "disconnect", new=AsyncMock()):
            with TestClient(app) as client:
                res_fail = client.get("/api/health")
                assert res_fail.status_code == 503
                body = res_fail.json()
                assert body["status"] == "unhealthy"
                assert body["database"] == "disconnected"
    finally:
        app.dependency_overrides.clear()


def test_post_search_endpoint_success_and_validation():
    """POST /api/search uç noktasının SearchRequest doğrulaması ve SearchResponse dönüşünü test eder."""
    mock_session = AsyncMock()

    async def _override_session():
        yield mock_session

    fake_movie_id = uuid.uuid4()
    fake_result = {
        "response_text": "Bu akşam için harika bir zihin bükücü seçim: Inception!",
        "movies": [
            {
                "id": fake_movie_id,
                "title": "Inception",
                "overview": "Rüya içinde rüya bilim kurgusu.",
                "poster_path": "https://example.com/inception.jpg",
                "release_year": 2010,
                "created_at": datetime.now(timezone.utc),
                "vibes": ["Zihin Bükücü"],
            }
        ],
        "matched_tool": "get_movies_by_vibe",
        "detected_mood": ["#ZihinBükücü"],
        "logs": ["[12:00:00] Arama tamamlandı."],
    }

    app.dependency_overrides[db.get_session] = _override_session
    try:
        with patch.object(db, "connect", new=AsyncMock()), \
             patch.object(db, "init_db", new=AsyncMock()), \
             patch.object(db, "disconnect", new=AsyncMock()), \
             patch("app.main.route_and_execute", new=AsyncMock(return_value=fake_result)) as mock_route:

            with TestClient(app) as client:
                # Geçerli arama
                resp = client.post("/api/search", json={"query": "Zihin bükücü film öner"})
                assert resp.status_code == 200
                data = resp.json()
                assert data["matched_tool"] == "get_movies_by_vibe"
                assert len(data["movies"]) == 1
                assert data["movies"][0]["title"] == "Inception"
                assert data["detected_mood"] == ["#ZihinBükücü"]
                mock_route.assert_awaited_once()

                # Çok kısa sorgu -> 422
                resp_invalid = client.post("/api/search", json={"query": "a"})
                assert resp_invalid.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_get_analytics_endpoint():
    """GET /api/analytics uç noktasının AnalysisService sonucunu döndürdüğünü doğrular."""
    mock_session = AsyncMock()

    async def _override_session():
        yield mock_session

    fake_analytics = AnalyticsResponse(
        total_queries=20,
        top_moods=[TrendItem(mood="#Komedi", count=9)],
        ai_summary="Kullanıcılar en çok #Komedi etiketinde arama yaptı.",
    )

    app.dependency_overrides[db.get_session] = _override_session
    try:
        with patch.object(db, "connect", new=AsyncMock()), \
             patch.object(db, "init_db", new=AsyncMock()), \
             patch.object(db, "disconnect", new=AsyncMock()), \
             patch("app.main.AnalysisService.get_analytics_report", new=AsyncMock(return_value=fake_analytics)) as mock_report:

            with TestClient(app) as client:
                resp = client.get("/api/analytics")
                assert resp.status_code == 200
                data = resp.json()
                assert data["total_queries"] == 20
                assert data["top_moods"] == [{"mood": "#Komedi", "count": 9}]
                assert "#Komedi" in data["ai_summary"]
                mock_report.assert_awaited_once_with(mock_session)
    finally:
        app.dependency_overrides.clear()


def test_websocket_search_streams_live_logs_and_returns_result():
    """WEBSOCKET /ws/search/ rotasının canlı logları akıtıp ardından film sonucunu JSON döndürdüğünü test eder."""
    mock_session = AsyncMock()

    async def _fake_get_session():
        yield mock_session

    fake_movie_id = uuid.uuid4()

    async def _fake_route_and_execute(session, query_text, model=None):
        log_agent(f"Niyet analiz ediliyor: {query_text}")
        log_agent("Veritabanında uyumlu filmler bulundu.")
        return {
            "response_text": "Kafa dağıtmalık harika bir öneri seni bekliyor!",
            "movies": [
                {
                    "id": fake_movie_id,
                    "title": "The Grand Budapest Hotel",
                    "overview": "Pastel renkli, mizahi ve nostaljik serüven.",
                    "poster_path": "https://example.com/budapest.jpg",
                    "release_year": 2014,
                    "created_at": datetime.now(timezone.utc),
                    "vibes": ["Mizahi", "Nostaljik"],
                }
            ],
            "matched_tool": "get_movies_by_vibe",
            "detected_mood": ["#Mizahi"],
            "logs": list(active_logs.get()),
        }

    with patch.object(db, "connect", new=AsyncMock()), \
         patch.object(db, "init_db", new=AsyncMock()), \
         patch.object(db, "disconnect", new=AsyncMock()), \
         patch.object(db, "get_session", side_effect=_fake_get_session), \
         patch("app.main.route_and_execute", side_effect=_fake_route_and_execute):

        with TestClient(app) as client:
            with client.websocket_connect("/ws/search/") as ws:
                # 1. Kısa/hatalı sorgu -> error döner ve bağlantı açık kalır
                ws.send_json({"query": "a"})
                err_msg = ws.receive_json()
                assert err_msg["type"] == "error"

                # 2. Geçerli sorgu -> önce canlı loglar, sonra nihai result
                ws.send_json({"query": "Kafa dağıtmalık komik film"})

                received_logs = []
                final_result = None
                while True:
                    frame = ws.receive_json()
                    if frame["type"] == "log":
                        received_logs.append(frame["message"])
                    elif frame["type"] == "result":
                        final_result = frame["data"]
                        break

                assert len(received_logs) == 2
                assert "Niyet analiz ediliyor" in received_logs[0]
                assert "Veritabanında uyumlu filmler bulundu" in received_logs[1]

                assert final_result is not None
                assert final_result["matched_tool"] == "get_movies_by_vibe"
                assert final_result["movies"][0]["id"] == str(fake_movie_id)
                assert final_result["movies"][0]["title"] == "The Grand Budapest Hotel"
                assert len(final_result["logs"]) == 2
