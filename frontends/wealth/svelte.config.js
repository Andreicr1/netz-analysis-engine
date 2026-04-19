import adapter from "@sveltejs/adapter-node";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter(),
		alias: {
			$lib: "src/lib",
			// Reciprocal alias introduced in X2 (ii-terminal extraction).
			// Shared components under src/lib/{components,stores,state,api,types}
			// use $wealth/* instead of $lib/* so the SAME source tree resolves
			// when the terminal app imports these files via its own $wealth
			// alias (pointing back here). Without this reciprocal, wealth's
			// own build cannot resolve its own shared-components imports.
			// X5 promotes the shared tree to @investintell/ii-terminal-core
			// and removes this alias.
			$wealth: "src/lib",
		},
	},
};

export default config;
