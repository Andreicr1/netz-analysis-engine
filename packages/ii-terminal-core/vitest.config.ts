import { defineConfig } from "vitest/config";

export default defineConfig({
	test: {
		// Pure-TS tests in this package; no Svelte/DOM yet, so node is
		// enough. Add `happy-dom` if a future test mounts a component.
		environment: "node",
		include: ["src/**/*.test.ts"],
		globals: true,
	},
});
