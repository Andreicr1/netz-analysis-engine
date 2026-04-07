/**
 * Shared ESLint flat config for all Netz frontends.
 * Enforces formatter discipline: all number/date/currency formatting
 * must go through @investintell/ui formatters.
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
		// Exclude generated files and build output
		ignores: ["**/node_modules/**", "**/.svelte-kit/**", "**/dist/**", "**/build/**"],
	},
];

export default netzFormatterRules;
