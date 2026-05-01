/**
 * vitest config — ii-terminal-core
 *
 * Mirrors `packages/investintell-ui/vitest.config.ts`. Lets the
 * package run its co-located component tests in a happy-dom
 * environment with the SvelteKit Vite plugin so .svelte files
 * compile inside vitest.
 *
 * The `browser` resolve condition under VITEST is the SvelteKit
 * recommended workaround for the "Cannot find package $app" error
 * when component code touches $app/state or similar virtual modules.
 */
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
	plugins: [sveltekit()],
	resolve: {
		conditions: process.env.VITEST ? ["browser"] : undefined,
	},
	test: {
		environment: "happy-dom",
		include: ["src/lib/**/*.{test,spec}.{js,ts}"],
		globals: false,
	},
});
