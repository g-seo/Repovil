import type { RankingQuery } from "./ranking-query";

export type Category = {
  name: string;
  slug: string;
  display_order: number;
};

export type RankingItem = {
  github_id: number;
  owner: string;
  name: string;
  description: string | null;
  github_url: string;
  language: string | null;
  current_stars: number;
  score: number;
  star_gain: number;
  is_estimated: boolean;
  categories: Category[];
};

export type RankingsResponse = {
  state: "preparing" | "ready";
  tracking_run_id: number | null;
  calculated_at: string | null;
  period: RankingQuery["period"];
  category: string | null;
  items: RankingItem[];
  pagination: {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
  };
};

const DEFAULT_API_URL = "http://127.0.0.1:8000";

function apiUrl(path: string): string {
  const configured = process.env.REPOVIL_API_URL ?? DEFAULT_API_URL;
  return new URL(path, `${configured.replace(/\/$/, "")}/`).toString();
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(apiUrl(path), {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Repovil API request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchCategories(): Promise<Category[]> {
  return getJson<Category[]>("categories");
}

export function fetchRankings(query: RankingQuery): Promise<RankingsResponse> {
  const parameters = new URLSearchParams({
    period: query.period,
    page: String(query.page),
  });
  if (query.category) {
    parameters.set("category", query.category);
  }
  return getJson<RankingsResponse>(`rankings?${parameters.toString()}`);
}
