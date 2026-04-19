import adapter from "@sveltejs/adapter-node";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter(),
		alias: {
			// X2 transitional: terminal has no src/lib of its own yet — all
			// components live under wealth/src/lib and are imported via
			// $wealth/* from copied routes. Pointing $lib at wealth's
			// src/lib lets those wealth files resolve their own $lib/*
			// internal imports unchanged. X5 promotes the components to
			// @investintell/ii-terminal-core and drops this redirection.
			$lib: "../wealth/src/lib",
			$wealth: "../wealth/src/lib",
		},
	},
};

export default config;
