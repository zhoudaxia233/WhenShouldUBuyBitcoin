import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// A new buy from another exchange starts on the exchange of the latest one.
const here = path.dirname(fileURLToPath(import.meta.url));
const html = readFileSync(path.join(here, "../src/dca_service/templates/index.html"), "utf8");

function load(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found`);
  const end = html.indexOf("\n        }\n", start) + "\n        }\n".length;
  return new Function(`${html.slice(start, end)}; return ${name};`)();
}

const defaultExternalBuyVenue = load("defaultExternalBuyVenue");

describe("defaultExternalBuyVenue", () => {
  it("takes the exchange of the newest buy from another exchange", () => {
    const transactions = [
      { source: "BINANCE", venue: null },
      { source: "EXTERNAL", venue: "Bitvavo" },
      { source: "EXTERNAL", venue: "Kraken Pro" },
    ];
    expect(defaultExternalBuyVenue(transactions)).toBe("Bitvavo");
  });

  it("keeps a typed exchange name", () => {
    expect(defaultExternalBuyVenue([{ source: "EXTERNAL", venue: "Coinbase" }])).toBe("Coinbase");
  });

  it("falls back to Kraken Pro with no buys from other exchanges yet", () => {
    expect(defaultExternalBuyVenue([])).toBe("Kraken Pro");
    expect(defaultExternalBuyVenue([{ source: "BINANCE" }])).toBe("Kraken Pro");
    expect(defaultExternalBuyVenue(undefined)).toBe("Kraken Pro");
  });
});
