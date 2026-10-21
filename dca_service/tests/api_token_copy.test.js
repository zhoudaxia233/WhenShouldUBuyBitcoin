import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// copyTokenText lives in the API token template; load it from there.
// The browser can refuse navigator.clipboard (unfocused document, denied
// permission, plain-HTTP origin); the copy must still work, not just select.
const here = path.dirname(fileURLToPath(import.meta.url));
const html = readFileSync(path.join(here, "../src/dca_service/templates/api_token.html"), "utf8");
const start = html.indexOf("async function copyTokenText");
const end = html.indexOf("\n        }\n", start) + "\n        }\n".length;
const copyTokenText = new Function(`${html.slice(start, end)}; return copyTokenText;`)();

function fakeInput(value) {
    const calls = [];
    return { value, calls, focus: () => calls.push("focus"), select: () => calls.push("select") };
}

function fakeDocument(copyWorks) {
    const commands = [];
    return { commands, execCommand: (name) => { commands.push(name); return copyWorks; } };
}

const refusingClipboard = { writeText: () => Promise.reject(new Error("Document is not focused.")) };

describe("copyTokenText", () => {
    it("uses the Clipboard API when it works", async () => {
        const written = [];
        const clipboard = { writeText: async (text) => { written.push(text); } };
        const doc = fakeDocument(true);
        expect(await copyTokenText(fakeInput("wsub_abc"), clipboard, doc)).toBe(true);
        expect(written).toEqual(["wsub_abc"]);
        expect(doc.commands).toEqual([]);
    });

    it("copies the selected input when the Clipboard API refuses", async () => {
        const input = fakeInput("wsub_abc");
        const doc = fakeDocument(true);
        expect(await copyTokenText(input, refusingClipboard, doc)).toBe(true);
        expect(input.calls).toEqual(["focus", "select"]);
        expect(doc.commands).toEqual(["copy"]);
    });

    it("copies the selected input when there is no Clipboard API", async () => {
        const doc = fakeDocument(true);
        expect(await copyTokenText(fakeInput("wsub_abc"), undefined, doc)).toBe(true);
        expect(doc.commands).toEqual(["copy"]);
    });

    it("reports failure, with the token selected, when both ways fail", async () => {
        const input = fakeInput("wsub_abc");
        expect(await copyTokenText(input, refusingClipboard, fakeDocument(false))).toBe(false);
        expect(input.calls).toEqual(["focus", "select"]);
    });
});
