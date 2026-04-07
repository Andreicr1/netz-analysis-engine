/**
 * Rule: require-load-timeout
 *
 * Stability Guardrails P6. Prevents the "FactSheet hangs forever"
 * failure class where a SvelteKit load function awaits a fetch that
 * never resolves. Every `+page.{ts,server.ts}` / `+layout.{ts,server.ts}`
 * load function must wrap its fetch call in `AbortSignal.timeout(...)`.
 *
 * Heuristic (v1): inside files matching `+(page|layout)[*.](ts|js)` or
 * `+(page|layout).server.(ts|js)`, flag any `fetch(...)` call or
 * `*.get`/`*.post`/`*.put`/`*.delete` call that does not pass an
 * object argument containing a `signal:` key AND whose file body does
 * not mention `AbortSignal.timeout` anywhere.
 */

const LOAD_FILE_RE = /[+](page|layout)(\.server)?\.(ts|js)$/;
const HTTP_METHODS = new Set(["get", "post", "put", "patch", "delete", "head"]);

/** @type {import("eslint").Rule.RuleModule} */
export default {
	meta: {
		type: "problem",
		docs: {
			description:
				"Require SvelteKit load functions to use AbortSignal.timeout() on every fetch.",
			url: "docs/reference/stability-guardrails.md#p6-fault-tolerant",
		},
		messages: {
			noTimeout:
				"Load function calls '{{callee}}' without AbortSignal.timeout(). " +
				"Every fetch inside +page.{ts,server.ts} must be time-bounded. " +
				"See docs/reference/stability-guardrails.md#p6-fault-tolerant.",
		},
		schema: [],
	},
	create(context) {
		const filename = context.filename || context.getFilename?.() || "";
		if (!LOAD_FILE_RE.test(filename)) {
			return {};
		}

		const source = context.sourceCode || context.getSourceCode?.();
		if (!source) return {};
		const sourceText = source.getText();
		// File-level escape hatch: if the module mentions AbortSignal.timeout
		// anywhere, assume it is being applied and do not nag per-call. This
		// is a deliberate false-negative bias — see charter §5 note on
		// alert fatigue.
		if (sourceText.includes("AbortSignal.timeout")) return {};

		return {
			CallExpression(node) {
				const callee = node.callee;
				if (!callee) return;

				// Case 1: fetch(...)
				if (callee.type === "Identifier" && callee.name === "fetch") {
					context.report({
						node,
						messageId: "noTimeout",
						data: { callee: "fetch" },
					});
					return;
				}

				// Case 2: something.get(...) / .post(...) / .put(...) / .delete(...)
				if (
					callee.type === "MemberExpression" &&
					callee.property &&
					callee.property.type === "Identifier" &&
					HTTP_METHODS.has(callee.property.name)
				) {
					// Only flag inside awaited calls to avoid touching
					// unrelated helper functions named .get() on maps, etc.
					const parent = node.parent;
					if (parent && parent.type === "AwaitExpression") {
						context.report({
							node,
							messageId: "noTimeout",
							data: {
								callee: `.${callee.property.name}()`,
							},
						});
					}
				}
			},
		};
	},
};
