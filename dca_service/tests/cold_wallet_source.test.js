import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// The cold storage dialog's decisions live in the dashboard template; load them from there.
const here = path.dirname(fileURLToPath(import.meta.url));
const html = readFileSync(path.join(here, "../src/dca_service/templates/index.html"), "utf8");

function load(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found`);
  const end = html.indexOf("\n        }\n", start) + "\n        }\n".length;
  return new Function(`${html.slice(start, end)}; return ${name};`)();
}

const coldModalView = load("coldModalView");
const shouldAutoSyncCold = load("shouldAutoSyncCold");
const coldSyncedAt = load("coldSyncedAt");

describe("coldModalView", () => {
  it("shows the tracking status in the browser that holds the key", () => {
    expect(coldModalView(true, "public_key", null)).toBe("tracking");
    expect(coldModalView(true, null, null)).toBe("tracking");
  });

  it("says the key is paused when the balance was since entered by hand elsewhere", () => {
    expect(coldModalView(true, "manual", null)).toBe("paused");
  });

  it("explains a synced balance on a device without the key", () => {
    expect(coldModalView(false, "public_key", null)).toBe("remote");
    expect(coldModalView(false, "public_key", "add")).toBe("remote-add");
    expect(coldModalView(false, "public_key", "manual")).toBe("remote-manual");
  });

  it("offers the manual form and the key setup otherwise", () => {
    expect(coldModalView(false, "manual", null)).toBe("setup");
    expect(coldModalView(false, null, null)).toBe("setup");
    expect(coldModalView(false, "manual", "add")).toBe("setup");
  });
});

describe("shouldAutoSyncCold", () => {
  it("stops the daily sync once the balance is entered by hand", () => {
    expect(shouldAutoSyncCold("manual")).toBe(false);
  });

  it("keeps syncing synced balances and balances saved before the source was recorded", () => {
    expect(shouldAutoSyncCold("public_key")).toBe(true);
    expect(shouldAutoSyncCold(null)).toBe(true);
    expect(shouldAutoSyncCold(undefined)).toBe(true);
  });
});

describe("coldSyncedAt", () => {
  const server = "2026-10-14T08:30:00+00:00";

  it("uses the server's time for a synced balance, on every device", () => {
    expect(coldSyncedAt("public_key", server, null)).toBe(Date.parse(server));
    expect(coldSyncedAt("public_key", server, { at: 1 })).toBe(Date.parse(server));
  });

  it("shows no sync age for a balance entered by hand", () => {
    expect(coldSyncedAt("manual", server, { at: 1 })).toBeNull();
  });

  it("falls back to this browser's own sync when the source is unknown", () => {
    expect(coldSyncedAt(null, server, { at: 1234 })).toBe(1234);
    expect(coldSyncedAt(null, server, null)).toBeNull();
  });
});
