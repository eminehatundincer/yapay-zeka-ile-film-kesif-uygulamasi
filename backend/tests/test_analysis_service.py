import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.analysis_service import AnalysisService
from app.schemas import AnalyticsResponse, TrendItem


@pytest.mark.asyncio
async def test_get_analytics_report_returns_total_and_top_moods():
    """get_analytics_report metodunun toplam sorgu sayısını, unnest top 10 sonucunu ve AI özetini döndürdüğünü test eder."""
    total_result = MagicMock()
    total_result.scalar.return_value = 42

    trends_result = MagicMock()
    trends_result.all.return_value = [
        ("#ZihinBükücü", 15),
        ("#KafaDağıtmalık", 10),
        ("#Karanlık", 7),
    ]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(side_effect=[total_result, trends_result])

    expected_summary = "Toplam 42 sorguda kullanıcıların en gözde atmosferi #ZihinBükücü oldu."

    with patch.object(
        AnalysisService,
        "generate_ai_summary",
        new=AsyncMock(return_value=expected_summary),
    ) as mock_summary:
        report = await AnalysisService.get_analytics_report(mock_session)

        assert isinstance(report, AnalyticsResponse)
        assert report.total_queries == 42
        assert len(report.top_moods) == 3
        assert report.top_moods[0] == TrendItem(mood="#ZihinBükücü", count=15)
        assert report.top_moods[1] == TrendItem(mood="#KafaDağıtmalık", count=10)
        assert report.ai_summary == expected_summary

        # İkinci SQL sorgusunun PostgreSQL unnest ve LIMIT 10 içerdiğini doğrula
        assert mock_session.execute.await_count == 2
        trends_sql = str(mock_session.execute.call_args_list[1][0][0]).lower()
        assert "unnest" in trends_sql
        assert "limit" in trends_sql

        mock_summary.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_ai_summary_uses_gemini_3_5_flash():
    """generate_ai_summary metodunun birincil olarak gemini-3.5-flash modelini çağırdığını test eder."""
    fake_response = MagicMock()
    fake_response.text = "Kullanıcılar ağırlıklı olarak zihin bükücü ve neşeli filmlere yöneliyor."

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=fake_response)

    top_moods = [TrendItem(mood="#ZihinBükücü", count=9)]

    with patch.object(AnalysisService, "_get_gemini_client", return_value=mock_client):
        summary = await AnalysisService.generate_ai_summary(total_queries=18, top_moods=top_moods)

        assert summary == fake_response.text
        mock_client.aio.models.generate_content.assert_awaited_once()
        _, kwargs = mock_client.aio.models.generate_content.call_args
        assert kwargs["model"] == "gemini-3.5-flash"


@pytest.mark.asyncio
async def test_generate_ai_summary_fallback_on_404(monkeypatch):
    """gemini-3.5-flash 404 döndürürse settings.GEMINI_MODEL modeline düşüldüğünü test eder."""
    monkeypatch.setattr("app.analysis_service.settings.GEMINI_MODEL", "gemini-2.5-flash")

    fake_response = MagicMock()
    fake_response.text = "Yedek model üzerinden üretilen trend özeti."

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=[RuntimeError("404 NOT_FOUND: model gemini-3.5-flash not found"), fake_response]
    )

    top_moods = [TrendItem(mood="#Komedi", count=5)]

    with patch.object(AnalysisService, "_get_gemini_client", return_value=mock_client):
        summary = await AnalysisService.generate_ai_summary(total_queries=10, top_moods=top_moods)

        assert summary == fake_response.text
        assert mock_client.aio.models.generate_content.await_count == 2
        second_call_kwargs = mock_client.aio.models.generate_content.call_args_list[1].kwargs
        assert second_call_kwargs["model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_generate_ai_summary_empty_queries():
    """Hiç kullanıcı sorgusu yokken API çağırmadan anlamlı varsayılan özet döndüğünü test eder."""
    with patch.object(AnalysisService, "_get_gemini_client") as mock_get_client:
        summary = await AnalysisService.generate_ai_summary(total_queries=0, top_moods=[])

        assert "Henüz kaydedilmiş" in summary
        mock_get_client.assert_not_called()
