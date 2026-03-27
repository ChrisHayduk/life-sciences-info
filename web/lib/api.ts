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
  summary: string;
  key_takeaways: string[];
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
  top_filings: FilingListItem[];
  top_news: NewsItem[];
  recent_trials: ClinicalTrial[];
  latest_digest?: Digest | null;
  counts: Record<string, number>;
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
};

export type NewsFilters = {
  limit?: number;
  offset?: number;
  source_name?: string;
  search?: string;
  sort_by?: string;
};

export type Watchlist = {
  id: number;
  name: string;
  company_ids: number[];
  form_types: string[];
  topic_tags: string[];
  created_at: string;
  updated_at: string;
};

export type WatchlistFeed = {
  watchlist: Watchlist;
  filings: FilingListItem[];
  news: NewsItem[];
};

export type TrialFilters = {
  limit?: number;
  offset?: number;
  company_id?: number;
  phase?: string;
  status?: string;
  search?: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

async function fetchJSON<T>(path: string, revalidate?: number): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    next: revalidate !== undefined ? { revalidate } : undefined,
    cache: revalidate !== undefined ? undefined : "no-store",
  });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${path}: ${response.status}`);
  }
  return response.json() as Promise<T>;
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
  dashboard: () => fetchJSON<DashboardData>("/dashboard"),
  companies: (search?: string) =>
    fetchJSON<Company[]>(`/companies${buildQuery({ search })}`, 60),
  company: (id: string) => fetchJSON<CompanyDetail>(`/companies/${id}`),
  filings: (filters?: FilingFilters) =>
    fetchJSON<PaginatedResponse<FilingListItem>>(
      `/filings${buildQuery(filters ?? {})}`,
      60
    ),
  filing: (id: string) => fetchJSON<FilingDetail>(`/filings/${id}`),
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
  watchlistFeed: (id: string, limit?: number) =>
    fetchJSON<WatchlistFeed>(`/watchlists/${id}/feed${buildQuery({ limit })}`, 0),
};

export async function createWatchlist(params: {
  name: string;
  company_ids?: number[];
  form_types?: string[];
  topic_tags?: string[];
}): Promise<Watchlist> {
  const query = buildQuery({
    name: params.name,
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

export async function deleteWatchlist(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/watchlists/${id}`, {
    method: "DELETE",
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Failed to delete watchlist: ${response.status}`);
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
