'use client';

import React, { useEffect, useState, useCallback, useRef } from 'react';
import { BookOpen, Search } from 'lucide-react';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert, AlertDescription } from '@/components/ui/alert';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RunbookResult {
  id: string;
  title: string;
  domain: string;
  version: string;
  similarity: number;
  content_excerpt: string;
}

type Domain = 'all' | 'compute' | 'network' | 'storage' | 'security' | 'arc' | 'sre' | 'patch' | 'eol';

// ---------------------------------------------------------------------------
// Domain config
// ---------------------------------------------------------------------------

const DOMAINS: { id: Domain; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'compute', label: 'Compute' },
  { id: 'network', label: 'Network' },
  { id: 'storage', label: 'Storage' },
  { id: 'security', label: 'Security' },
  { id: 'arc', label: 'Arc' },
  { id: 'sre', label: 'SRE' },
  { id: 'patch', label: 'Patch' },
  { id: 'eol', label: 'EOL' },
];

const DOMAIN_ACCENT: Record<string, string> = {
  compute: 'var(--accent-blue)',
  network: '#8b5cf6',  // purple — no --accent-purple token
  storage: 'var(--accent-orange)',
  security: 'var(--accent-red)',
  arc: 'var(--accent-green)',
  sre: '#0d9488',      // teal — no --accent-teal token
  patch: 'var(--accent-yellow)',
  eol: 'var(--text-secondary)',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function domainBadgeStyle(domain: string): React.CSSProperties {
  const accent = DOMAIN_ACCENT[domain.toLowerCase()] ?? 'var(--accent-blue)';
  return {
    background: `color-mix(in srgb, ${accent} 15%, transparent)`,
    color: accent,
  };
}

function versionBadgeStyle(): React.CSSProperties {
  return {
    background: 'color-mix(in srgb, var(--accent-blue) 10%, transparent)',
    color: 'var(--accent-blue)',
  };
}

function formatSimilarity(score: number): string {
  return `${Math.round(score * 100)}% match`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function LoadingSkeletons() {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div
          key={i}
          className="rounded-lg p-4 space-y-3"
          style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
        >
          <Skeleton className="h-4 w-3/4" />
          <div className="flex gap-2">
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-5 w-10 rounded-full" />
          </div>
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
          <Skeleton className="h-3 w-4/6" />
        </div>
      ))}
    </div>
  );
}

interface RunbookCardProps {
  runbook: RunbookResult;
  showSimilarity: boolean;
}

