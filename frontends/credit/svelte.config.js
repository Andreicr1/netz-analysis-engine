import adapter from "@sveltejs/adapter-cloudflare";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

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
		// CSP handled via static _headers file (Cloudflare Pages)
		// NOT via SvelteKit csp config — SvelteKit injects nonces that
		// block Clerk inline scripts (nonce presence disables unsafe-inline per CSP3 spec)
	},
};

export default config;
