import adapter from "@sveltejs/adapter-node";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter(),
		alias: {
			// X2 transitional holdover: $lib still redirects to wealth's
			// src/lib for any remaining wealth-internal $lib/* imports
			// surfaced through copied routes. X5b dropped the $wealth
			// alias after the terminal migrated to
			// @investintell/ii-terminal-core. Remove this once terminal
			// stops piggybacking on wealth's $lib entirely.
			$lib: "../wealth/src/lib",
		},
	},
};

export default config;
