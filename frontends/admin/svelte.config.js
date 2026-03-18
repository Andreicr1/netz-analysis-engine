import adapter from "@sveltejs/adapter-node";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({ out: "build" }),
		alias: {
			$lib: "src/lib",
		},
		csp: {
			directives: {
				"default-src": ["self"],
				"script-src": ["self"],
				"style-src": ["self", "unsafe-inline"],
				"img-src": ["self", "data:", "blob:", "https:"],
				"connect-src": ["self", "https://*.clerk.com", "wss:"],
				"font-src": ["self", "data:"],
				"frame-ancestors": ["none"],
				"base-uri": ["self"],
				"form-action": ["self"],
			},
		},
	},
};

export default config;
