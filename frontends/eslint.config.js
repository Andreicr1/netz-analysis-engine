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

/**
 * Terminal Unification Master Plan — Phase 1 guardrails.
 * Source: docs/plans/2026-04-11-terminal-unification-master-plan.md §2
 *
 * These rules are imperative for any frontend that hosts the
 * `(terminal)/` route group. Layered on top of netzFormatterRules
 * in `frontends/wealth/eslint.config.js`. They enforce:
 *
 *   1. Direct `echarts` / `svelte-echarts` imports are forbidden
 *      everywhere except inside
 *      `src/lib/components/terminal/charts/**`. Every other caller
 *      must import a pattern wrapper (TerminalLineChart, …).
 *   2. No `localStorage` / `sessionStorage` — terminal state is
 *      in-memory, URL, SSE, polling. Violations explode the
 *      "smart backend, dumb frontend" contract (per
 *      feedback_echarts_no_localstorage.md).
 *   3. No cross-imports between the `(app)/` legacy read-only
 *      route group and the `(terminal)/` operational surface.
 *      Enforced at file-path level — `(app)` files cannot import
 *      from `(terminal)` and vice-versa.
 *   4. Hex color literals are blocked inside `(terminal)/**` and
 *      `lib/components/terminal/**` components. Tokens live in
 *      `packages/investintell-ui/src/lib/tokens/terminal.css` and
 *      are consumed exclusively through `var(--terminal-*)`.
 *
 * Strictly no escape hatches. If you feel the urge to add one,
 * open a separate PR to amend this file and the master plan at
 * the same time.
 */
/** @type {import("eslint").Linter.Config[]} */
export const netzTerminalRules = [
	{
		// Ban direct ECharts imports OUTSIDE the sanctioned chart
		// wrapper directory. Pattern wrappers and TerminalChart.svelte
		// are the only files allowed to reach for echarts.
		files: ["**/*.{js,ts,svelte}"],
		ignores: [
			"**/lib/components/terminal/charts/**",
			// Legacy credit charts (in @netz/ui) are unaffected.
			"**/node_modules/**",
		],
		rules: {
			"no-restricted-imports": [
				"error",
				{
					paths: [
						{
							name: "svelte-echarts",
							message:
								"svelte-echarts is banned outside lib/components/terminal/charts/. " +
								"Compose TerminalChart / TerminalLineChart / … instead. " +
								"See docs/plans/2026-04-11-terminal-unification-master-plan.md §1.2.",
						},
						{
							name: "echarts",
							message:
								"Direct `echarts` import is only permitted in lib/components/terminal/charts/TerminalChart.svelte. " +
								"Every other file must import a pattern wrapper. See master plan §1.2.",
						},
						{
							name: "echarts/core",
							message:
								"Direct `echarts/core` import is only permitted in lib/components/terminal/charts/TerminalChart.svelte. " +
								"See master plan §1.2.",
						},
					],
					patterns: [
						{
							group: ["echarts/*"],
							message:
								"Direct ECharts module imports are only permitted in lib/components/terminal/charts/TerminalChart.svelte. " +
								"See master plan §1.2.",
						},
					],
				},
			],
		},
	},
	{
		// Ban localStorage / sessionStorage inside the terminal namespace.
		// Terminal state is in-memory (+ URL + SSE + polling). Pre-existing
		// `(app)/` legacy calls (e.g. ThemeToggle) get cleaned up in Phase 9.
		// This matches the master plan's Phase 1 exit criteria: "lint suite
		// rejects any NEW hex/toFixed/localStorage commit" under `(terminal)/`.
		files: [
			"**/src/routes/(terminal)/**/*.{js,ts,svelte}",
			"**/src/lib/components/terminal/**/*.{js,ts,svelte}",
			"**/src/lib/runtime/terminal/**/*.{js,ts}",
		],
		rules: {
			"no-restricted-globals": [
				"error",
				{
					name: "localStorage",
					message:
						"localStorage is banned inside (terminal)/ — state lives in-memory, URL, SSE, or polling. " +
						"See feedback_echarts_no_localstorage.md and master plan §2.",
				},
				{
					name: "sessionStorage",
					message:
						"sessionStorage is banned inside (terminal)/ — state lives in-memory, URL, SSE, or polling. " +
						"See feedback_echarts_no_localstorage.md and master plan §2.",
				},
			],
		},
	},
	{
		// (app) files cannot import from (terminal). The legacy read-only
		// surface must not reach into the operational surface or its
		// wrappers — enforced at the file-path level.
		files: ["**/src/routes/(app)/**/*.{js,ts,svelte}"],
		rules: {
			"no-restricted-imports": [
				"error",
				{
					patterns: [
						{
							group: ["**/routes/(terminal)/**", "**/(terminal)/**"],
							message:
								"(app)/ is the legacy read-only surface and cannot import from (terminal)/. " +
								"See master plan §2 rule 9 and §3 Phase 9.",
						},
						{
							group: ["$lib/components/terminal/**", "**/components/terminal/**"],
							message:
								"(app)/ cannot import terminal components. Terminal primitives belong to (terminal)/ only. " +
								"See master plan §2 rule 9.",
						},
					],
				},
			],
		},
	},
	{
		// (terminal) files cannot import from (app). Keeps the new
		// operational surface insulated from legacy code paths.
		files: ["**/src/routes/(terminal)/**/*.{js,ts,svelte}"],
		rules: {
			"no-restricted-imports": [
				"error",
				{
					patterns: [
						{
							group: ["**/routes/(app)/**", "**/(app)/**"],
							message:
								"(terminal)/ cannot import from (app)/. (app) is read-only report surface; " +
								"share via @investintell/ui or the backend API. See master plan §2 rule 9.",
						},
					],
				},
			],
		},
	},
	{
		// Hex color literal block inside terminal surfaces. Matches
		// `#fff`, `#ffffff`, `#ffffff00` in string literals. Tokens
		// live in packages/investintell-ui/src/lib/tokens/terminal.css;
		// consume them via var(--terminal-*).
		//
		// We run this on .svelte, .ts and .js under terminal paths.
		// Stylelint can later add a scoped `color-no-hex` rule for
		// CSS-only files — kept minimal here to avoid double reporting.
		files: [
			"**/src/routes/(terminal)/**/*.{js,ts,svelte}",
			"**/src/lib/components/terminal/**/*.{js,ts,svelte}",
		],
		rules: {
			"no-restricted-syntax": [
				"error",
				{
					selector:
						"Literal[value=/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/]",
					message:
						"Hex color literals are banned in (terminal)/**. Use var(--terminal-*) tokens from " +
						"packages/investintell-ui/src/lib/tokens/terminal.css. See master plan §2 rule 1.",
				},
				{
					selector:
						"TemplateElement[value.raw=/#([0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(\\b|[^0-9a-fA-F])/]",
					message:
						"Hex color literals are banned in (terminal)/**. Use var(--terminal-*) tokens. " +
						"See master plan §2 rule 1.",
				},
			],
		},
	},
	{
		ignores: ["**/node_modules/**", "**/.svelte-kit/**", "**/dist/**", "**/build/**"],
	},
];

export default netzFormatterRules;
