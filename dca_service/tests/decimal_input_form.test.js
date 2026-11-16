// @vitest-environment happy-dom
// reportProblem checks a form's decimal fields the way the browser checked
// number inputs, including a field that belongs to the form without sitting
// inside its tags (the strategy page has a stray </div> before its Save button).

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const source = readFileSync(
    join(process.cwd(), "dca_service", "src", "dca_service", "static", "decimal_input.js"),
    "utf8",
);
const module = { exports: {} };
new Function("module", source)(module);
const { reportProblem } = module.exports;

function form(html) {
    document.body.innerHTML = html;
    return document.getElementById("f");
}

describe("reportProblem", () => {
    it("passes a form whose fields are within min and max, read with either mark", () => {
        const f = form(`<form id="f">
            <input id="a" type="text" inputmode="decimal" min="0" max="10" value="2,5">
            <input id="b" type="text" inputmode="decimal" min="1" value="150.5">
        </form>`);
        expect(reportProblem(f)).toBe(false);
    });

    it("stops at the first field out of range and says why at the field", () => {
        const f = form(`<form id="f">
            <input id="a" type="text" inputmode="decimal" min="0" max="10" value="11">
            <input id="b" type="text" inputmode="decimal" min="0" value="-1">
        </form>`);
        expect(reportProblem(f)).toBe(true);
        expect(document.getElementById("a").validationMessage).toBe("Enter 10 or less.");
        expect(document.getElementById("b").validationMessage).toBe("");
    });

    it("checks a field that belongs to the form from outside its tags", () => {
        // Browsers list such a field in form.elements (checked in WebKit on
        // 2026-11-16); happy-dom does not, so the form here lists it itself.
        form(`<input id="a" type="text" inputmode="decimal" min="0" value="abc">`);
        const outside = document.getElementById("a");
        const strategyForm = { elements: [outside], querySelectorAll: () => [] };
        expect(reportProblem(strategyForm)).toBe(true);
        expect(outside.validationMessage).toMatch(/number/);
    });

    it("leaves disabled and read-only fields alone, as the browser does", () => {
        const f = form(`<form id="f">
            <input type="text" inputmode="decimal" min="1" value="0,5" disabled>
            <input type="text" inputmode="decimal" min="1" value="0,5" readonly>
        </form>`);
        expect(reportProblem(f)).toBe(false);
    });

    it("lets the field be submitted again once it is edited", () => {
        const f = form(`<form id="f">
            <input id="a" type="text" inputmode="decimal" max="10" value="11">
        </form>`);
        reportProblem(f);
        const field = document.getElementById("a");
        field.value = "9";
        field.dispatchEvent(new Event("input"));
        expect(field.validationMessage).toBe("");
        expect(reportProblem(f)).toBe(false);
    });
});
