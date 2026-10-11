export const PERIODS = ["24h", "7d", "30d"] as const;

export type RankingPeriod = (typeof PERIODS)[number];

export type RankingQuery = {
  period: RankingPeriod;
  category?: string;
  page: number;
};

export type SearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export function parseRankingQuery(parameters: SearchParams): RankingQuery {
  const requestedPeriod = first(parameters.period);
  const period = PERIODS.find((candidate) => candidate === requestedPeriod) ?? "7d";
  const requestedCategory = first(parameters.category)?.trim();
  const requestedPage = Number(first(parameters.page));
  const page = Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1;

  return {
    period,
    category: requestedCategory || undefined,
    page,
  };
}

export function buildRankingHref(query: RankingQuery): string {
  const parameters = new URLSearchParams({ period: query.period });
  if (query.category) {
    parameters.set("category", query.category);
  }
  if (query.page > 1) {
    parameters.set("page", String(query.page));
  }
  return `/?${parameters.toString()}`;
}
