import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// Build metadata exposed to the client bundle via import.meta.env.
// Consumed by TerminalStatusBar through TerminalShell. Railway sets
// GIT_SHA in production deploys; local dev falls back to "local-dev".
const BUILD_SHA = process.env.GIT_SHA ?? "local-dev";
const BUILD_ENV = process.env.NODE_ENV === "production" ? "prod" : "dev";

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	define: {
		"import.meta.env.VITE_BUILD_SHA": JSON.stringify(BUILD_SHA),
		"import.meta.env.VITE_ENV": JSON.stringify(BUILD_ENV),
	},
	server: {
		port: 5174,
		strictPort: false,
		warmup: {
			clientFiles: [
				"./src/routes/(app)/+layout.svelte",
				"./src/routes/(app)/allocation/+page.svelte",
				"./src/routes/(app)/screener/+page.svelte",
				"./src/routes/(app)/macro/+page.svelte",
				"./src/routes/(app)/us-fund-analysis/+page.svelte",
			],
		},
	},
	optimizeDeps: {
		include: [
			"echarts",
			"echarts/core",
			"echarts/charts",
			"echarts/components",
			"echarts/renderers",
			"svelte-echarts",
			"lucide-svelte",
			"@tanstack/svelte-table",
		],
	},
	ssr: {
		noExternal: [
			"@tanstack/svelte-table",
			"@codemirror/state",
			"@codemirror/view",
			"@codemirror/lang-json",
			"@codemirror/lint",
			"@codemirror/commands",
			"@codemirror/merge",
			"codemirror-json-schema",
		],
	},
	build: {
		chunkSizeWarningLimit: 1000,
	},
});
