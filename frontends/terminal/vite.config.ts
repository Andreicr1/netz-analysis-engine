import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// Build metadata exposed to the client bundle via import.meta.env.
// Railway injects GIT_SHA in production deploys; local dev falls back
// to "local-dev".
const BUILD_SHA = process.env.GIT_SHA ?? "local-dev";
const BUILD_ENV = process.env.NODE_ENV === "production" ? "prod" : "dev";

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	define: {
		"import.meta.env.VITE_BUILD_SHA": JSON.stringify(BUILD_SHA),
		"import.meta.env.VITE_ENV": JSON.stringify(BUILD_ENV),
	},
	optimizeDeps: {
		include: [
			"echarts",
			"echarts/core",
			"echarts/charts",
			"echarts/components",
			"echarts/renderers",
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
	server: {
		port: 5175,
		strictPort: false,
	},
	build: {
		chunkSizeWarningLimit: 1000,
	},
});
