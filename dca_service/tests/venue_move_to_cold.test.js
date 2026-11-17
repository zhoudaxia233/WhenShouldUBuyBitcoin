import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// Moving bitcoin from an exchange to cold storage: the dialog's decisions live
// in the dashboard template; load them from there.
const here = path.dirname(fileURLToPath(import.meta.url));
const html = readFileSync(path.join(here, "../src/dca_service/templates/index.html"), "utf8");

function load(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found`);
  const end = html.indexOf("\n        }\n", start) + "\n        }\n".length;
  return new Function(`${html.slice(start, end)}; return ${name};`)();
}

const venueMoveColdMode = load("venueMoveColdMode");
const venueMoveProblems = load("venueMoveProblems");
const venueMoveArrivedDefault = load("venueMoveArrivedDefault");
const venueEmptySince = load("venueEmptySince");
const coldVenueHintText = load("coldVenueHintText");
const coldSyncDue = load("coldSyncDue");
const venueMoveToast = load("venueMoveToast");

describe("venueMoveColdMode", () => {
  it("leaves cold storage to the key while a key is saved and not overridden by hand", () => {
    expect(venueMoveColdMode(true, "public_key")).toBe("key");
    expect(venueMoveColdMode(true, null)).toBe("key");
  });

  it("asks what arrived when cold storage is typed by hand or has no key", () => {
    expect(venueMoveColdMode(true, "manual")).toBe("manual");
    expect(venueMoveColdMode(false, "public_key")).toBe("manual");
    expect(venueMoveColdMode(false, null)).toBe("manual");
  });
});

describe("venueMoveProblems", () => {
  const ok = { left: "", arrived: "" };

  it("accepts moving everything with a fee taken off", () => {
    expect(venueMoveProblems(0.0049665, 0, 0.0049, "manual")).toEqual(ok);
  });

  it("accepts arrived equal to what left, compared in satoshis", () => {
    expect(venueMoveProblems(0.00192492, 0.001, 0.00092492, "manual")).toEqual(ok);
  });

  it("needs something to leave the exchange", () => {
    expect(venueMoveProblems(0.00192492, 0.00192492, 0.0001, "manual").left).toMatch(/less than/);
    expect(venueMoveProblems(0.00192492, 0.01, 0.0001, "manual").left).toMatch(/less than/);
    expect(venueMoveProblems(0.00192492, -1, 0.0001, "manual").left).not.toBe("");
  });

  it("needs a positive arrival no larger than what left", () => {
    expect(venueMoveProblems(0.002, 0, 0, "manual").arrived).toMatch(/more than 0/);
    expect(venueMoveProblems(0.002, 0.001, 0.0011, "manual").arrived).toMatch(/more than left/);
  });

  it("leaves unreadable text to the decimal field check", () => {
    expect(venueMoveProblems(0.002, NaN, NaN, "manual")).toEqual(ok);
  });

  it("does not ask for an arrival when cold storage is read from the key", () => {
    expect(venueMoveProblems(0.002, 0, NaN, "key")).toEqual(ok);
    expect(venueMoveProblems(0.002, 0.002, NaN, "key").left).toMatch(/less than/);
  });
});

describe("venueMoveArrivedDefault", () => {
  it("is what left the exchange, to the satoshi", () => {
    expect(venueMoveArrivedDefault(0.0049665, 0)).toBe("0.00496650");
    expect(venueMoveArrivedDefault(0.00192492, 0.001)).toBe("0.00092492");
  });

  it("is empty when nothing sensible would leave", () => {
    expect(venueMoveArrivedDefault(0.002, NaN)).toBe("");
    expect(venueMoveArrivedDefault(0.002, 0.003)).toBe("");
  });
});

describe("venueEmptySince", () => {
  const now = Date.parse("2026-11-17T12:00:00Z");

  it("names the day an exchange was emptied", () => {
    expect(venueEmptySince(0, "2026-11-17T12:00:00Z", now)).toBe("empty since 17 Nov");
  });

  it("adds the year for an earlier year", () => {
    expect(venueEmptySince(0, "2025-03-02T12:00:00Z", now)).toBe("empty since 2 Mar 2025");
  });

  it("says empty without a date for cached rows saved before the time was sent", () => {
    expect(venueEmptySince(0, undefined, now)).toBe("empty");
    expect(venueEmptySince(0, "not a date", now)).toBe("empty");
  });

  it("says nothing for an exchange that still holds bitcoin", () => {
    expect(venueEmptySince(0.001, "2026-11-17T12:00:00Z", now)).toBe("");
  });
});

describe("coldVenueHintText", () => {
  it("lists only exchanges that still hold bitcoin and points to the move", () => {
    const text = coldVenueHintText([
      { venue: "Bitvavo", btc: 0.0049665 },
      { venue: "Kraken Pro", btc: 0 },
    ]);
    expect(text).toContain("Bitvavo ₿0.00496650");
    expect(text).not.toContain("Kraken Pro");
    expect(text).toContain("Move to cold storage");
  });

  it("is empty when no exchange holds bitcoin", () => {
    expect(coldVenueHintText([{ venue: "Kraken Pro", btc: 0 }])).toBe("");
    expect(coldVenueHintText([])).toBe("");
  });
});

describe("coldSyncDue", () => {
  const day = 24 * 60 * 60 * 1000;

  it("waits a day between background syncs", () => {
    expect(coldSyncDue(1000, 1000 + day - 1, day, false)).toBe(false);
    expect(coldSyncDue(1000, 1000 + day, day, false)).toBe(true);
  });

  it("checks right away after a move", () => {
    expect(coldSyncDue(1000, 1001, day, true)).toBe(true);
  });
});

describe("venueMoveToast", () => {
  it("names how much left which exchange", () => {
    expect(venueMoveToast("Kraken Pro", 0.00192492, 0)).toBe("Moved ₿0.00192492 from Kraken Pro to cold storage");
    expect(venueMoveToast("Bitvavo", 0.0049665, 0.001)).toBe("Moved ₿0.00396650 from Bitvavo to cold storage");
  });
});