function RunbookCard({ runbook, showSimilarity }: RunbookCardProps) {
  return (
    <div
      className="rounded-lg p-4 flex flex-col gap-3 transition-colors"
      style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border)' }}
    >
      {/* Title */}
      <p
        className="text-[13px] font-semibold leading-snug"
        style={{ color: 'var(--text-primary)' }}
      >
        {runbook.title}
      </p>

      {/* Badges row */}
      <div className="flex flex-wrap items-center gap-2">
        <span
          className="text-[11px] px-2 py-0.5 rounded-full font-medium capitalize"
          style={domainBadgeStyle(runbook.domain)}
        >
          {runbook.domain}
        </span>
        <span
          className="text-[11px] px-2 py-0.5 rounded-full font-medium"
          style={versionBadgeStyle()}
        >
          {runbook.version}
        </span>
        {showSimilarity && runbook.similarity > 0 && (
          <span
            className="text-[11px] ml-auto"
            style={{ color: 'var(--text-secondary)' }}
          >
            {formatSimilarity(runbook.similarity)}
          </span>
        )}
      </div>

      {/* Excerpt */}
      <p
        className="text-[12px] leading-relaxed line-clamp-3"
        style={{ color: 'var(--text-secondary)' }}
      >
        {runbook.content_excerpt}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function RunbookTab() {
  const [query, setQuery] = useState('');
  const [activeDomain, setActiveDomain] = useState<Domain>('all');
  const [results, setResults] = useState<RunbookResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const fetchRunbooks = useCallback(async (searchQuery: string, domain: Domain) => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({ limit: '12' });
      if (searchQuery) params.set('query', searchQuery);
      if (domain !== 'all') params.set('domain', domain);

      const res = await fetch(`/api/proxy/runbooks?${params.toString()}`, {
        signal: AbortSignal.timeout(15000),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data?.error ?? `HTTP ${res.status}`);
      }

      // Backend may return array directly or wrapped in { results: [] }
      const items: RunbookResult[] = Array.isArray(data) ? data : (data.results ?? []);
      setResults(items);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setError(`Failed to load runbooks: ${message}`);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial load — browse mode with a default browse query
  useEffect(() => {
    fetchRunbooks('azure operations', 'all');
  }, [fetchRunbooks]);

  // Debounced search on query/domain change (skip initial mount)
  useEffect(() => {
    if (!hasSearched) return;

    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (query.length > 0 && query.length < 2) return; // wait for 2+ chars

    debounceRef.current = setTimeout(() => {
      fetchRunbooks(query || 'azure operations', activeDomain);
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, activeDomain, hasSearched, fetchRunbooks]);

  function handleQueryChange(e: React.ChangeEvent<HTMLInputElement>) {
    setHasSearched(true);
    setQuery(e.target.value);
  }

  function handleDomainChange(domain: Domain) {
    setHasSearched(true);
    setActiveDomain(domain);
  }

  const showSimilarity = hasSearched && query.length >= 2;

  return (
    <div className="flex flex-col gap-4">
      {/* Search bar */}
      <div className="relative">
        <Search
          className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 pointer-events-none"
          style={{ color: 'var(--text-secondary)' }}
        />
        <input
          type="text"
          placeholder="Search runbooks by keyword or topic..."
          value={query}
          onChange={handleQueryChange}
          className="w-full rounded-lg pl-9 pr-4 py-2.5 text-[13px] outline-none transition-colors"
          style={{
            background: 'var(--bg-subtle)',
            border: '1px solid var(--border)',
            color: 'var(--text-primary)',
          }}
          onFocus={(e) => { e.currentTarget.style.borderColor = 'var(--accent-blue)'; }}
          onBlur={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; }}
        />
      </div>

      {/* Domain filter chips */}
      <div className="flex flex-wrap gap-2">
        {DOMAINS.map(({ id, label }) => {
          const isActive = activeDomain === id;
          return (
            <button
              key={id}
              onClick={() => handleDomainChange(id)}
              className="text-[12px] px-3 py-1 rounded-full font-medium transition-colors cursor-pointer"
              style={
                isActive
                  ? {
                      background: 'color-mix(in srgb, var(--accent-blue) 20%, transparent)',
                      color: 'var(--accent-blue)',
                      border: '1px solid var(--accent-blue)',
                    }
                  : {
                      background: 'var(--bg-subtle)',
                      color: 'var(--text-secondary)',
                      border: '1px solid var(--border)',
                    }
              }
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* Content area */}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {!error && loading && <LoadingSkeletons />}

      {!error && !loading && !hasSearched && results.length === 0 && (
        <div
          className="flex flex-col items-center justify-center py-16 gap-3"
          style={{ color: 'var(--text-secondary)' }}
        >
          <BookOpen className="h-10 w-10 opacity-30" />
          <p className="text-sm">Search for runbooks by typing above.</p>
        </div>
      )}

      {!error && !loading && hasSearched && results.length === 0 && (
        <div
          className="flex flex-col items-center justify-center py-16 gap-3"
          style={{ color: 'var(--text-secondary)' }}
        >
          <Search className="h-10 w-10 opacity-30" />
          <p className="text-sm">No runbooks found for your query.</p>
          <p className="text-xs opacity-60">Try a different keyword or clear the domain filter.</p>
        </div>
      )}

      {!error && !loading && results.length > 0 && (
        <>
          <div
            className="text-[12px] pb-1"
            style={{ color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}
          >
            {results.length} runbook{results.length !== 1 ? 's' : ''}
            {activeDomain !== 'all' && ` · ${activeDomain}`}
            {showSimilarity && query && ` · "${query}"`}
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {results.map((rb) => (
              <RunbookCard key={rb.id} runbook={rb} showSimilarity={showSimilarity} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
