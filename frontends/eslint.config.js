/**
 * Shared ESLint flat config for all Netz frontends.
 * Enforces formatter discipline: all number/date/currency formatting
 * must go through @netz/ui formatters.
 *
 * Install in each frontend: pnpm add -D eslint
 * Then run: eslint src/
 */

export default [
	{
		files: ["**/*.{js,ts,svelte}"],
		rules: {
			/**
			 * Ban raw number/date formatting APIs that bypass @netz/ui formatters.
			 * Use formatNumber, formatCurrency, formatDate, formatDateTime, etc. from @netz/ui.
			 */
			"no-restricted-syntax": [
				"error",
				{
					selector: "CallExpression[callee.property.name='toFixed']",
					message:
						"Use formatNumber() from @netz/ui instead of .toFixed(). " +
						"@netz/ui formatters use Intl.NumberFormat with caching and EM-dash fallback.",
				},
				{
					selector: "CallExpression[callee.property.name='toLocaleString']",
					message:
						"Use formatNumber(), formatCurrency(), formatDate(), or formatDateTime() from @netz/ui " +
						"instead of .toLocaleString(). @netz/ui formatters use Intl caching and consistent locale defaults.",
				},
				{
					selector: "NewExpression[callee.object.name='Intl'][callee.property.name='NumberFormat']",
					message:
						"Do not instantiate Intl.NumberFormat directly. " +
						"Use formatNumber(), formatCurrency(), formatPercent(), formatAUM(), etc. from @netz/ui.",
				},
				{
					selector: "NewExpression[callee.object.name='Intl'][callee.property.name='DateTimeFormat']",
					message:
						"Do not instantiate Intl.DateTimeFormat directly. " +
						"Use formatDate(), formatDateTime(), formatShortDate(), or formatDateRange() from @netz/ui.",
				},
			],

			/**
			 * Force formatter imports to come from @netz/ui, not from relative paths
			 * or reimplemented in domain packages.
			 */
			"no-restricted-imports": [
				"error",
				{
					patterns: [
						{
							regex: "\\.\\.?/.*format",
							message:
								"Import formatters from '@netz/ui', not from relative paths. " +
								"Centralising formatters in @netz/ui ensures consistent locale and Intl caching.",
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
