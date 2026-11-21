import { useState } from 'react';
import { Calendar, Cpu, ExternalLink, Film, Sparkles, Star } from 'lucide-react';

// Wikipedia linki, boş URL veya kırık görsel durumları için yüksek kaliteli sinema mock görseli
const MOCK_POSTER_URL =
  'https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?q=80&w=600&auto=format&fit=crop';

const TOOL_LABELS = {
  get_movies_by_vibe: 'Yerel Veritabanı (PostgreSQL)',
  discover_new_movies_from_web: 'Canlı Web & AI Keşfi (Gemini + OMDb)',
  'AnalysisService.get_analytics_report': 'Analitik Trend Servisi',
};

function resolvePosterUrl(posterPath) {
  if (!posterPath || typeof posterPath !== 'string') {
    return MOCK_POSTER_URL;
  }
  const trimmed = posterPath.trim();
  // Wikipedia görselleri yerine güvenilir HD TMDB/OMDb veya mock görsel kullan
  if (!trimmed.startsWith('http') || trimmed.toLowerCase().includes('wikipedia.org') || trimmed.toLowerCase().includes('wikimedia.org')) {
    return MOCK_POSTER_URL;
  }
  return trimmed;
}

function MovieCard({ movie }) {
  const [imgSrc, setImgSrc] = useState(() => resolvePosterUrl(movie.poster_path));
  const vibes = Array.isArray(movie.vibes) ? movie.vibes : [];
  const imdbUrl = movie.imdb_id ? `https://www.imdb.com/title/${movie.imdb_id}/` : null;

  return (
    <article className="animate-fade-slide group flex flex-col overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-[#0f3b82]/30 hover:shadow-md">
      {/* Afiş Alanı */}
      <div className="relative aspect-[2/3] w-full overflow-hidden bg-slate-100">
        <img
          src={imgSrc}
          alt={movie.title}
          loading="lazy"
          onError={() => {
            if (imgSrc !== MOCK_POSTER_URL) {
              setImgSrc(MOCK_POSTER_URL);
            }
          }}
          className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
        />
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-slate-950/75 via-slate-950/20 to-transparent" />

        {/* Yıl Rozeti */}
        <span className="absolute top-3 left-3 inline-flex items-center gap-1 rounded-lg bg-slate-900/75 px-2.5 py-1 text-xs font-semibold text-white backdrop-blur-sm">
          <Calendar className="h-3 w-3 text-slate-300" />
          {movie.release_year}
        </span>

        {/* IMDb Puanı Rozeti */}
        {movie.imdb_rating != null && (
          <span className="absolute top-3 right-3 inline-flex items-center gap-1 rounded-lg bg-amber-400/95 px-2.5 py-1 text-xs font-bold text-slate-950 shadow-sm backdrop-blur-sm">
            <Star className="h-3.5 w-3.5 fill-slate-950 text-slate-950" />
            {Number(movie.imdb_rating).toFixed(1)}
          </span>
        )}
      </div>

      {/* Kart İçeriği */}
      <div className="flex flex-1 flex-col p-4 sm:p-5">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-base font-bold leading-snug text-[#1e293b] group-hover:text-[#0f3b82]">
            {movie.title}
          </h3>
          {imdbUrl && (
            <a
              href={imdbUrl}
              target="_blank"
              rel="noreferrer"
              title="IMDb sayfasında aç"
              className="shrink-0 rounded-md p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-[#0f3b82]"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          )}
        </div>

        <p className="mt-2 line-clamp-4 flex-1 text-sm leading-relaxed text-slate-600">
          {movie.overview}
        </p>

        {/* Mod / Vibe Etiketleri */}
        {vibes.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-1.5 border-t border-slate-100 pt-3">
            {vibes.slice(0, 5).map((tag) => (
              <span
                key={tag}
                className="rounded-md bg-[#0f3b82]/8 px-2.5 py-1 text-[11px] font-semibold text-[#0f3b82]"
              >
                #{String(tag).replace(/^#/, '')}
              </span>
            ))}
          </div>
        )}
      </div>
    </article>
  );
}

export default function MovieGrid({
  movies = [],
  responseText = '',
  detectedMood = [],
  matchedTool = '',
  isLoading = false,
  hasSearched = false,
}) {
  if (isLoading) {
    return (
      <section className="space-y-4">
        <div className="h-24 animate-pulse rounded-2xl border border-slate-200 bg-white p-5" />
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((n) => (
            <div
              key={n}
              className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
            >
              <div className="aspect-[2/3] w-full animate-pulse bg-slate-200/80" />
              <div className="space-y-2.5 p-4">
                <div className="h-5 w-3/4 animate-pulse rounded bg-slate-200" />
                <div className="h-3.5 w-full animate-pulse rounded bg-slate-100" />
                <div className="h-3.5 w-5/6 animate-pulse rounded bg-slate-100" />
              </div>
            </div>
          ))}
        </div>
      </section>
    );
  }

  if (!hasSearched && movies.length === 0 && !responseText) {
    return (
      <section className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-14 text-center">
        <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#0f3b82]/10 text-[#0f3b82]">
          <Film className="h-6 w-6" />
        </div>
        <h3 className="text-base font-semibold text-[#1e293b]">
          Keşfetmeye Hazır Mısınız?
        </h3>
        <p className="mt-1.5 max-w-md text-sm text-slate-500">
          Yukarıdaki arama çubuğuna ruh halinizi yazın veya hazır önerilerden birine tıklayın.
          Ajan, 770+ filmlik PostgreSQL veritabanını ve gerektiğinde canlı web keşfini kullanarak size özel seçki hazırlayacaktır.
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-5">
      {/* Yapay Zeka Öneri Özeti & Meta Bilgiler */}
      {responseText && (
        <div className="animate-fade-slide rounded-2xl border border-[#0f3b82]/20 bg-white p-5 shadow-sm">
          <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm font-semibold text-[#0f3b82]">
              <Sparkles className="h-4 w-4" />
              <span>Ajan Küratör Notu</span>
            </div>
            {matchedTool && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-[#f8fafc] px-3 py-1 text-xs font-medium text-slate-600">
                <Cpu className="h-3.5 w-3.5 text-[#0f3b82]" />
                {TOOL_LABELS[matchedTool] || matchedTool}
              </span>
            )}
          </div>

          <p className="text-sm leading-relaxed text-[#1e293b] sm:text-[15px]">
            {responseText}
          </p>

          {detectedMood.length > 0 && (
            <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-xs font-medium text-slate-400">Tespit edilen mod:</span>
              {detectedMood.map((mood) => (
                <span
                  key={mood}
                  className="rounded-full bg-[#0f3b82] px-2.5 py-0.5 text-xs font-medium text-white"
                >
                  {mood}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Responsive Film Kartları Gridi */}
      {movies.length > 0 ? (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {movies.map((movie) => (
            <MovieCard key={movie.id || `${movie.title}-${movie.release_year}`} movie={movie} />
          ))}
        </div>
      ) : (
        hasSearched && (
          <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
            Bu sorgu için listelenecek film kartı bulunmuyor (analitik raporu veya eşleşmeyen sorgu).
          </div>
        )
      )}
    </section>
  );
}
