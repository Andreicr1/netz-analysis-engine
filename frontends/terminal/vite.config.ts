import path from "node:path";
import { fileURLToPath } from "node:url";
import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Build metadata exposed to the client bundle via import.meta.env.
// Railway injects GIT_SHA in production deploys; local dev falls back
// to "local-dev". Mirrors the convention used by frontends/wealth.
const BUILD_SHA = process.env.GIT_SHA ?? "local-dev";
const BUILD_ENV = process.env.NODE_ENV === "production" ? "prod" : "dev";

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	define: {
		"import.meta.env.VITE_BUILD_SHA": JSON.stringify(BUILD_SHA),
		"import.meta.env.VITE_ENV": JSON.stringify(BUILD_ENV),
	},
	resolve: {
		// X2 transitional holdover: $lib still redirects to wealth's
		// src/lib because copied wealth components may resolve internal
		// $lib/* imports through this terminal config. $wealth alias
		// was removed in X5b after migration to
		// @investintell/ii-terminal-core. Array form required because
		// the object form merges with SvelteKit's alias injection and
		// plugin defaults win; array aliases run first in declared order.
		alias: [
			{
				find: /^\$lib\/(.*)$/,
				replacement: path.resolve(__dirname, "../wealth/src/lib/$1"),
			},
			{
				find: /^\$lib$/,
				replacement: path.resolve(__dirname, "../wealth/src/lib"),
			},
		],
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
