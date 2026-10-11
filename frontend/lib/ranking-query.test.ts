import { describe, expect, it } from "vitest";

import { buildRankingHref, parseRankingQuery } from "./ranking-query";

describe("parseRankingQuery", () => {
  it("defaults invalid and missing values safely", () => {
    expect(parseRankingQuery({ period: "year", page: "0" })).toEqual({
      period: "7d",
      category: undefined,
      page: 1,
    });
    expect(parseRankingQuery({ page: "2.5", category: "  " })).toEqual({
      period: "7d",
      category: undefined,
      page: 1,
    });
  });

  it("reads shared filter state from the first URL value", () => {
    expect(
      parseRankingQuery({
        period: ["30d", "24h"],
        category: ["ai-agents", "skills"],
        page: ["3", "4"],
      }),
    ).toEqual({ period: "30d", category: "ai-agents", page: 3 });
  });
});

describe("buildRankingHref", () => {
  it("preserves filters and omits the default first page", () => {
    expect(buildRankingHref({ period: "7d", category: "mcp-servers", page: 1 })).toBe(
      "/?period=7d&category=mcp-servers",
    );
    expect(buildRankingHref({ period: "30d", category: "mcp-servers", page: 4 })).toBe(
      "/?period=30d&category=mcp-servers&page=4",
    );
  });
});
