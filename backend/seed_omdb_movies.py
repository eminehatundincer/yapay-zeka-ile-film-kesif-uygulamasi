"""
OMDb (IMDb) Üzerinden Canlı Toplu Film İçe Aktarma Scripti.

Farklı ruh halleri ve türlerde seçkin filmlerin güncel IMDb puanı, IMDb ID ve
HD afiş bilgilerini OMDb API'den asenkron olarak çeker; mükerrer kayıt kontrolü
yaparak PostgreSQL veritabanına (movies & vibe_tags) kalıcı olarak kaydeder.

Kullanım:
    backend\.venv\Scripts\python.exe backend/seed_omdb_movies.py
"""

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Dict, List

import httpx
from sqlalchemy import func, select

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.tools import DEFAULT_POSTER_URL, fetch_movie_poster_url, fetch_omdb_movie_details
from app.database import Movie, VibeTag, db

CURATED_CATALOG: List[Dict] = [
    # --- Zihin Bükücü / Bilim Kurgu ---
    {
        "title": "The Matrix",
        "year": 1999,
        "overview": "Gerçekliğin dev bir simülasyon olduğunu keşfeden genç bir yazılımcının insanlığı uyandırma mücadelesi.",
        "vibes": ["Zihin Bükücü", "Bilim Kurgu", "Aksiyon", "Felsefi", "Distopik"],
    },
    {
        "title": "Arrival",
        "year": 2016,
        "overview": "Dünya'ya inen gizemli uzay gemileriyle iletişim kurmaya çalışan bir dilbilimcinin zaman ve hafıza algısını değiştiren yolculuğu.",
        "vibes": ["Felsefi", "Bilim Kurgu", "Duygusal", "Zihin Bükücü", "Gizem"],
    },
    {
        "title": "Ex Machina",
        "year": 2014,
        "overview": "Genç bir yazılımcı, izole bir dağ evinde insansı bir yapay zekanın gerçek bilince sahip olup olmadığını test etmekle görevlendirilir.",
        "vibes": ["Felsefi", "Karanlık", "Bilim Kurgu", "Gerilim", "Yapay Zeka"],
    },
    {
        "title": "Memento",
        "year": 2000,
        "overview": "Kısa süreli hafıza kaybı yaşayan bir adamın eşinin katilini bulmak için notlar ve dövmelerle geriye doğru ördüğü zihin bükücü bulmaca.",
        "vibes": ["Zihin Bükücü", "Gerilim", "Gizem", "Karanlık", "Psikolojik"],
    },
    {
        "title": "Shutter Island",
        "year": 2010,
        "overview": "Uzak bir akıl hastanesi adasındaki kayıp hasta vakasını araştıran iki dedektifin giderek derinleşen psikolojik kabus hikayesi.",
        "vibes": ["Psikolojik", "Gerilim", "Gizem", "Zihin Bükücü", "Karanlık"],
    },
    {
        "title": "Eternal Sunshine of the Spotless Mind",
        "year": 2004,
        "overview": "Ayrılık acısından kurtulmak için birbirlerini hafızalarından sildirmeye karar veren bir çiftin rüya gibi melankolik hikayesi.",
        "vibes": ["Melankolik", "Romantik", "Zihin Bükücü", "Duygusal", "Felsefi"],
    },
    {
        "title": "Dune",
        "year": 2021,
        "overview": "Evrenin en değerli maddesini barındıran çöl gezegeni Arrakis'te kaderiyle yüzleşen genç bir varisin epik bilim kurgu destanı.",
        "vibes": ["Epik Bilim Kurgu", "Görsel Şölen", "Macera", "Büyüleyici", "Distopik"],
    },
    {
        "title": "The Truman Show",
        "year": 1998,
        "overview": "Doğduğundan beri tüm hayatının dev bir televizyon şovu olarak yayınlandığından habersiz yaşayan Truman'ın uyanış öyküsü.",
        "vibes": ["Felsefi", "Mizahi", "Duygusal", "Zihin Bükücü", "İç Isıtan"],
    },
    {
        "title": "Her",
        "year": 2013,
        "overview": "Yakın gelecekte yalnız bir yazarın, gelişmiş ve empatik bir yapay zeka işletim sistemiyle kurduğu derin duygusal bağ.",
        "vibes": ["Melankolik", "Romantik", "Bilim Kurgu", "Duygusal", "Yapay Zeka"],
    },
    # --- Gerilim / Suç / Karanlık ---
    {
        "title": "Parasite",
        "year": 2019,
        "overview": "Yoksul bir ailenin zengin bir ailenin evine tek tek sızmasıyla başlayan, keskin toplumsal taşlama ve şok edici gerilim dolu başyapıt.",
        "vibes": ["Gerilim", "Kara Mizah", "Dram", "Zihin Bükücü", "Sürükleyici"],
    },
    {
        "title": "Se7en",
        "year": 1995,
        "overview": "Yedi ölümcül günahı temel alarak cinayetler işleyen bir seri katilin izini süren iki dedektifin yağmurlu ve karanlık avı.",
        "vibes": ["Karanlık", "Gerilim", "Polisiye", "Psikolojik", "Gizem"],
    },
    {
        "title": "Fight Club",
        "year": 1999,
        "overview": "Modern tüketim toplumundan bunalan uykusuz bir ofis çalışanının karizmatik bir yabancıyla kurduğu yeraltı dövüş kulübü.",
        "vibes": ["Karanlık", "Psikolojik", "Zihin Bükücü", "Asi", "Dram"],
    },
    {
        "title": "The Dark Knight",
        "year": 2008,
        "overview": "Gotham şehrini kaosa sürükleyen Joker karşısında Batman'in adalet ve ahlak sınırlarını zorlayan efsanevi mücadelesi.",
        "vibes": ["Aksiyon", "Karanlık", "Gerilim", "Epik", "Sürükleyici"],
    },
    {
        "title": "Prisoners",
        "year": 2013,
        "overview": "Kızları kaybolan çaresiz bir babanın adaleti kendi elleriyle aramasıyla gerilimin zirveye çıktığı karanlık polisiye.",
        "vibes": ["Gerilim", "Karanlık", "Gizem", "Polisiye", "Dram"],
    },
    {
        "title": "Gone Girl",
        "year": 2014,
        "overview": "Evlilik yıldönümünde eşinin gizemli şekilde ortadan kaybolmasıyla medyanın ve polisin hedefi haline gelen bir adamın hikayesi.",
        "vibes": ["Gerilim", "Gizem", "Psikolojik", "Karanlık", "Sürükleyici"],
    },
    {
        "title": "Knives Out",
        "year": 2019,
        "overview": "Ünlü bir polisiye yazarının şüpheli ölümü üzerine eksantrik bir dedektifin açgözlü aile bireylerini sorguladığı zeki ve eğlenceli gizem.",
        "vibes": ["Gizem", "Mizahi", "Polisiye", "Kafa Dağıtmalık", "Sürükleyici"],
    },
    # --- Kafa Dağıtmalık / Komedi ---
    {
        "title": "Superbad",
        "year": 2007,
        "overview": "Liseden mezun olmadan önce unutulmaz bir gece yaşamak isteyen iki yakın arkadaşın başına gelen absürt ve kahkaha dolu aksilikler.",
        "vibes": ["Komedi", "Kafa Dağıtmalık", "Absürt Komedi", "Gençlik", "Eğlenceli"],
    },
    {
        "title": "The Hangover",
        "year": 2009,
        "overview": "Las Vegas'taki bekarlığa veda partisinin ertesi sabahı damadı kaybeden üç arkadaşın çılgın geceyi adım adım çözme macerası.",
        "vibes": ["Komedi", "Kafa Dağıtmalık", "Eğlenceli", "Macera", "Absürt Komedi"],
    },
    {
        "title": "Shaun of the Dead",
        "year": 2004,
        "overview": "Sıradan hayatına çeki düzen vermeye çalışan Shaun'ın bir sabah Londra'yı basan zombilere karşı sevdiklerini kurtarma çabası.",
        "vibes": ["Komedi", "Kara Mizah", "Kafa Dağıtmalık", "Eğlenceli", "Absürt Komedi"],
    },
    {
        "title": "Groundhog Day",
        "year": 1993,
        "overview": "Huysuz bir hava durumu spikerinin aynı günü sonsuz kez tekrar yaşamaya mahkum olmasıyla değişen hayat felsefesi.",
        "vibes": ["Komedi", "İç Isıtan", "Nostaljik", "Kafa Dağıtmalık", "Felsefi"],
    },
    {
        "title": "Palm Springs",
        "year": 2020,
        "overview": "Bir düğünde zaman döngüsüne sıkışan iki yabancının sonsuz günü eğlenceye ve beklenmedik bir aşka dönüştürme hikayesi.",
        "vibes": ["Komedi", "Romantik", "Kafa Dağıtmalık", "Eğlenceli", "Bilim Kurgu"],
    },
    {
        "title": "School of Rock",
        "year": 2003,
        "overview": "Grubundan atılan çılgın bir rock müzisyeninin sahte öğretmen olarak girdiği prestijli okulda öğrencileriyle rock grubu kurması.",
        "vibes": ["Komedi", "Müzik", "İç Isıtan", "Kafa Dağıtmalık", "Eğlenceli"],
    },
    # --- İç Isıtan / Duygusal / İlham Verici ---
    {
        "title": "The Shawshank Redemption",
        "year": 1994,
        "overview": "Haksız yere hapse atılan bir bankacının umudunu hiç kaybetmeden kurduğu dostluk ve özgürlük mücadelesi.",
        "vibes": ["İlham Verici", "Dram", "Duygusal", "Dostluk", "Klasik"],
    },
    {
        "title": "Forrest Gump",
        "year": 1994,
        "overview": "Saf kalbi ve bitmeyen azmiyle Amerikan tarihinin en önemli anlarına tesadüfen tanıklık eden Forrest'ın unutulmaz yaşam öyküsü.",
        "vibes": ["İç Isıtan", "Duygusal", "Nostaljik", "İlham Verici", "Dram"],
    },
    {
        "title": "The Intouchables",
        "year": 2011,
        "overview": "Felçli zengin bir aristokrat ile hayat dolu genç bakıcısı arasında gelişen, gerçek bir hikayeye dayanan kahkaha ve duygu dolu dostluk.",
        "vibes": ["İç Isıtan", "Dostluk", "Komedi", "Duygusal", "Fransız Sineması"],
    },
    {
        "title": "Good Will Hunting",
        "year": 1997,
        "overview": "Üniversitede hademelik yapan gizli bir matematik dehasının, bir terapist yardımıyla geçmişiyle yüzleşip potansiyelini keşfetmesi.",
        "vibes": ["İlham Verici", "Dram", "Duygusal", "Psikolojik", "Felsefi"],
    },
    {
        "title": "Dead Poets Society",
        "year": 1989,
        "overview": "Katı kurallı bir erkek yatılı okuluna gelen sıra dışı edebiyat öğretmeninin öğrencilerine 'anı yaşa' felsefesini aşılaması.",
        "vibes": ["İlham Verici", "Duygusal", "Nostaljik", "Dram", "Eğitici"],
    },
    {
        "title": "The Pursuit of Happyness",
        "year": 2006,
        "overview": "Küçük oğluyla evsiz kalan bir babanın pes etmeden yeni bir hayat kurmak için verdiği gerçek ve duygu yüklü mücadele.",
        "vibes": ["İlham Verici", "Duygusal", "Biyografi", "Dram", "Gerçek Hikaye"],
    },
    {
        "title": "Green Book",
        "year": 2018,
        "overview": "1960'lar Amerika'sında ünlü bir piyanist ile İtalyan-Amerikalı şoförünün önyargıları yıkan sıcak yol hikayesi.",
        "vibes": ["İç Isıtan", "Dostluk", "Biyografi", "Mizahi", "Duygusal"],
    },
    # --- Romantik / Melankolik ---
    {
        "title": "La La Land",
        "year": 2016,
        "overview": "Los Angeles'ta hayallerinin peşinden koşan bir caz piyanisti ile genç bir oyuncunun müzik ve renklerle bezeli tutkulu aşkı.",
        "vibes": ["Romantik", "Müzik", "Görsel Şölen", "Melankolik", "Duygusal"],
    },
    {
        "title": "Before Sunrise",
        "year": 1995,
        "overview": "Trende tanışan iki gencin Viyana sokaklarında sabaha kadar yürüyüp hayat ve aşk üzerine sohbet ettiği samimi romantik klasik.",
        "vibes": ["Romantik", "Nostaljik", "Felsefi", "İç Isıtan", "Sakin"],
    },
    {
        "title": "Pride & Prejudice",
        "year": 2005,
        "overview": "18. yüzyıl İngiltere'sinde zeki Elizabeth Bennet ile gururlu Bay Darcy arasındaki önyargıdan doğan zarif aşk hikayesi.",
        "vibes": ["Romantik", "Dönem", "Nostaljik", "Duygusal", "Görsel Şölen"],
    },
    {
        "title": "About Time",
        "year": 2013,
        "overview": "Zaman yolculuğu yapabildiğini öğrenen genç bir adamın bu yeteneği büyük bir aşk ve sevdikleriyle her anın kıymetini bilmek için kullanması.",
        "vibes": ["Romantik", "İç Isıtan", "Duygusal", "Aile", "Fantastik"],
    },
    {
        "title": "Past Lives",
        "year": 2023,
        "overview": "Çocukluk aşkı iki insanın yıllar sonra New York'ta yeniden buluşarak kader, seçimler ve 'ya olsaydı' üzerine kurduğu dingin hikaye.",
        "vibes": ["Melankolik", "Romantik", "Duygusal", "Sakin", "Dram"],
    },
    # --- Animasyon / Aile / Büyüleyici ---
    {
        "title": "Spirited Away",
        "year": 2001,
        "overview": "Ailesiyle taşınırken gizemli bir ruhlar dünyasına adım atan küçük Chihiro'nun cesaret ve büyüme dolu büyülü yolculuğu.",
        "vibes": ["Animasyon", "Büyüleyici", "Fantastik", "Görsel Şölen", "Macera"],
    },
    {
        "title": "Spider-Man: Into the Spider-Verse",
        "year": 2018,
        "overview": "Genç Miles Morales'in çoklu evrenden gelen diğer Örümcek-İnsanlarla güçlerini birleştirdiği görsel devrim niteliğinde animasyon.",
        "vibes": ["Animasyon", "Aksiyon", "Görsel Şölen", "Eğlenceli", "Macera"],
    },
    {
        "title": "Coco",
        "year": 2017,
        "overview": "Müzisyen olma hayali kuran küçük Miguel'in Ölüler Diyarı'na uzanan rengarenk ve gözyaşlarıyla güldüren aile hikayesi.",
        "vibes": ["Animasyon", "Duygusal", "İç Isıtan", "Müzik", "Aile"],
    },
    {
        "title": "WALL·E",
        "year": 2008,
        "overview": "Terk edilmiş Dünya'yı tek başına temizleyen sevimli bir robotun uzayda aşkı ve insanlığın umudunu keşfetme macerası.",
        "vibes": ["Animasyon", "Bilim Kurgu", "İç Isıtan", "Romantik", "Duygusal"],
    },
    {
        "title": "Ratatouille",
        "year": 2007,
        "overview": "Paris'in en ünlü restoranında şef olma hayali kuran yetenekli fare Remy'nin lezzet ve tutku dolu eğlenceli öyküsü.",
        "vibes": ["Animasyon", "İç Isıtan", "Komedi", "Fransız Sineması", "Kafa Dağıtmalık"],
    },
    {
        "title": "Soul",
        "year": 2020,
        "overview": "Hayalindeki caz konserine çıkmak üzereyken ruhlar alemine düşen bir müzik öğretmeninin yaşamın gerçek anlamını keşfetmesi.",
        "vibes": ["Animasyon", "Felsefi", "Müzik", "İç Isıtan", "İlham Verici"],
    },
    # --- Aksiyon / Macera / Epik ---
    {
        "title": "Mad Max: Fury Road",
        "year": 2015,
        "overview": "Kıyamet sonrası çorak topraklarda özgürlük uğruna nefes kesen bir kovalamacaya atılan Furiosa ve Max'in yüksek adrenalinli destanı.",
        "vibes": ["Aksiyon", "Adrenalin", "Distopik", "Görsel Şölen", "Sürükleyici"],
    },
    {
        "title": "Gladiator",
        "year": 2000,
        "overview": "İhanete uğrayarak köle yapılan Romalı general Maximus'un arenalardan yükselen onur ve intikam destanı.",
        "vibes": ["Epik", "Aksiyon", "Tarih", "Dram", "Duygusal"],
    },
    {
        "title": "The Lord of the Rings: The Fellowship of the Ring",
        "year": 2001,
        "overview": "Orta Dünya'yı karanlıktan kurtarmak için Tek Yüzük'ü yok etme görevini üstlenen dokuz yol arkadaşının efsanevi yolculuğu.",
        "vibes": ["Fantastik", "Epik", "Macera", "Büyüleyici", "Dostluk"],
    },
    {
        "title": "Top Gun: Maverick",
        "year": 2022,
        "overview": "Efsanevi savaş pilotu Maverick'in genç pilotları imkansız bir göreve hazırlarken geçmişiyle hesaplaştığı nefes kesen aksiyon.",
        "vibes": ["Aksiyon", "Adrenalin", "Nostaljik", "İlham Verici", "Sürükleyici"],
    },
    # --- Biyografi / Tarih / Belgesel / Öğretici ---
    {
        "title": "Oppenheimer",
        "year": 2023,
        "overview": "Atom bombasının geliştirilmesine liderlik eden fizikçi J. Robert Oppenheimer'ın bilimsel dehası ve vicdani yükünü anlatan epik biyografi.",
        "vibes": ["Biyografi", "Tarih", "Dram", "Öğretici", "Gerilim"],
    },
    {
        "title": "The Social Network",
        "year": 2010,
        "overview": "Harvard yurt odasında başlayan Facebook'un yükselişini, hırsı ve kopan dostlukları keskin diyaloglarla anlatan modern biyografi.",
        "vibes": ["Biyografi", "Dram", "Öğretici", "Sürükleyici", "Teknoloji"],
    },
    {
        "title": "Whiplash",
        "year": 2014,
        "overview": "Mükemmellik takıntılı acımasız bir konservatuvar hocasıyla sınırlarını sonuna kadar zorlayan genç bateristin nefes kesen düellosu.",
        "vibes": ["Müzik", "Gerilim", "İlham Verici", "Dram", "Psikolojik"],
    },
    {
        "title": "The Imitation Game",
        "year": 2014,
        "overview": "İkinci Dünya Savaşı'nda Nazi şifre makinesi Enigma'yı kırarak tarihin akışını değiştiren matematikçi Alan Turing'in gerçek hikayesi.",
        "vibes": ["Biyografi", "Tarih", "Öğretici", "Gerilim", "İlham Verici"],
    },
    {
        "title": "Free Solo",
        "year": 2018,
        "overview": "Kaya tırmanışçısı Alex Honnold'un 900 metrelik El Capitan duvarına hiç ip kullanmadan tırmanma hazırlığını anlatan nefes kesen belgesel.",
        "vibes": ["Belgesel", "Öğretici", "Adrenalin", "İlham Verici", "Gerçek Hikaye"],
    },
    # --- Korku / Gizem ---
    {
        "title": "Get Out",
        "year": 2017,
        "overview": "Sevgilisinin ailesiyle tanışmak için hafta sonu tatiline giden genç bir fotoğrafçının rahatsız edici sırlarla dolu gerilim kabusu.",
        "vibes": ["Korku", "Gerilim", "Gizem", "Psikolojik", "Zihin Bükücü"],
    },
    {
        "title": "A Quiet Place",
        "year": 2018,
        "overview": "En ufak sese saldıran yaratıkların istila ettiği dünyada mutlak sessizlik içinde hayatta kalmaya çalışan bir ailenin mücadelesi.",
        "vibes": ["Korku", "Gerilim", "Bilim Kurgu", "Sürükleyici", "Aile"],
    },
]


