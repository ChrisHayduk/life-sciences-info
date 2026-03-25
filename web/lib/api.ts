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
  summary: string;
  original_document_url: string;
  pdf_download_url?: string | null;
};

export type FilingDetail = FilingListItem & {
  parsed_sections: Record<string, string>;
  key_takeaways: string[];
  material_changes: string[];
  risk_flags: string[];
  opportunity_flags: string[];
  evidence_sections: string[];
  prior_comparable_filing_id?: number | null;
  prior_comparable_filing_url?: string | null;
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

export type CompanyDetail = Company & {
  market_cap_updated_at?: string | null;
  filings_count: number;
  news_count: number;
  recent_filings: FilingListItem[];
  recent_news: NewsItem[];
};

export type NewsItem = {
  id: number;
  source_name: string;
  title: string;
  canonical_url: string;
  excerpt?: string | null;
  published_at: string;
  mentioned_companies: string[];
  topic_tags: string[];
  importance_score: number;
  market_cap_score: number;
  composite_score: number;
  score_explanation: ScoreExplanation;
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
    filings?: Array<{ id: number; title: string; company_id: number; score: number }>;
    news?: Array<{ id: number; title: string; source_name: string; score: number }>;
  };
};

export type DashboardData = {
  top_filings: FilingListItem[];
  top_news: NewsItem[];
  latest_digest?: Digest | null;
  counts: Record<string, number>;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

async function fetchJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to fetch ${path}: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  dashboard: () => fetchJSON<DashboardData>("/dashboard"),
  companies: () => fetchJSON<Company[]>("/companies"),
  company: (id: string) => fetchJSON<CompanyDetail>(`/companies/${id}`),
  filings: () => fetchJSON<FilingListItem[]>("/filings"),
  filing: (id: string) => fetchJSON<FilingDetail>(`/filings/${id}`),
  news: () => fetchJSON<NewsItem[]>("/news"),
  digests: () => fetchJSON<Digest[]>("/digests")
};

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
