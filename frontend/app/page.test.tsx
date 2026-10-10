import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home", () => {
  it("renders the application shell", () => {
    const markup = renderToStaticMarkup(<Home />);

    expect(markup).toContain("<h1>Repovil</h1>");
    expect(markup).toContain("momentum tracking is being prepared");
  });
});

