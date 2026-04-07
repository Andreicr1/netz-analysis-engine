/**
 * Shared ESLint flat config for all Netz frontends.
 *
 * Two rule groups live here:
 *
 *  1. Formatter discipline — every number/date/currency value must
 *     go through @investintell/ui formatters.
 *  2. Stability Guardrails (§5.2 of the design spec,
 *     docs/reference/stability-guardrails.md) — three AST-level
 *     rules inlined here that enforce P2 (Batched), P4 (Lifecycle),
 *     and the Route Data Contract of §3.2. The Svelte-parser rules
 *     (no-unsafe-derived, require-load-timeout,
 *     require-tick-buffer-dispose, require-svelte-boundary) live in
 *     the separate @investintell/eslint-plugin-netz-runtime package.
 *
 * Install in each frontend: pnpm add -D eslint typescript-eslint
 * Then run: eslint src/
 */

/** @type {import("eslint").Linter.Config[]} */
export const netzFormatterRules = [
	{
		files: ["**/*.{js,ts}"],
		rules: {
			/**
			 * Ban raw number/date formatting APIs that bypass @investintell/ui formatters.
			 * Use formatNumber, formatCurrency, formatDate, formatDateTime, etc. from @investintell/ui.
			 */
			"no-restricted-syntax": [
				"error",
				{
					selector: "CallExpression[callee.property.name='toFixed']",
					message:
						"Use formatNumber() from @investintell/ui instead of .toFixed(). " +
						"@investintell/ui formatters use Intl.NumberFormat with caching and EM-dash fallback.",
				},
				{
					selector: "CallExpression[callee.property.name='toLocaleString']",
					message:
						"Use formatNumber(), formatCurrency(), formatDate(), or formatDateTime() from @investintell/ui " +
						"instead of .toLocaleString(). @investintell/ui formatters use Intl caching and consistent locale defaults.",
				},
				{
					selector: "NewExpression[callee.object.name='Intl'][callee.property.name='NumberFormat']",
					message:
						"Do not instantiate Intl.NumberFormat directly. " +
						"Use formatNumber(), formatCurrency(), formatPercent(), formatAUM(), etc. from @investintell/ui.",
				},
				{
					selector: "NewExpression[callee.object.name='Intl'][callee.property.name='DateTimeFormat']",
					message:
						"Do not instantiate Intl.DateTimeFormat directly. " +
						"Use formatDate(), formatDateTime(), formatShortDate(), or formatDateRange() from @investintell/ui.",
				},
				/**
				 * Stability Guardrails P2 (Batched) — no spread on reactive
				 * maps inside WebSocket handlers. Pattern like
				 *   priceMap = { ...priceMap, [t.ticker]: t };
				 * causes O(N) re-renders per tick and self-DDoS. Use
				 * createTickBuffer from @investintell/ui/runtime instead.
				 *
				 * Selector: catches any assignment where the right-hand
				 * side is an ObjectExpression containing a SpreadElement
				 * whose argument is a bare identifier matching common
				 * reactive-map names (priceMap, holdings, *Map).
				 */
				{
					selector:
						"AssignmentExpression[operator='='][right.type='ObjectExpression'] > ObjectExpression > SpreadElement[argument.type='Identifier'][argument.name=/^(priceMap|holdings|tickMap|snapshotMap|.*Map)$/]",
					message:
						"Spread on reactive map (`{ ...priceMap, ... }`) in a reactive assignment causes O(N) re-render per tick. " +
						"Use createTickBuffer from @investintell/ui/runtime to coalesce writes. " +
						"See docs/reference/stability-guardrails.md#p2-batched.",
				},
				/**
				 * Stability Guardrails P4 (Lifecycle) — store subscriptions
				 * may not live at module top-level. They must be inside
				 * onMount with a cleanup in onDestroy (or returned from
				 * onMount). Pattern detected: top-level
				 *   something.subscribe([...])
				 *
				 * Selector matches an ExpressionStatement whose parent is
				 * Program (i.e. top-level) calling `.subscribe(arrayLit)`.
				 */
				{
					selector:
						"Program > ExpressionStatement > CallExpression[callee.type='MemberExpression'][callee.property.name='subscribe'][arguments.0.type='ArrayExpression']",
					message:
						"Store .subscribe() must live inside onMount with cleanup in onDestroy, not at module top-level. " +
						"Use createMountedGuard from @investintell/ui/runtime for callback safety. " +
						"See docs/reference/stability-guardrails.md#p4-lifecycle.",
				},
			],

			/**
			 * Force formatter imports to come from @investintell/ui, not from relative paths
			 * or reimplemented in domain packages.
			 */
			"no-restricted-imports": [
				"error",
				{
					patterns: [
						{
							regex: "\\.\\.?/.*format",
							message:
								"Import formatters from '@investintell/ui', not from relative paths. " +
								"Centralising formatters in @investintell/ui ensures consistent locale and Intl caching.",
						},
					],
				},
			],
		},
	},
	{
		/**
		 * Stability Guardrails P3/P6 — Route Data Contract.
		 * SvelteKit load functions live in +page.{ts,server.ts} and
		 * +layout.{ts,server.ts} and MUST return `RouteData<T>` shapes
		 * instead of calling `throw error()`. A black-screen on a
		 * detail page is institutionally unacceptable (§7.2).
		 *
		 * This inline rule catches `error(...)` calls in load files.
		 * It is applied as a separate config entry because it only
		 * targets specific filenames.
		 */
		files: [
			"**/+page.ts",
			"**/+page.server.ts",
			"**/+layout.ts",
			"**/+layout.server.ts",
		],
		rules: {
			"no-restricted-syntax": [
				"error",
				{
					selector: "CallExpression[callee.name='error'][arguments.length>=1]",
					message:
						"Server load functions must return RouteData<T> with { data, error } shape, not call `error()`. " +
						"Import `errData`/`okData` from @investintell/ui/runtime. " +
						"See docs/reference/stability-guardrails.md#p3-isolated.",
				},
			],
		},
	},
	{
		// Exclude generated files and build output
		ignores: ["**/node_modules/**", "**/.svelte-kit/**", "**/dist/**", "**/build/**"],
	},
];

export default netzFormatterRules;
