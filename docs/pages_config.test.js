import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

describe("GitHub Pages configuration", () => {
  it("excludes internal superpowers planning docs from Jekyll rendering", () => {
    const config = readFileSync(join(process.cwd(), "docs", "_config.yml"), "utf8");

    expect(config).toContain("exclude:");
    expect(config).toMatch(/-\s+superpowers\/?/);
  });
});
