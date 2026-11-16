// Decimal fields take a comma as well as a point. An iPhone set to a German
// region has only a comma on its decimal keypad, and WebKit's type="number"
// inputs drop that comma unless the phone's language is German: "0,5" arrived
// as 5 (2026-11-16, adding the IB1T holding).

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

function loadDecimalInput() {
    const source = readFileSync(
        join(process.cwd(), "dca_service", "src", "dca_service", "static", "decimal_input.js"),
        "utf8",
    );
    const module = { exports: {} };
    new Function("module", source)(module);
    return module.exports;
}

const { parse, problem } = loadDecimalInput();

describe("parse", () => {
    it.each([
        ["0,5", 0.5],
        ["0.5", 0.5],
        ["500,123456", 500.123456],
        [" 7,1234 ", 7.1234],
        [",5", 0.5],
        ["5,", 5],
        ["12", 12],
        // What JavaScript writes into a field for a tiny balance
        ["1e-8", 1e-8],
        ["-0,5", -0.5],
    ])("reads %j as %d", (text, value) => {
        expect(parse(text)).toBe(value);
    });

    // Grouping is not guessed at: 1.234,56 or 1,234.56 is refused, never misread
    it.each(["", "   ", ",", ".", "-", "abc", "1.234,56", "1,234.56", "5,,5", "1 234", "0,5 BTC"])(
        "does not read %j",
        (text) => {
            expect(parse(text)).toBeNaN();
        },
    );

    it("reads nothing from a missing field", () => {
        expect(parse(undefined)).toBeNaN();
        expect(parse(null)).toBeNaN();
    });
});

describe("problem", () => {
    it("leaves an empty field to the required attribute", () => {
        expect(problem("", "0", "10")).toBe("");
        expect(problem("  ", "0", "10")).toBe("");
    });

    it("accepts a value within min and max, with either mark", () => {
        expect(problem("2,5", "0", "10")).toBe("");
        expect(problem("0.75", "0", "10")).toBe("");
        expect(problem("10", "0", "10")).toBe("");
        expect(problem("0,12345678", "0", null)).toBe("");
        expect(problem("3", null, null)).toBe("");
    });

    it("says what is wrong, as a number input did", () => {
        expect(problem("abc", "0", null)).toMatch(/number/);
        expect(problem("1.234,5", "0", null)).toMatch(/number/);
        expect(problem("-1", "0", null)).toMatch(/0 or more/);
        expect(problem("11", "0", "10")).toMatch(/10 or less/);
        expect(problem("0,4", "0.5", "10")).toMatch(/0\.5 or more/);
        expect(problem("0,5", "1", null)).toMatch(/1 or more/);
    });
});
