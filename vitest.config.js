import { defineConfig } from "vitest/config";

export default defineConfig({
    test: {
        environment: "node", // Use Node environment for backtest tests
        globals: true,
        coverage: {
            provider: "v8",
            reporter: ["text", "json", "html"],
            exclude: [
                "node_modules/**",
                "docs/charts/**",
                "docs/test_*.html",
                "*.config.js",
            ],
        },
    },
});

