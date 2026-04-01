export type ScoreExplanation = {
  components?: Record<string, number>;
  rationale?: string[];
  confidence?: string;
};

export type FilingListItem = {
  id: number;
  company_id: number;
  company_name: string;
  ticker?: string | null;
  accession_number: string;
  form_type: string;
  normalized_form_type: string;
  filed_at: string;
  title?: string | null;
  importance_score: number;
  market_cap_score: number;
  impact_score: number;
  composite_score: number;
  score_explanation: ScoreExplanation;
  summary_status: string;
  summary_tier: string;
  source_type: string;
  event_type?: string | null;
  priority_reason: string;
  is_official_source: boolean;
  dedupe_group_id?: string | null;
  freshness_bucket: string;
  summary: string;
  original_document_url: string;
  pdf_download_url?: string | null;
};

export type ExtractedEntity = {
  name: string;
  type: string;
  context: string;
};

export type FilingDiff = {
  added_risks?: string[];
  removed_risks?: string[];
  financial_deltas?: string[];
  guidance_changes?: string[];
  pipeline_updates?: string[];
  summary?: string;
};

export type FilingDetail = FilingListItem & {
  parsed_sections: Record<string, string>;
  key_takeaways: string[];
  material_changes: string[];
  risk_flags: string[];
  opportunity_flags: string[];
  evidence_sections: string[];
  entities?: ExtractedEntity[];
  prior_comparable_filing_id?: number | null;
  prior_comparable_filing_url?: string | null;
  diff_json?: FilingDiff;
  diff_status?: string;
  related_news?: NewsItem[];
};

export type Company = {
  id: number;
  cik: string;
  ticker?: string | null;
  name: string;
  exchange?: string | null;
  sic?: string | null;
  sic_description?: string | null;
  market_cap?: number | null;
  market_cap_currency: string;
  market_cap_source?: string | null;
  universe_reason: string;
  universe_reason_label: string;
  is_active: boolean;
};

export type CompanyTrend = {
  direction: string;
  trend_score: number;
  risk_trend: string;
  opportunity_trend: string;
  filings_analyzed: number;
};

export type ClinicalTrial = {
  id: number;
  nct_id: string;
  company_id: number | null;
  company_name?: string | null;
  ticker?: string | null;
  title: string;
  phase: string | null;
  status: string;
  conditions: string[];
  interventions: string[];
  sponsor: string | null;
  start_date: string | null;
  primary_completion_date: string | null;
  last_update_date: string | null;
  enrollment: number | null;
  study_type: string | null;
};

export type CompanyDetail = Company & {
  market_cap_updated_at?: string | null;
  filings_count: number;
  news_count: number;
  recent_filings: FilingListItem[];
  recent_news: NewsItem[];
  timeline: TimelineEvent[];
  latest_filing?: FilingListItem | null;
  latest_news?: NewsItem | null;
  latest_trial?: ClinicalTrial | null;
  business_summary: string;
  change_summary: string[];
  catalyst_summary: string[];
  catalysts: TimelineEvent[];
  trend?: CompanyTrend;
  pipeline?: Record<string, ClinicalTrial[]>;
};

export type NewsItem = {
  id: number;
  source_name: string;
  title: string;
  canonical_url: string;
  excerpt?: string | null;
  published_at: string;
  mentioned_companies: string[];
  company_tag_ids: number[];
  topic_tags: string[];
  importance_score: number;
  market_cap_score: number;
  composite_score: number;
  score_explanation: ScoreExplanation;
  summary_status: string;
  summary_tier: string;
  source_type: string;
  event_type?: string | null;
  priority_reason: string;
  is_official_source: boolean;
  dedupe_group_id?: string | null;
  freshness_bucket: string;
  summary: string;
  key_takeaways: string[];
};

export type TimelineEvent = {
  id: string;
  item_type: string;
  item_id: number;
  occurred_at: string;
  title: string;
  summary: string;
  company_ids: number[];
  company_names: string[];
  href?: string | null;
  external_url?: string | null;
  source_type: string;
  event_type?: string | null;
  priority_reason: string;
  summary_tier: string;
  is_official_source: boolean;
  freshness_bucket: string;
  composite_score: number;
  tags: string[];
};

export type SummaryBudgetSnapshot = {
  used: number;
  limit: number;
  remaining: number;
  used_usd: number;
  limit_usd: number;
  remaining_usd: number;
};

export type ModelUsageSnapshot = {
  count: number;
  prompt_tokens: number;
  completion_tokens: number;
  reasoning_tokens: number;
  cached_input_tokens: number;
  estimated_cost_usd: number;
};

