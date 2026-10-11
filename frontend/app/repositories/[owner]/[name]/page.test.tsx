import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  fetchRepository,
  type Repository,
  type StarHistoryPoint,
  type StarHistoryResponse,
} from "../../../../lib/api";
import RepositoryError from "./error";
import RepositoryLoading from "./loading";
import RepositoryNotFound from "./not-found";
import RepositoryDetailRoute, { RepositoryDetailPage } from "./page";
import { recentHistoryPoints, StarHistoryGraph } from "./star-history-graph";

const NOW = new Date("2026-10-11T12:00:00Z");
const repository: Repository = {
  github_id: 123,
  owner: "current-owner",
  name: "current-name",
  description: "A repository that moved to its current identity.",
  github_url: "https://github.com/current-owner/current-name",
  language: "TypeScript",
  current_stars: 12345,
  status: "active",
  discovered_at: "2026-08-01T00:00:00Z",
  tracking_started_at: "2026-09-01T00:00:00Z",
  categories: [{ name: "AI Agents", slug: "ai-agents", display_order: 1 }],
};

function history(points: StarHistoryPoint[]): StarHistoryResponse {
  return { github_id: 123, owner: "current-owner", name: "current-name", points };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StarHistoryGraph", () => {
  it("renders actual-only history with an accessible summary and data table", () => {
    const markup = renderToStaticMarkup(
      <StarHistoryGraph
        now={NOW}
        points={[
          { captured_at: "2026-09-20T12:00:00Z", star_count: 100, is_estimated: false },
          { captured_at: "2026-10-11T12:00:00Z", star_count: 140, is_estimated: false },
        ]}
      />,
    );

    expect(markup).toContain("Star history");
    expect(markup).toContain("2 points over the last 30 days: 2 actual and 0 estimated");
    expect(markup.match(/chart-point actual/g)).toHaveLength(2);
    expect(markup).not.toContain("chart-point estimated");
    expect(markup).toContain("Accessible star history data");
  });

  it("renders estimated-only history with dashed segments and an estimate explanation", () => {
    const markup = renderToStaticMarkup(
      <StarHistoryGraph
        now={NOW}
        points={[
          { captured_at: "2026-09-15T00:00:00Z", star_count: 70, is_estimated: true },
          { captured_at: "2026-10-01T00:00:00Z", star_count: 90, is_estimated: true },
        ]}
      />,
    );

    expect(markup.match(/chart-point estimated/g)).toHaveLength(2);
    expect(markup).toContain("chart-segment estimated");
    expect(markup).toContain("may not reflect unstars or exact UTC day boundaries");
  });

  it("keeps the inclusive 30-day boundary, drops older data, and prefers actual by date", () => {
    const points: StarHistoryPoint[] = [
      { captured_at: "2026-09-11T11:59:59Z", star_count: 800, is_estimated: false },
      { captured_at: "2026-09-11T12:00:00Z", star_count: 850, is_estimated: false },
      { captured_at: "2026-10-01T00:00:00Z", star_count: 900, is_estimated: true },
      { captured_at: "2026-10-01T06:00:00Z", star_count: 901, is_estimated: false },
      { captured_at: "2026-10-05T00:00:00Z", star_count: 950, is_estimated: true },
      { captured_at: "2026-10-11T12:00:00Z", star_count: 1000, is_estimated: false },
    ];

    const recent = recentHistoryPoints(points, NOW);
    const markup = renderToStaticMarkup(<StarHistoryGraph points={points} now={NOW} />);

    expect(recent.map((point) => point.star_count)).toEqual([850, 901, 950, 1000]);
    expect(markup).toContain("4 points over the last 30 days: 3 actual and 1 estimated");
    expect(markup).not.toContain("800 stars");
    expect(markup).not.toContain("900 stars");
  });

  it("renders an empty state when no valid recent history exists", () => {
    const markup = renderToStaticMarkup(
      <StarHistoryGraph
        now={NOW}
        points={[{ captured_at: "2026-08-01T00:00:00Z", star_count: 10, is_estimated: false }]}
      />,
    );

    expect(markup).toContain("No recent star history yet");
    expect(markup).not.toContain("star-chart");
  });
});

describe("RepositoryDetailPage", () => {
  it("uses current API metadata for a renamed repository and renders its GitHub link", () => {
    const markup = renderToStaticMarkup(
      <RepositoryDetailPage repository={repository} history={history([])} now={NOW} />,
    );

    expect(markup).toContain("current-owner/");
    expect(markup).toContain("current-name");
    expect(markup).toContain("A repository that moved to its current identity.");
    expect(markup).toContain("12,345");
    expect(markup).toContain("TypeScript");
    expect(markup).toContain("AI Agents");
    expect(markup).toContain('href="https://github.com/current-owner/current-name"');
    expect(markup).toContain('target="_blank"');
  });
});

describe("repository route data loading", () => {
  it("loads metadata and history from the read-only API", async () => {
    const responseHistory = history([]);
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      return new Response(JSON.stringify(url.endsWith("/star-history") ? responseHistory : repository), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const page = await RepositoryDetailRoute({
      params: Promise.resolve({ owner: "current-owner", name: "current-name" }),
    });
    const markup = renderToStaticMarkup(page);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([
      "http://127.0.0.1:8000/repositories/current-owner/current-name",
      "http://127.0.0.1:8000/repositories/current-owner/current-name/star-history",
    ]);
    expect(markup).toContain("current-owner/");
  });

  it("preserves API status on failures so the route can select not-found", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("missing", { status: 404 })));

    await expect(fetchRepository("missing", "repository")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
    } satisfies Partial<ApiError>);
  });

  it("turns the API not-found contract into the Next.js not-found boundary", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("missing", { status: 404 })));

    await expect(
      RepositoryDetailRoute({
        params: Promise.resolve({ owner: "missing", name: "repository" }),
      }),
    ).rejects.toMatchObject({ digest: "NEXT_HTTP_ERROR_FALLBACK;404" });
  });
});

describe("repository route states", () => {
  it("renders distinct not-found, API error, and loading states", () => {
    const notFound = renderToStaticMarkup(<RepositoryNotFound />);
    const error = renderToStaticMarkup(
      <RepositoryError
        error={Object.assign(new Error("failed"), { digest: "detail123" })}
        reset={() => {}}
      />,
    );
    const loading = renderToStaticMarkup(<RepositoryLoading />);

    expect(notFound).toContain("This repository isn’t tracked");
    expect(notFound).toContain("Return to rankings");
    expect(error).toContain('role="alert"');
    expect(error).toContain("We couldn’t load this repository");
    expect(error).toContain("Reference: detail123");
    expect(loading).toContain('aria-busy="true"');
    expect(loading).toContain("Building the star timeline");
  });
});
