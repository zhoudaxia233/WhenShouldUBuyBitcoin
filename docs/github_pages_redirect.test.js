import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// The old GitHub Pages copy (served on daxia.io, the owner's custom domain,
// and on github.io) sends visitors to the maintained site.
function redirectScript() {
  const html = readFileSync(join(process.cwd(), "docs", "index.html"), "utf8");
  const start = html.indexOf("const SATSFLOW_ANALYSIS_URL");
  return html.slice(start, html.indexOf("</script>", start));
}

function visit(href) {
  const url = new URL(href);
  const location = {
    hostname: url.hostname,
    pathname: url.pathname,
    hash: url.hash,
    href: url.href,
    replaced: null,
    replace(target) { this.replaced = target; },
  };
  new Function("window", redirectScript())({ location });
  return location.replaced;
}

describe("GitHub Pages canonical analysis redirect", () => {
  it("sends the Pages copy on daxia.io to the maintained site, keeping the view", () => {
    expect(visit("https://daxia.io/WhenShouldUBuyBitcoin/")).toBe("https://btc.daxia.io/analysis/");
    expect(visit("https://daxia.io/WhenShouldUBuyBitcoin/#backtest")).toBe("https://btc.daxia.io/analysis/#backtest");
    expect(visit("https://daxia.io/WhenShouldUBuyBitcoin/index.html#charts")).toBe("https://btc.daxia.io/analysis/#charts");
  });

  it("also covers the github.io address", () => {
    expect(visit("https://zhoudaxia233.github.io/WhenShouldUBuyBitcoin/")).toBe("https://btc.daxia.io/analysis/");
  });

  it("leaves the maintained site and local copies alone", () => {
    expect(visit("https://btc.daxia.io/analysis/")).toBeNull();
    expect(visit("https://btc.daxia.io/analysis/#charts")).toBeNull();
    expect(visit("http://localhost:8000/index.html")).toBeNull();
    expect(visit("http://127.0.0.1:8793/analysis/")).toBeNull();
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
