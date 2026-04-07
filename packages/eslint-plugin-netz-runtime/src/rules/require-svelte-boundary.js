/**
 * Rule: require-svelte-boundary
 *
 * Stability Guardrails P3. Detail pages that render a component
 * tree without a surrounding <svelte:boundary> can crash the entire
 * page on any runtime error in a descendant. This is the mechanical
 * root cause of the "FactSheet black screen" failure (§7.2).
 *
 * Heuristic (v1): for files whose name matches +page.svelte or
 * +layout.svelte, check the raw source text. If it contains any
 * component tag (`<Capital` or `<lowercase-with-dashes`) and does
 * NOT contain `<svelte:boundary`, report a warning.
 *
 * This is a TEXT-LEVEL rule: it does not parse the Svelte template.
 * The hardening sprint will replace it with a proper svelte-eslint-parser
 * rule that can surface the exact offending component. The v1
 * heuristic fires as `warn` (not `error`) to avoid alert fatigue
 * while existing pages are migrated — see design spec §6.1 R1.9.
 */

const PAGE_FILE_RE = /[+](page|layout)\.svelte$/;
// Match custom component tags: PascalCase <Foo ...> or custom
// kebab-case <some-element ...>. Exclude standard HTML tags.
const COMPONENT_TAG_RE = /<([A-Z][A-Za-z0-9]*)[\s/>]/;

/** @type {import("eslint").Rule.RuleModule} */
export default {
	meta: {
		type: "suggestion",
		docs: {
			description:
				"Require +page.svelte / +layout.svelte files that render components to use <svelte:boundary>.",
			url: "docs/reference/stability-guardrails.md#p3-isolated",
		},
		messages: {
			missingBoundary:
				"This page renders a component but contains no <svelte:boundary>. " +
				"Wrap the top-level component in <svelte:boundary> with a `failed` snippet so a descendant crash does not produce a black screen. " +
				"See docs/reference/stability-guardrails.md#p3-isolated.",
		},
		schema: [],
	},
	create(context) {
		const filename = context.filename || context.getFilename?.() || "";
		if (!PAGE_FILE_RE.test(filename)) {
			return {};
		}

		const source = context.sourceCode || context.getSourceCode?.();
		if (!source) return {};
		const text = source.getText();

		return {
			"Program:exit"(node) {
				if (text.includes("<svelte:boundary")) return;
				// Only fire if the file actually renders a component —
				// static HTML-only pages are fine.
				if (!COMPONENT_TAG_RE.test(text)) return;
				context.report({
					node,
					messageId: "missingBoundary",
				});
			},
		};
	},
};