async def seed_movies_from_omdb() -> None:
    """Katalogdaki tüm filmler için OMDb'den canlı veri çeker ve eksikleri PostgreSQL'e kaydeder."""
    await db.init_db()

    semaphore = asyncio.Semaphore(6)

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as http_client:
        async def _fetch_one(item: Dict) -> Dict:
            async with semaphore:
                omdb = await fetch_omdb_movie_details(
                    item["title"],
                    release_year=item["year"],
                    client=http_client,
                )
                poster = omdb.get("poster_url")
                if not poster:
                    poster = await fetch_movie_poster_url(item["title"], client=http_client)
                return {
                    **item,
                    "imdb_id": omdb.get("imdb_id"),
                    "imdb_rating": omdb.get("imdb_rating"),
                    "poster_path": poster or DEFAULT_POSTER_URL,
                }

        print(f"[*] OMDb API üzerinden {len(CURATED_CATALOG)} film için canlı veri çekiliyor...")
        enriched_catalog = await asyncio.gather(*(_fetch_one(item) for item in CURATED_CATALOG))

    added_count = 0
    skipped_count = 0

    async for session in db.get_session():
        # Mevcut başlıkları ve etiketleri tek seferde önbelleğe al
        existing_movies_res = await session.execute(select(Movie))
        existing_titles = {m.title.strip().lower() for m in existing_movies_res.scalars().all()}

        existing_tags_res = await session.execute(select(VibeTag))
        tag_cache: Dict[str, VibeTag] = {
            t.tag_name.strip().lower(): t for t in existing_tags_res.scalars().all()
        }

        for item in enriched_catalog:
            title_key = item["title"].strip().lower()
            if title_key in existing_titles:
                skipped_count += 1
                continue
            existing_titles.add(title_key)

            movie_vibes_objs: List[VibeTag] = []
            seen_movie_tags: set[str] = set()
            for raw_tag in item["vibes"]:
                clean_tag = raw_tag.strip()
                tag_key = clean_tag.lower()
                if not clean_tag or tag_key in seen_movie_tags:
                    continue
                seen_movie_tags.add(tag_key)

                if tag_key not in tag_cache:
                    tag_cache[tag_key] = VibeTag(tag_name=clean_tag)
                movie_vibes_objs.append(tag_cache[tag_key])

            movie = Movie(
                id=uuid.uuid4(),
                title=item["title"],
                overview=item["overview"],
                poster_path=item["poster_path"],
                release_year=int(item["year"]),
                imdb_id=item["imdb_id"],
                imdb_rating=item["imdb_rating"],
                vibes=movie_vibes_objs,
            )
            session.add(movie)
            added_count += 1

        if added_count > 0:
            await session.commit()

        total_movies = (await session.execute(select(func.count(Movie.id)))).scalar() or 0
        total_tags = (await session.execute(select(func.count(VibeTag.id)))).scalar() or 0

        print(f"\n[+] İşlem tamamlandı!")
        print(f"    - Yeni eklenen film : {added_count}")
        print(f"    - Zaten mevcut olan : {skipped_count}")
        print(f"    - Toplam film sayısı: {total_movies}")
        print(f"    - Toplam vibe etiketi: {total_tags}")
        break

    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(seed_movies_from_omdb())
