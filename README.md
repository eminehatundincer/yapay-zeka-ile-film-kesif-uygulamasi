# Yapay Zeka ile Film Dizi Keşif Uygulaması

## Canlı Demo (Railway)

- **Web Uygulaması:** https://frontend-production-c4adda12.up.railway.app

## Proje Akışı

Gemini API -> PostgreSQL -> FastAPI -> React -> Docker -> Railway

## Adım 1- Gemini ile Yapay Zeka Destekli Film Keşif Algoritması Geliştirme

**Ne yapacağız?**

Kullanıcnın doğal dilde girdiği ruh haline göre niyet analizi yapacak uygun etiketleri çıkaracak ve gerektiğinde web keşif ajanını tetikleyecek bir Router Agent geliştireceğiz.

**Dosyalar:**

- `backend/app/agents/router.py` -> Niyet analizi, orkestrasyon ve yanıt sentezleme logic'i
- `backend/app/agents/tools.py` -> Ajan araçları

**Ne Öğreneceğiz?**

- `google-genai` SDK ile `gemini-2.5-flash` model entegrasyonu.
- Structured JSON Output alma kuralları
- Ajan loglarını asenkron olarak izlemek için `ContextVar` kullanımı
- Wikipedia API ile dinamik olarak veri çekmeyi

## Adım 2 - PostgreSQL ile Analiz Sonuçları ve Film Verilerini Kaydetme (ORM)

**Ne Yapacağız?**
İlişkisel veritabanı şemamızı (filmler, etiketler, junction tablosu ve kullanıcı geçmişi) asenkron SQLAlchemy kullanarak tasarlayacağız. Veritabanı başlatıldığında seed verileri otomatik olarak yüklyeceğiz.

**Dosyalar:**

- `backend/app/config.py` -> Pydantic Settings ile ortam değişkenlerinin okunması
- `backend/app/database.py` -> Async engine, sessionmaker, base model ve ORM sınıfları
- `backend/test_db.py` -> Veritabanı bağlantısını ve tabloların oluşturulmasını test eden bir script

**Ne Öğreneceğiz?**

- Pydantic Settings ile `.env` yönetimi ve config ayarları
- SQLAlchemy 2.0 asenkron bağlantısı
- Many-to-Many ilişki modellerinin tasarımı
- `lazy="selection` ilişkisel yükleme stratejisi.

## Adım 3 - FastAPI ile Film Keşif API'si Geliştirme

**Ne yapacağız?**
Yapay zeka routerımızı ve veritabanı katmanımızı asenkron FastAPI uçları (endpoints) ile dış dünyaya açacağız.
Arama sonuçlarını REST API ile sunarken, ajan loglarını canlı olarak akıtmak için bir WebSocket bağlantısı kuracağız.

**Dosyalar:**

- `backend/app/main.py` -> FastAPI lifespans, CORS, REST ve Websocket endpointleri.
- `backend/app/schemas.py` -> Pydantic request / response şemaları.

**Ne Öğreneceğiz?**

- FastAPI ile `lifespan` olayları (events) ile DB pool yönetimi.
- REST POST ve Websocket (`/ws/search`) protokellerini kullanamayı
- Gerçek zamanlı log stream'i sağlamak için callback tabanlı `ObservableLİst` tasarımını
- CORS ayarları ile frontend-backend entegrasyonu.

## Adım 4 - React ile Kullanıcı Arayüzü Geliştirme

**Ne yapacağız?**
Kullanıcnın film/dizi araması yapabildiği arama sonuçlarını premium kart tasarımlarında gördüğü, ajan loglarını bir terminal erkanından canlı izlediği ve geçmiş arama analitiğini dahsboard üzerinden inceleyebildiği modern bir web arayüzü inşa edeceğiz.

**Dosyalar:**

- `frontend/src/App.jsx` -> Sayfa düzeni
- `frontend/src/components/PromptBar.jsx` -> Arama çubuğu
- `frontend/src/components/MovieGrid.jsx` -> Film kartları
- `frontend/src/components/AgentLogs.jsx` -> Terminal görünümünde akan ajan log paneli
- `frontend/src/components/Dashboard.jsx` -> Dashboard

**Ne öğreneceğiz?**

- Vite ile React projesi geliştirme ve `npm run dev` kullanımı
- WebSocket bağlantısı açma, mesaj dinleme ve bağlantı koptuğunda REST fallback'e geçme.
- React state yönetimi
- Tailwind CSS ile premium dark/light mod renk paletleri ve responsive grid tasarımları.

## Adım 5 - Docker ile Paketleme (Docker Compose)

**Ne Yapacağız?**
Tüm servislerimizi Docker konteynerlerinde çalıştıracağız. Tek bir `docker-compose.yml` komutuyla tüm projeyi yerelde izole bir şekilde ayağa kaldıracağız.

**Dosyalar:**

- `backend/Dockerfile`
- `frontend/Dockerfile`
- `docker-compose.yml`

**Ne öğreneceğiz?**

- Python ve Node.js için çok aşamalı Dockerfile yazımı.
- Docker network yapılandırması
- Verilerin kaybolmaması için Docker Volume kullanımı
- Servisilerin healthcheck yönetimi

## Adım 6 - Railway Cloud ile Projeyi Canlıya Alma (Deploy)

**Ne yapacağız?**
Uygulamamızı Railway platformu vesilesiyle deploy edeceğiz.

**Ne Öğreneceğiz?**

- Monorepo yapısındaki alt klasörleri ayrı Railway servisleri olarak yapılandırma.
- Ortam değişkenlerinin Railway referans sözdizimi ile tanımlanması
- Github entegrasyonu ile otomatik CI/CD süreçleri.

