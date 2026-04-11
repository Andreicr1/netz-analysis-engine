import tseslint from "typescript-eslint";
import svelteParser from "svelte-eslint-parser";
import tsParser from "@typescript-eslint/parser";
import sveltePlugin from "eslint-plugin-svelte";
import { netzFormatterRules, netzTerminalRules } from "../eslint.config.js";

export default [
	tseslint.configs.base,
	// eslint-plugin-svelte flat/recommended: registers the plugin, wires
	// svelte-eslint-parser for .svelte / .svelte.ts files, and enables 37
	// Svelte-aware rules (a11y, reactive-statement sanity, template hygiene).
	// Per project mandate (2026-04-11), we take the full recommended
	// ruleset rather than the minimum-viable parser alone.
	...sveltePlugin.configs["flat/recommended"],
	// Wire @typescript-eslint/parser as the inner parser for
	// <script lang="ts"> blocks inside .svelte files. The preset's own
	// entry only sets the outer svelte-eslint-parser; without this
	// override TS type annotations surface as "Parsing error: Type
	// expected" — the original 242-error regression this fix resolves.
	{
		files: ["**/*.svelte", "**/*.svelte.ts", "**/*.svelte.js"],
		languageOptions: {
			parser: svelteParser,
			parserOptions: {
				parser: tsParser,
				extraFileExtensions: [".svelte"],
				svelteFeatures: {
					experimentalGenerics: true,
				},
			},
		},
	},
	...netzFormatterRules,
	...netzTerminalRules,
];
