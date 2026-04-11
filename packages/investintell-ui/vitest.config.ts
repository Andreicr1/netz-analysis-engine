import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
	plugins: [sveltekit()],
	resolve: {
		conditions: process.env.VITEST ? ["browser"] : undefined,
	},
	test: {
		environment: "happy-dom",
		include: [
			"src/lib/**/*.{test,spec}.{js,ts}",
			"tests/**/*.{test,spec}.{js,ts}",
		],
		globals: false,
	},
});
