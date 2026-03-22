import adapter from "@sveltejs/adapter-cloudflare";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

const dev = process.env.NODE_ENV !== "production";

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({
			routes: { include: ["/*"], exclude: ["<all>"] },
		}),
		alias: {
			$lib: "src/lib",
		},
		// CSP disabled in dev — Vite injects inline scripts without nonces
		...(!dev && {
			csp: {
				mode: "auto",
				directives: {
					"default-src": ["self"],
					"script-src": ["self"],
					"style-src": ["self", "unsafe-inline"],
					"img-src": ["self", "data:", "blob:", "https:"],
					"connect-src": ["self", "https://*.clerk.com", "wss:", "http://localhost:8000"],
					"font-src": ["self", "data:"],
					"frame-ancestors": ["none"],
					"base-uri": ["self"],
					"form-action": ["self"],
				},
			},
		}),
	},
};

export default config;
