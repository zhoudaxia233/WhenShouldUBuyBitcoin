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
const venueMoveEffect = load("venueMoveEffect");
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

describe("venueMoveEffect", () => {
  it("says the exchange drops and cold storage is left to the key", () => {
    const effect = venueMoveEffect("Kraken Pro", 0.00192492, 0, NaN, "key", 0.5);
    expect(effect.venue).toBe("Kraken Pro ₿0.00192492 → ₿0.00000000");
    expect(effect.cold).toMatch(/^Cold storage is not changed here/);
    expect(effect.cold).toMatch(/what your wallet received/);
  });

  it("says nothing is added until the received amount is typed", () => {
    const effect = venueMoveEffect("Bitvavo", 0.0049665, 0.001, NaN, "manual", 0.01);
    expect(effect.venue).toBe("Bitvavo ₿0.00496650 → ₿0.00100000");
    expect(effect.cold).toBe("Cold storage gets only what you enter as received, not the ₿0.00396650 that left Bitvavo.");
  });

  it("shows the typed amount and the fee it implies", () => {
    const effect = venueMoveEffect("Bitvavo", 0.0049665, 0, 0.0049, "manual", 0.01);
    expect(effect.cold).toBe("Cold storage ₿0.01000000 → ₿0.01490000 · withdrawal fee ₿0.00006650");
  });

  it("has no exchange line while Left is unreadable", () => {
    expect(venueMoveEffect("Bitvavo", 0.002, NaN, NaN, "key", 0).venue).toBe("");
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
  it("does not claim cold storage changed when the key decides it", () => {
    expect(venueMoveToast("Kraken Pro", 0.00192492, 0, null, "key")).toBe(
      "Kraken Pro is now ₿0.00000000. Reading cold storage from your key…");
  });

  it("names what was added by hand and the fee", () => {
    expect(venueMoveToast("Bitvavo", 0.0049665, 0.001, 0.0039, "manual")).toBe(
      "Bitvavo is now ₿0.00100000. Cold storage +₿0.00390000 (withdrawal fee ₿0.00006650)");
  });
});