export type SummaryBudgetOverview = {
  filing: SummaryBudgetSnapshot;
  news: SummaryBudgetSnapshot;
  override: SummaryBudgetSnapshot;
  diff: SummaryBudgetSnapshot;
  digest: SummaryBudgetSnapshot;
  total_used_usd: number;
  total_limit_usd: number;
  total_remaining_usd: number;
  seven_day_average_usd: number;
  spend_by_model: Record<string, ModelUsageSnapshot>;
};

export type Digest = {
  id: number;
  digest_type: string;
  title: string;
  window_start: string;
  window_end: string;
  published_at: string;
  narrative_summary: string;
  payload: {
    filings?: Array<{ id: number; title: string; company_id: number; company_name?: string; score: number }>;
    news?: Array<{ id: number; title: string; source_name: string; mentioned_companies?: string[]; company_tag_ids?: number[]; score: number }>;
  };
};

export type DashboardData = {
  latest_filings: FilingListItem[];
  latest_news: NewsItem[];
  important_filings: FilingListItem[];
  important_news: NewsItem[];
  top_filings: FilingListItem[];
  top_news: NewsItem[];
  watchlist_highlights: WatchlistHighlight[];
  upcoming_regulatory_events: TimelineEvent[];
  recent_trials: ClinicalTrial[];
  latest_digest?: Digest | null;
  counts: Record<string, number>;
  ai_budget: SummaryBudgetOverview;
  queue_counts: Record<string, number>;
};

export type PaginatedResponse<T> = {
  items: T[];
  total: number;
  offset: number;
  limit: number;
};

export type FilingFilters = {
  limit?: number;
  offset?: number;
  company_id?: number;
  form_type?: string;
  search?: string;
  sort_by?: string;
  recent_days?: number;
  watchlist_id?: number;
  sort_mode?: string;
};

export type NewsFilters = {
  limit?: number;
  offset?: number;
  source_name?: string;
  search?: string;
  sort_by?: string;
  recent_days?: number;
  watchlist_id?: number;
  sort_mode?: string;
};

export type Watchlist = {
  id: number;
  name: string;
  description?: string | null;
  preset_key?: string | null;
  company_ids: number[];
  form_types: string[];
  topic_tags: string[];
  created_at: string;
  updated_at: string;
};

export type WatchlistHighlight = {
  watchlist_id: number;
  watchlist_name: string;
  watchlist_description?: string | null;
  highlights: TimelineEvent[];
};

export type WatchlistFeed = {
  watchlist: Watchlist;
  filings: FilingListItem[];
  news: NewsItem[];
  trials: ClinicalTrial[];
  catalysts: TimelineEvent[];
  highlights: TimelineEvent[];
  timeline: TimelineEvent[];
};

export type TrialFilters = {
  limit?: number;
  offset?: number;
  company_id?: number;
  phase?: string;
  status?: string;
  search?: string;
};

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1")
  .trim()
  .replace(/\/$/, "");
const API_REQUEST_TIMEOUT_MS = 8000;
const DASHBOARD_TIMEOUT_MS = 15000;
const MAX_RETRIES = 2;
const RETRY_BACKOFF_MS = [500, 1000];

function logApiFailure(path: string, error: unknown, extra?: Record<string, unknown>) {
  if (typeof window !== "undefined") {
    return;
  }
  const detail =
    error instanceof Error
      ? { name: error.name, message: error.message, stack: error.stack }
      : { message: String(error) };
  console.error("[api] request failed", {
    path,
    apiBase: API_BASE,
    ...extra,
    ...detail,
  });
}

function isRetryable(error: unknown, status?: number): boolean {
  if (error instanceof Error && error.name === "AbortError") return true;
  if (status && (status === 502 || status === 503 || status === 504 || status === 408)) return true;
  if (error instanceof TypeError) return true; // network error
  return false;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchJSON<T>(path: string, revalidate?: number, timeoutMs?: number): Promise<T> {
  const effectiveTimeout = timeoutMs ?? API_REQUEST_TIMEOUT_MS;
  let lastError: unknown;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    if (attempt > 0) {
      await sleep(RETRY_BACKOFF_MS[attempt - 1] ?? 1000);
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), effectiveTimeout);

    try {
      const response = await fetch(`${API_BASE}${path}`, {
        next: revalidate !== undefined ? { revalidate } : undefined,
        cache: revalidate !== undefined ? undefined : "no-store",
        signal: controller.signal,
      });
      if (!response.ok) {
        const error = new Error(`Failed to fetch ${path}: ${response.status}`);
        if (attempt < MAX_RETRIES && isRetryable(error, response.status)) {
          logApiFailure(path, error, { status: response.status, attempt, willRetry: true });
          lastError = error;
          continue;
        }
        logApiFailure(path, error, { status: response.status, revalidate });
        throw error;
      }
      return response.json() as Promise<T>;
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        const timeoutError = new Error(`Failed to fetch ${path}: request timed out after ${effectiveTimeout}ms`);
        if (attempt < MAX_RETRIES) {
          logApiFailure(path, timeoutError, { timeoutMs: effectiveTimeout, attempt, willRetry: true });
          lastError = timeoutError;
          continue;
        }
        logApiFailure(path, timeoutError, { timeoutMs: effectiveTimeout, revalidate });
        throw timeoutError;
      }
      if (attempt < MAX_RETRIES && isRetryable(error)) {
        logApiFailure(path, error, { attempt, willRetry: true });
        lastError = error;
        continue;
      }
      logApiFailure(path, error, { revalidate });
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  throw lastError;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      parts.push(`${key}=${encodeURIComponent(value)}`);
    }
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

