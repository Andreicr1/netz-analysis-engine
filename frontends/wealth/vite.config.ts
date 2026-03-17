import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		port: 5174,
		strictPort: false,
	},
	ssr: {
		noExternal: ["@tanstack/svelte-table"],
	},
	build: {
		rollupOptions: {
			output: {
				manualChunks: {
					echarts: ["echarts/core", "echarts/charts", "echarts/components", "echarts/renderers"],
					table: ["@tanstack/svelte-table"],
				},
			},
		},
	},
});
