import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// formatColdSyncAge lives in the dashboard template; load it from there.
const here = path.dirname(fileURLToPath(import.meta.url));
const html = readFileSync(path.join(here, "../src/dca_service/templates/index.html"), "utf8");
const start = html.indexOf("function formatColdSyncAge");
const end = html.indexOf("\n        }\n", start) + "\n        }\n".length;
const formatColdSyncAge = new Function(`${html.slice(start, end)}; return formatColdSyncAge;`)();

const MIN = 60 * 1000;
const now = Date.UTC(2026, 9, 14, 20, 0);

describe("formatColdSyncAge", () => {
  it.each([
    [0, "synced just now"],
    [59 * 1000, "synced just now"],
    [MIN, "synced 1m ago"],
    [59 * MIN, "synced 59m ago"],
    [60 * MIN, "synced 1h ago"],
    [47 * 60 * MIN, "synced 47h ago"],
    [48 * 60 * MIN, "synced 2d ago"],
    [-5 * MIN, "synced just now"],
  ])("%i ms ago reads %s", (ago, text) => {
    expect(formatColdSyncAge(now - ago, now)).toBe(text);
  });
});
