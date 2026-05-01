import { defineConfig } from "vitest/config";

/**
 * Pure-JS/TS unit test runner for ii-terminal-core helpers.
 *
 * Svelte component tests under ``src/lib/components/**`` require the
 * Svelte vite plugin and a browser-like environment (jsdom + Svelte 5
 * runes harness). Until that toolchain lands, exclude them so the
 * helper tests (utils/, formatters/) can run on their own.
 */
export default defineConfig({
	test: {
		include: ["src/lib/**/*.test.ts"],
		exclude: [
			"node_modules/**",
			"dist/**",
			".svelte-kit/**",
			"src/lib/components/**",
		],
	},
});
