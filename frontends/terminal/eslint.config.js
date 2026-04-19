import tseslint from "typescript-eslint";
import svelteParser from "svelte-eslint-parser";
import tsParser from "@typescript-eslint/parser";
import sveltePlugin from "eslint-plugin-svelte";
import { netzFormatterRules, netzTerminalRules } from "../eslint.config.js";

export default [
	tseslint.configs.base,
	...sveltePlugin.configs["flat/recommended"],
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
	{
		files: ["**/*.svelte"],
		rules: {
			// Svelte 5 rune files — keep formatter discipline in <script lang="ts">.
			"no-restricted-syntax": netzFormatterRules[0].rules["no-restricted-syntax"],
		},
	},
	{
		// Build artifacts and vendored code
		ignores: [".svelte-kit/**", "build/**", "node_modules/**", "dist/**"],
	},
];
