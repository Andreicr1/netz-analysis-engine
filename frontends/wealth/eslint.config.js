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
	/**
	 * Phase 1 Final Polish (2026-04-11) — widen netzFormatterRules to
	 * .svelte files across the entire wealth frontend.
	 *
	 * The shared netzFormatterRules block is scoped to `**​/*.{js,ts}`,
	 * which means .svelte <script lang="ts"> blocks were slipping past
	 * the formatter-discipline rules. The full-tree audit surfaced 48
	 * violations (.toFixed / .toLocaleString / new Intl.*) across 25
	 * non-Appendix-F files — all migrated in Tasks 1-7 of this session.
	 * This block re-applies the same rule set to .svelte files so future
	 * regressions anywhere in frontends/wealth/src/** get caught by CI
	 * before merge.
	 *
	 * `AdvancedMarketChart.svelte` is explicitly allowlisted. The file
	 * is slated for deletion per master plan Appendix A (contains its
	 * own svelte-echarts wiring that predates the TerminalChart
	 * primitives; migrating its single .toLocaleString site would be
	 * wasted work). Remove the ignore entry when the file is deleted.
	 *
	 * stores/stale.ts is NOT ignored — it already has a documented
	 * `// eslint-disable-next-line no-restricted-syntax` above its
	 * `new Intl.DateTimeFormat(...)` usage (São Paulo timezone parser
	 * for business-day staleness, which @investintell/ui formatters
	 * do not expose).
	 */
	{
		files: ["src/**/*.svelte"],
		ignores: ["src/lib/components/charts/AdvancedMarketChart.svelte"],
		rules: netzFormatterRules[0]?.rules ?? {},
	},
];
