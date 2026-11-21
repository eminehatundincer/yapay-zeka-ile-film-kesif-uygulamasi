"""
Yapay Zeka Film & Dizi Keşif Uygulaması - Pydantic Request & Response Şemaları
FastAPI uçları, ORM doğrulaması ve Gemini ajan analizleri için veri modelleri.
"""

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional
import uuid
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ContentType(str, Enum):
    """Kullanıcının talep ettiği içerik türü."""
    MOVIE = "movie"
    SERIES = "series"
    ALL = "all"


class IntentType(str, Enum):
    """Kullanıcı sorgusunun temel niyeti."""
    SEARCH = "search"
    ANALYTICS = "analytics"


class SearchRequest(BaseModel):
    """Kullanıcıdan gelen doğal dilde film/dizi arama ve keşif isteği."""

    query: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="Kullanıcının doğal dilde girdiği arama, ruh hali veya keşif metni.",
    )
    model: Optional[str] = Field(
        default=None,
        description="Kullanılacak Gemini modeli (örn: 'gemini-3.5-flash'). Boş bırakılırsa sistem varsayılanı kullanılır."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "Bugün çok yorgunum, kafa dağıtacak komik bir şeyler izlemek istiyorum"
            }
        }
    )


class IntentAnalysisResponse(BaseModel):
    """Gemini tarafından üretilen yapılandırılmış niyet, ruh hali ve etiket analizi yanıtı."""

    intent: IntentType = Field(
        default=IntentType.SEARCH,
        description="Tespit edilen niyet türü: 'search' (film/dizi arama ve keşif) veya 'analytics' (istatistik/raporlama)."
    )
    mood: str = Field(
        ...,
        description="Kullanıcının metninden tespit edilen baskın ruh hali veya atmosfer (örn: 'Yorgun, kafa dağıtmak isteyen, neşeli')."
    )
    content_type: ContentType = Field(
        default=ContentType.MOVIE,
        description="Tercih edilen içerik türü: 'movie' (film), 'series' (dizi) veya 'all' (tümü)."
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Ruh haline, temaya ve türe uygun CamelCase hashtag listesi (örn: ['#KafaDağıtmalık', '#Komedi', '#Hafif'])."
    )
    genres: List[str] = Field(
        default_factory=list,
        description="Önerilen sinema/dizi türleri (örn: ['Komedi', 'Macera'])."
    )
    explanation: str = Field(
        ...,
        description="Modelin kullanıcı ruh haline göre oluşturduğu empati ve öneri gerekçesi özeti."
    )
    needs_web_discovery: bool = Field(
        default=False,
        description="Güncel vizyon, yeni çıkan yapımlar veya dış ağ bilgisi gerekip gerekmediğini belirten bayrak."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "intent": "search",
                "mood": "Yorgun, rahatlamak ve kafa dağıtmak isteyen bir ruh hali",
                "content_type": "movie",
                "tags": ["#KafaDağıtmalık", "#Komedi", "#Rahatlatıcı"],
                "genres": ["Komedi", "Hafif Macera"],
                "explanation": "Kullanıcı zihinsel yorgunluğu giderecek, kasmayan, eğlenceli ve hafif yapımlar arıyor.",
                "needs_web_discovery": False
            }
        }
    )


