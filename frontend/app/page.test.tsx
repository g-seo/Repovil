import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Category, RankingsResponse } from "../lib/api";
import RankingError from "./error";
import Loading from "./loading";
import Home, { RankingPage } from "./page";

const categories: Category[] = [
  { name: "AI Agents", slug: "ai-agents", display_order: 1 },
  { name: "Skills", slug: "skills", display_order: 2 },
];

const ranking: RankingsResponse = {
  state: "ready",
  tracking_run_id: 42,
  calculated_at: "2026-10-11T12:00:00Z",
  period: "7d",
  category: null,
  items: [
    {
      github_id: 101,
      owner: "open-source",
      name: "agent-kit",
      description: "A fast toolkit for production agents.",
      github_url: "https://github.com/open-source/agent-kit",
      language: "Python",
      current_stars: 12345,
      score: 0.123456,
      star_gain: 678,
      is_estimated: true,
      categories: [categories[0]],
    },
  ],
  pagination: {
    page: 1,
    page_size: 20,
    total_items: 41,
    total_pages: 3,
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RankingPage", () => {
  it("renders filters, ranking fields, detail navigation, and external links", () => {
    const markup = renderToStaticMarkup(
      <RankingPage
        categories={categories}
        rankings={ranking}
        query={{ period: "7d", page: 1 }}
      />,
    );

    expect(markup).toContain("Find the AI projects");
    expect(markup).toContain('aria-current="page" href="/?period=7d"');
    expect(markup).toContain("Skills");
    expect(markup).toContain("open-source/");
    expect(markup).toContain("agent-kit");
    expect(markup).toContain("A fast toolkit for production agents.");
    expect(markup).toContain("12,345");
    expect(markup).toContain("+678");
    expect(markup).toContain("0.1235");
    expect(markup).toContain("Python");
    expect(markup).toContain("AI Agents");
    expect(markup).toContain("Estimated");
    expect(markup).toContain('href="/repositories/open-source/agent-kit"');
    expect(markup).toContain('href="https://github.com/open-source/agent-kit"');
    expect(markup).toContain('target="_blank"');
  });

  it("keeps selected filters in pagination links", () => {
    const response = {
      ...ranking,
      category: "skills",
      pagination: { ...ranking.pagination, page: 2 },
    };
    const markup = renderToStaticMarkup(
      <RankingPage
        categories={categories}
        rankings={response}
        query={{ period: "24h", category: "skills", page: 2 }}
      />,
    );

    expect(markup).toContain('href="/?period=24h&amp;category=skills"');
    expect(markup).toContain('href="/?period=24h&amp;category=skills&amp;page=3"');
    expect(markup).toContain("Page <strong>2</strong> of 3");
    expect(markup).toContain('aria-label="Rank 21"');
  });

  it("distinguishes preparing from a ready empty result", () => {
    const preparing = renderToStaticMarkup(
      <RankingPage
        categories={categories}
        rankings={{
          ...ranking,
          state: "preparing",
          tracking_run_id: null,
          calculated_at: null,
          items: [],
          pagination: { ...ranking.pagination, total_items: 0, total_pages: 0 },
        }}
        query={{ period: "7d", page: 1 }}
      />,
    );
    const empty = renderToStaticMarkup(
      <RankingPage
        categories={categories}
        rankings={{
          ...ranking,
          items: [],
          pagination: { ...ranking.pagination, total_items: 0, total_pages: 0 },
        }}
        query={{ period: "7d", page: 1 }}
      />,
    );

    expect(preparing).toContain("Ranking data is being prepared");
    expect(preparing).not.toContain("No repositories match");
    expect(empty).toContain("No repositories match these filters");
    expect(empty).not.toContain("Ranking data is being prepared");
    expect(empty).toContain("Skills");
  });
});

describe("Home data loading", () => {
  it("loads categories and the URL-selected ranking from FastAPI", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      const body = url.endsWith("/categories") ? categories : ranking;
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const page = await Home({
      searchParams: Promise.resolve({ period: "24h", category: "skills", page: "2" }),
    });
    const markup = renderToStaticMarkup(page);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain(
      "http://127.0.0.1:8000/rankings?period=24h&page=2&category=skills",
    );
    expect(markup).toContain("agent-kit");
  });

  it("throws on API errors so the retry boundary can render", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("unavailable", { status: 503 })),
    );

    await expect(Home({ searchParams: Promise.resolve({}) })).rejects.toThrow(
      "Repovil API request failed with status 503",
    );
  });
});

describe("route states", () => {
  it("renders accessible loading and retry states", () => {
    const loading = renderToStaticMarkup(<Loading />);
    const error = renderToStaticMarkup(
      <RankingError
        error={Object.assign(new Error("failed"), { digest: "abc123" })}
        reset={() => {}}
      />,
    );

    expect(loading).toContain('aria-live="polite"');
    expect(loading).toContain('aria-busy="true"');
    expect(loading).toContain("Loading momentum data");
    expect(error).toContain('role="alert"');
    expect(error).toContain("We couldn’t load the ranking");
    expect(error).toContain("Try again");
    expect(error).toContain("Reference: abc123");
  });
});