export const api = {
  dashboard: () => fetchJSON<DashboardData>("/dashboard", undefined, DASHBOARD_TIMEOUT_MS),
  companies: (search?: string) =>
    fetchJSON<Company[]>(`/companies${buildQuery({ search })}`, 60),
  company: (id: string) => fetchJSON<CompanyDetail>(`/companies/${id}`),
  filings: (filters?: FilingFilters) =>
    fetchJSON<PaginatedResponse<FilingListItem>>(
      `/filings${buildQuery(filters ?? {})}`,
      60
    ),
  filing: (id: string) => fetchJSON<FilingDetail>(`/filings/${id}`),
  companyTimeline: (id: string, limit?: number) =>
    fetchJSON<TimelineEvent[]>(`/companies/${id}/timeline${buildQuery({ limit })}`),
  news: (filters?: NewsFilters) =>
    fetchJSON<PaginatedResponse<NewsItem>>(
      `/news${buildQuery(filters ?? {})}`,
      60
    ),
  digests: () => fetchJSON<Digest[]>("/digests", 60),
  trials: (filters?: TrialFilters) =>
    fetchJSON<PaginatedResponse<ClinicalTrial>>(
      `/trials${buildQuery(filters ?? {})}`,
      60
    ),
  watchlists: () => fetchJSON<Watchlist[]>("/watchlists", 0),
  watchlist: (id: string) => fetchJSON<Watchlist>(`/watchlists/${id}`),
  watchlistBriefing: (id: string, limit?: number) =>
    fetchJSON<WatchlistFeed>(`/watchlists/${id}/briefing${buildQuery({ limit })}`, 0),
  watchlistFeed: (id: string, limit?: number) =>
    fetchJSON<WatchlistFeed>(`/watchlists/${id}/feed${buildQuery({ limit })}`, 0),
};

export async function createWatchlist(params: {
  name: string;
  description?: string;
  company_ids?: number[];
  form_types?: string[];
  topic_tags?: string[];
}): Promise<Watchlist> {
  const query = buildQuery({
    name: params.name,
    description: params.description,
    company_ids: params.company_ids?.join(","),
    form_types: params.form_types?.join(","),
    topic_tags: params.topic_tags?.join(","),
  });
  const response = await fetch(`${API_BASE}/watchlists${query}`, {
    method: "POST",
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Failed to create watchlist: ${response.status}`);
  return response.json() as Promise<Watchlist>;
}

export async function createStarterWatchlists(): Promise<Watchlist[]> {
  const response = await fetch(`${API_BASE}/watchlists/starter`, {
    method: "POST",
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Failed to create starter watchlists: ${response.status}`);
  return response.json() as Promise<Watchlist[]>;
}

export async function addCompaniesToWatchlist(watchlistId: number, companyIds: number[]): Promise<Watchlist> {
  const response = await fetch(
    `${API_BASE}/watchlists/${watchlistId}/companies${buildQuery({ company_ids: companyIds.join(",") })}`,
    {
      method: "POST",
      cache: "no-store",
    }
  );
  if (!response.ok) throw new Error(`Failed to update watchlist: ${response.status}`);
  return response.json() as Promise<Watchlist>;
}

export async function deleteWatchlist(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/watchlists/${id}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Failed to delete watchlist: ${response.status}`);
}

export async function summarizeFiling(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/filings/${id}/summarize`, {
    method: "POST",
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Failed to summarize filing: ${response.status}`);
}

export async function summarizeNews(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/news/${id}/summarize`, {
    method: "POST",
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Failed to summarize news: ${response.status}`);
}

export function formatCurrency(value?: number | null): string {
  if (!value) {
    return "Unavailable";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 1
  }).format(value);
}

export function formatMarketCap(company: Pick<Company, "market_cap" | "ticker">): string {
  if (company.market_cap) {
    return formatCurrency(company.market_cap);
  }
  return company.ticker ? "Pending refresh" : "Unavailable";
}

export function formatDate(value: string): string {
  return new Date(value).toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short"
  });
}