class MovieSchema(BaseModel):
    """Veritabanındaki Movie ORM modeline karşılık gelen Pydantic v2 API şeması."""

    id: uuid.UUID = Field(
        ...,
        description="Filmin benzersiz UUID kayıt kimliği."
    )
    title: str = Field(
        ...,
        description="Filmin orijinal veya yaygın bilinen adı."
    )
    overview: str = Field(
        ...,
        description="Filmin konusu ve atmosfer özeti."
    )
    poster_path: Optional[str] = Field(
        default=None,
        description="Film afişi görsel bağlantısı (URL)."
    )
    release_year: int = Field(
        ...,
        description="Filmin vizyon/çıkış yılı."
    )
    imdb_id: Optional[str] = Field(
        default=None,
        description="Filmin IMDb kimliği (örn: 'tt1375666')."
    )
    imdb_rating: Optional[float] = Field(
        default=None,
        description="Filmin IMDb puanı (örn: 8.8)."
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Kaydın veritabanına eklenme zamanı."
    )
    vibes: List[str] = Field(
        default_factory=list,
        description="Filme bağlı vibe/atmosfer etiket adları."
    )

    @field_validator("vibes", mode="before")
    @classmethod
    def _coerce_vibe_tags(cls, value: Any) -> List[str]:
        """ORM VibeTag nesnelerini otomatik olarak string etiket adlarına dönüştürür."""
        if value is None:
            return []
        result: List[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif hasattr(item, "tag_name"):
                result.append(str(item.tag_name))
            elif isinstance(item, dict) and "tag_name" in item:
                result.append(str(item["tag_name"]))
            else:
                result.append(str(item))
        return result

    model_config = ConfigDict(from_attributes=True)


class MovieResponse(BaseModel):
    """Geriye dönük uyumluluk için korunan genel film öneri modeli."""

    id: Optional[uuid.UUID] = Field(
        default=None,
        description="Veritabanı kayıt ID'si (varsa)."
    )
    title: str = Field(
        ...,
        description="Filmin orijinal veya yaygın bilinen adı."
    )
    overview: str = Field(
        ...,
        description="Film özeti veya kullanıcının ruh haline uygunluk gerekçesi."
    )
    poster_path: Optional[str] = Field(
        default=None,
        description="Film afişi görsel bağlantısı (URL)."
    )
    release_year: int = Field(
        ...,
        description="Filmin vizyon/çıkış yılı."
    )
    vibes: List[str] = Field(
        default_factory=list,
        description="Filme ait vibe/atmosfer etiketleri."
    )
    genre: Optional[str] = Field(
        default=None,
        description="Filmin ana türü."
    )

    model_config = ConfigDict(from_attributes=True)


class SearchResponse(BaseModel):
    """Tüm arama, keşif ve analitik orkestrasyon akışının API yanıt modeli."""

    response_text: str = Field(
        ...,
        description="Kullanıcıya sunulan sinematik öneri metni veya analitik özeti."
    )
    movies: List[MovieSchema] = Field(
        default_factory=list,
        description="Eşleşen veya keşfedilen film listesi."
    )
    matched_tool: str = Field(
        ...,
        description="Orkestrasyon sırasında tetiklenen ajan aracı veya servis adı."
    )
    detected_mood: List[str] = Field(
        default_factory=list,
        description="Kullanıcının sorgusundan tespit edilen ruh hali/mod etiketleri."
    )
    logs: List[str] = Field(
        default_factory=list,
        description="Ajanın işlem adımlarını içeren zaman damgalı log akışı."
    )

    @field_validator("detected_mood", mode="before")
    @classmethod
    def _coerce_detected_mood(cls, value: Any) -> List[str]:
        """Tekil string veya None değerlerini güvenli şekilde string listesine çevirir."""
        if value is None:
            return []
        if isinstance(value, str):
            cleaned = value.strip()
            return [cleaned] if cleaned else []
        return [str(v) for v in value if v is not None and str(v).strip()]


class TrendItem(BaseModel):
    """En popüler mod etiketlerinden birini ve tekrar sayısını temsil eder."""

    mood: str = Field(
        ...,
        description="Kullanıcı sorgularında tespit edilen mod/atmosfer etiketi."
    )
    count: int = Field(
        ...,
        ge=0,
        description="İlgili mod etiketinin toplam aranma sayısı."
    )


class AnalyticsResponse(BaseModel):
    """Arama trendleri ve yapay zeka destekli analitik rapor yanıt şeması."""

    total_queries: int = Field(
        ...,
        ge=0,
        description="Veritabanında kayıtlı toplam kullanıcı sorgusu sayısı."
    )
    top_moods: List[TrendItem] = Field(
        default_factory=list,
        description="En popüler ilk 10 mod etiketi (azalan sırada)."
    )
    ai_summary: str = Field(
        ...,
        description="Gemini tarafından üretilen 1-2 cümlelik analitik özet."
    )
