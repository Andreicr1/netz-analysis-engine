/**
 * Rule: require-tick-buffer-dispose
 *
 * Stability Guardrails P4. Every call to `createTickBuffer(...)`
 * allocates a requestAnimationFrame / setInterval loop and a
 * visibilitychange listener. Forgetting to call `.dispose()` leaks
 * them for the lifetime of the tab.
 *
 * Heuristic (v1): for each file, collect variable declarations of
 * the form `const foo = createTickBuffer(...)`. For each, require
 * that `foo.dispose(` appears somewhere in the file source text.
 * This is a coarse but effective check — it does not verify that
 * the call is actually inside an `onDestroy` callback. The hardening
 * sprint will upgrade this to an AST-level onDestroy check.
 */

/** @type {import("eslint").Rule.RuleModule} */
export default {
	meta: {
		type: "problem",
		docs: {
			description:
				"Require that every createTickBuffer result has a matching .dispose() call in the same file.",
			url: "docs/reference/stability-guardrails.md#p4-lifecycle",
		},
		messages: {
			missingDispose:
				"createTickBuffer result '{{name}}' has no matching '.dispose()' call in this file. " +
				"Tick buffers allocate requestAnimationFrame / setInterval loops and visibilitychange listeners; " +
				"call '{{name}}.dispose()' in onDestroy. See docs/reference/stability-guardrails.md#p4-lifecycle.",
		},
		schema: [],
	},
	create(context) {
		const source = context.sourceCode || context.getSourceCode?.();
		if (!source) return {};
		const sourceText = source.getText();
		const tickBufferNames = [];

		return {
			VariableDeclarator(node) {
				const init = node.init;
				if (!init || init.type !== "CallExpression") return;
				const callee = init.callee;
				if (!callee) return;
				const calleeName =
					callee.type === "Identifier"
						? callee.name
						: callee.type === "MemberExpression" &&
							  callee.property &&
							  callee.property.type === "Identifier"
							? callee.property.name
							: null;
				if (calleeName !== "createTickBuffer") return;
				if (node.id.type !== "Identifier") return;
				tickBufferNames.push({ name: node.id.name, node });
			},
			"Program:exit"() {
				for (const { name, node } of tickBufferNames) {
					const disposePattern = new RegExp(
						`\\b${name}\\s*\\.\\s*dispose\\s*\\(`,
					);
					if (!disposePattern.test(sourceText)) {
						context.report({
							node,
							messageId: "missingDispose",
							data: { name },
						});
					}
				}
			},
		};
	},
};
