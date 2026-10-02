// @vitest-environment happy-dom
// Without its stylesheet (a browser holding an old cached app.css) the canvas
// takes its CSS size from its own bitmap. Each redraw then grew the bitmap by
// devicePixelRatio until the canvas was too large to paint: a blank white block.

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

function loadReserveChart() {
    const source = readFileSync(
        join(process.cwd(), "dca_service", "src", "dca_service", "static", "reserve_chart.js"),
        "utf8",
    );
    const module = { exports: {} };
    new Function("module", source)(module);
    return module.exports;
}

function panel() {
    const root = document.createElement("section");
    root.innerHTML = '<div data-reserve-readout></div><canvas></canvas>';
    document.body.appendChild(root);
    return root;
}

describe("mount without the chart stylesheet", () => {
    it("pins the canvas to a fixed size so redraws cannot grow it", () => {
        document.head.innerHTML = "";
        const root = panel();
        loadReserveChart().mount(root);
        const canvas = root.querySelector("canvas");
        expect(canvas.style.width).toBe("100%");
        expect(canvas.style.height).toBe("320px");
    });

    it("leaves sizing to the stylesheet when it is loaded", () => {
        document.head.innerHTML = "<style>:root { --reserve-price: #e8891c; }</style>";
        const root = panel();
        loadReserveChart().mount(root);
        const canvas = root.querySelector("canvas");
        expect(canvas.style.height).toBe("");
    });
});
