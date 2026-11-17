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
const venueMoveAmountProblem = load("venueMoveAmountProblem");
const venueMoveLeft = load("venueMoveLeft");
const venueMoveNote = load("venueMoveNote");
const venueMoveReceivedText = load("venueMoveReceivedText");
const venueEmptySince = load("venueEmptySince");
const coldVenueHintText = load("coldVenueHintText");
const coldSyncDue = load("coldSyncDue");
const venueMoveToast = load("venueMoveToast");

describe("venueMoveColdMode", () => {
  it("leaves cold storage to the key while a key is saved and not overridden by hand", () => {
    expect(venueMoveColdMode(true, "public_key")).toBe("key");
    expect(venueMoveColdMode(true, null)).toBe("key");
  });

  it("leaves cold storage to the owner when it is typed by hand or has no key", () => {
    expect(venueMoveColdMode(true, "manual")).toBe("manual");
    expect(venueMoveColdMode(false, "public_key")).toBe("manual");
    expect(venueMoveColdMode(false, null)).toBe("manual");
  });
});

describe("venueMoveAmountProblem", () => {
  it("accepts everything or a part", () => {
    expect(venueMoveAmountProblem(0.00192492, 0.00192492)).toBe("");
    expect(venueMoveAmountProblem(0.00192492, 0.001)).toBe("");
  });

  it("needs more than nothing and no more than is there", () => {
    expect(venueMoveAmountProblem(0.002, 0)).toMatch(/more than 0/);
    expect(venueMoveAmountProblem(0.002, 0.00200001)).toBe("No more than the ₿0.00200000 on the exchange.");
  });

  it("leaves unreadable text to the decimal field check", () => {
    expect(venueMoveAmountProblem(0.002, NaN)).toBe("");
  });
});

describe("venueMoveLeft", () => {
  it("is what stays on the exchange, to the satoshi", () => {
    expect(venueMoveLeft(0.00192492, 0.00192492)).toBe(0);
    expect(venueMoveLeft(0.0049665, 0.001)).toBe(0.0039665);
  });
});

describe("venueMoveNote", () => {
  it("says cold storage is left to the key", () => {
    expect(venueMoveNote("Kraken Pro", "key")).toBe(
      "Only the Kraken Pro balance goes down. Cold storage is not changed here: it is read from your wallet's key after you save.");
  });

  it("says cold storage is the owner's to set when typed by hand", () => {
    expect(venueMoveNote("Bitvavo", "manual")).toBe(
      "Only the Bitvavo balance goes down. Cold storage is not changed here: set it yourself to what your wallet received.");
  });
});

describe("venueMoveReceivedText", () => {
  it("names what the wallet received and the fee", () => {
    expect(venueMoveReceivedText(0.00192492, 0.5, 0.5019)).toBe(
      "Cold storage received ₿0.00190000 (withdrawal fee ₿0.00002492)");
  });

  it("leaves the fee out when more arrived than this move", () => {
    expect(venueMoveReceivedText(0.001, 0.5, 0.503)).toBe("Cold storage received ₿0.00300000");
  });

  it("says so when nothing has arrived yet", () => {
    expect(venueMoveReceivedText(0.001, 0.5, 0.5)).toMatch(/nothing new yet.*Sync now/);
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
  it("does not claim cold storage changed", () => {
    expect(venueMoveToast("Kraken Pro", 0, "key")).toBe(
      "Kraken Pro is now ₿0.00000000. Reading cold storage from your key…");
    expect(venueMoveToast("Bitvavo", 0.001, "manual")).toBe(
      "Bitvavo is now ₿0.00100000. Cold storage is not changed.");
  });
});
