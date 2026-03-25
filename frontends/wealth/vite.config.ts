import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
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
		noExternal: ["@tanstack/svelte-table"],
	},
	build: {
		chunkSizeWarningLimit: 1000,
	},
});
