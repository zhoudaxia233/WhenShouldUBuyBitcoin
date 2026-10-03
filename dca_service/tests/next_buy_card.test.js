// @vitest-environment happy-dom
// The home page's "Next buy" card: tier ladder, goal ring and budget bar.

import { beforeEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const root = join(process.cwd(), "dca_service", "src", "dca_service");
const html = readFileSync(join(root, "templates", "index.html"), "utf8");
const ladderSource = readFileSync(join(root, "static", "strategy_ladder.js"), "utf8");

function loadHelpers() {
    const start = html.indexOf("function escapeLadderText(value)");
    const end = html.indexOf("window.renderStrategyLadder = renderStrategyLadder;", start);
    const module = { exports: {} };
    new Function("module", ladderSource)(module);
    window.StrategyLadder = module.exports;
    return new Function(
        "window",
        "document",
        `${html.slice(start, end)}; return { renderStrategyLadder, setGoalRing, renderBudgetSpent };`,
    )(window, document);
}

describe("next buy card", () => {
    beforeEach(() => {
        document.body.innerHTML = `
            <span id="previewBand"></span><span id="marketTier"></span><span id="marketAhr"></span>
            <ol id="strategyLadder" hidden></ol><div id="strategyLadderScale" hidden></div>
            <svg><circle id="goalRingFill"></circle></svg>
            <small id="budgetCaption"></small>
            <div class="progress"><div id="budgetSpentBar"></div></div>
        `;
    });

    it("marks the current tier and states the multiplier being bought", () => {
        const { renderStrategyLadder } = loadHelpers();
        renderStrategyLadder({ ahr_band: "p50", ahr999_value: 0.874, multiplier: 1 }, { ahr999_multiplier_p10: 2 });

        const items = [...document.querySelectorAll("#strategyLadder li")];
        expect(items.map((li) => li.textContent)).toEqual(["2×", "2×", "1×", "0×", "0×", "0×"]);
        expect(items[2].classList.contains("is-current")).toBe(true);
        expect(items[2].getAttribute("aria-current")).toBe("true");
        expect(document.getElementById("strategyLadder").hidden).toBe(false);
        expect(document.getElementById("previewBand").textContent).toBe("Cheap · buying 1×");
        expect(document.getElementById("marketTier").textContent).toBe("Cheap");
        expect(document.getElementById("marketAhr").textContent).toBe("0.87");
    });

    it("hides the ladder for strategies without tiers", () => {
        const { renderStrategyLadder } = loadHelpers();
        renderStrategyLadder({ ahr_band: "fixed", ahr999_value: 0.9, multiplier: 1 }, { strategy_type: "fixed_dca" });

        expect(document.getElementById("strategyLadder").hidden).toBe(true);
        expect(document.getElementById("previewBand").textContent).toBe("FIXED · buying 1×");
    });

    it("fills the goal ring in proportion to progress", () => {
        const { setGoalRing } = loadHelpers();
        setGoalRing("25");
        const [filled, total] = document.getElementById("goalRingFill").getAttribute("stroke-dasharray").split(" ").map(Number);
        expect(filled / total).toBeCloseTo(0.25, 3);
    });

    it("shows how much of a monthly budget is spent, and hides the bar when budgets roll over", () => {
        const { renderBudgetSpent } = loadHelpers();
        renderBudgetSpent({ remaining_budget: 412.4, budget_resets: true }, { total_budget_usd: 1000 });
        expect(document.getElementById("budgetSpentBar").style.width).toBe("59%");
        expect(document.getElementById("budgetCaption").textContent).toBe("left of $1,000 this month");

        renderBudgetSpent({ remaining_budget: 1800, budget_resets: false }, { total_budget_usd: 1000 });
        expect(document.querySelector(".progress").hidden).toBe(true);
        expect(document.getElementById("budgetCaption").textContent).toBe("available");
    });
});
