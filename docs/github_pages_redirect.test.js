import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

describe("GitHub Pages canonical analysis redirect", () => {
  it("redirects the GitHub Pages host to SatsFlow analysis without affecting SatsFlow itself", () => {
    const html = readFileSync(join(process.cwd(), "docs", "index.html"), "utf8");

    expect(html).toContain('const SATSFLOW_ANALYSIS_URL = "https://btc.daxia.io/analysis/";');
    expect(html).toContain('const GITHUB_PAGES_HOST = "zhoudaxia233.github.io";');
    expect(html).toContain("window.location.hostname === GITHUB_PAGES_HOST");
    expect(html).toContain("window.location.href !== SATSFLOW_ANALYSIS_URL");
    expect(html).toContain("window.location.replace(SATSFLOW_ANALYSIS_URL)");
  });
});

describe("Generated data workflow", () => {
  it("does not commit generated chart and data churn back to the repository", () => {
    const workflow = readFileSync(
      join(process.cwd(), ".github", "workflows", "update-data.yml"),
      "utf8",
    );

    expect(workflow).not.toContain("git add docs/data");
    expect(workflow).not.toContain("git commit");
    expect(workflow).not.toContain("git push");
  });
});
