import { RuleTester } from "eslint";
import { describe, it } from "vitest";

import rule from "../src/rules/require-tick-buffer-dispose.js";

const ruleTester = new RuleTester({
	languageOptions: {
		ecmaVersion: "latest",
		sourceType: "module",
		globals: {
			createTickBuffer: "readonly",
			onDestroy: "readonly",
		},
	},
});

describe("require-tick-buffer-dispose", () => {
	it("runs", () => {
		ruleTester.run("require-tick-buffer-dispose", rule, {
			valid: [
				// dispose call matches buffer name.
				{
					code:
						"const buf = createTickBuffer({ keyOf: (t) => t.ticker });\n" +
						"onDestroy(() => buf.dispose());",
				},
				// Explicit dispose inside a function is still detected.
				{
					code:
						"const priceBuf = createTickBuffer({ keyOf: (t) => t.ticker });\n" +
						"function cleanup() { priceBuf.dispose(); }",
				},
				// No createTickBuffer at all.
				{
					code: "const x = 1;",
				},
			],
			invalid: [
				{
					code: "const buf = createTickBuffer({ keyOf: (t) => t.id });",
					errors: [{ messageId: "missingDispose" }],
				},
				{
					code:
						"const buf = createTickBuffer({ keyOf: (t) => t.id });\n" +
						"onDestroy(() => { /* forgot */ });",
					errors: [{ messageId: "missingDispose" }],
				},
			],
		});
	});
});
