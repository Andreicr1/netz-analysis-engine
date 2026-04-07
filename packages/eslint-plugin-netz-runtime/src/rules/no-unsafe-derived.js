/**
 * Rule: no-unsafe-derived
 *
 * Stability Guardrails P4. Prevents the "black screen FactSheet"
 * failure class (design spec §7.2) where a `$derived` expression
 * accesses a property on a value that may be null/undefined at
 * mount time, crashing the component.
 *
 * Heuristic (v1): flag any `$derived(arg)` whose body contains a
 * direct member access like `x.y` where `x` is a bare identifier
 * named `data` or matching a nullable convention (`*Data`, `routeData`).
 * The rule does NOT consult the TypeScript type checker — it errs on
 * the side of the author, asking for optional chaining or a guard.
 *
 * Flagged:
 *   const aum = $derived(data.aum_usd);
 *   const name = $derived(routeData.name);
 *
 * Not flagged:
 *   const aum = $derived(data?.aum_usd ?? 0);
 *   const name = $derived(routeData?.name ?? "");
 *   const doubled = $derived(count * 2);
 */

const NULLABLE_IDENTIFIER_RE = /^(data|routeData|fund|factSheet|payload|entity|item)$/;

/** @type {import("eslint").Rule.RuleModule} */
export default {
	meta: {
		type: "problem",
		docs: {
			description:
				"Require optional chaining when a $derived expression accesses properties on a commonly-nullable identifier.",
			url: "docs/reference/stability-guardrails.md#p4-lifecycle",
		},
		messages: {
			unsafeDerived:
				"$derived() reads '{{identifier}}.{{property}}' without optional chaining. " +
				"The identifier may be null at mount time. Use '{{identifier}}?.{{property}} ?? defaultValue' or guard with {#if}. " +
				"See docs/reference/stability-guardrails.md#p4-lifecycle.",
		},
		schema: [],
	},
	create(context) {
		// AST node keys to skip when walking — these hold back-references
		// (`parent`) or scope artefacts ESLint attaches that would cause
		// infinite recursion.
		const SKIP_KEYS = new Set([
			"parent",
			"leadingComments",
			"trailingComments",
			"loc",
			"range",
			"start",
			"end",
			"tokens",
			"comments",
		]);

		function checkBody(identifierNode) {
			const seen = new Set();
			function walk(n) {
				if (!n || typeof n !== "object" || seen.has(n)) return;
				seen.add(n);
				if (n.type === "MemberExpression" && !n.optional) {
					const obj = n.object;
					if (
						obj &&
						obj.type === "Identifier" &&
						NULLABLE_IDENTIFIER_RE.test(obj.name)
					) {
						const prop = n.property;
						const propName =
							prop && prop.type === "Identifier" ? prop.name : "*";
						context.report({
							node: n,
							messageId: "unsafeDerived",
							data: {
								identifier: obj.name,
								property: propName,
							},
						});
					}
				}
				for (const key of Object.keys(n)) {
					if (SKIP_KEYS.has(key)) continue;
					const child = n[key];
					if (Array.isArray(child)) {
						for (const item of child) walk(item);
					} else if (child && typeof child === "object" && child.type) {
						walk(child);
					}
				}
			}
			walk(identifierNode);
		}

		return {
			CallExpression(node) {
				if (
					!node.callee ||
					node.callee.type !== "Identifier" ||
					node.callee.name !== "$derived"
				) {
					return;
				}
				if (node.arguments.length === 0) return;
				checkBody(node.arguments[0]);
			},
		};
	},
};
