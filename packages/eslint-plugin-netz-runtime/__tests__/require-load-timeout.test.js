import { RuleTester } from "eslint";
import { describe, it } from "vitest";

import rule from "../src/rules/require-load-timeout.js";

const ruleTester = new RuleTester({
	languageOptions: {
		ecmaVersion: "latest",
		sourceType: "module",
	},
});

describe("require-load-timeout", () => {
	it("runs", () => {
		ruleTester.run("require-load-timeout", rule, {
			valid: [
				// Not a load file — ignored.
				{
					code: "export const x = () => fetch('/api');",
					filename: "src/lib/whatever.ts",
				},
				// Load file with AbortSignal.timeout somewhere in the source.
				{
					code:
						"export const load = async () => {\n" +
						"  return fetch('/api', { signal: AbortSignal.timeout(8000) });\n" +
						"};",
					filename: "src/routes/foo/+page.server.ts",
				},
				// Load file with an api.get that uses a timeout signal.
				{
					code:
						"const s = AbortSignal.timeout(8000);\n" +
						"export const load = async () => {\n" +
						"  const r = await api.get('/x', { signal: s });\n" +
						"  return r;\n" +
						"};",
					filename: "src/routes/x/+page.ts",
				},
			],
			invalid: [
				{
					code:
						"export const load = async () => {\n" +
						"  const r = await api.get('/fund/SPY');\n" +
						"  return r;\n" +
						"};",
					filename: "src/routes/fund/[id]/+page.server.ts",
					errors: [{ messageId: "noTimeout" }],
				},
				{
					code:
						"export const load = async () => {\n" +
						"  return fetch('/api');\n" +
						"};",
					filename: "src/routes/x/+page.ts",
					errors: [{ messageId: "noTimeout" }],
				},
			],
		});
	});
});
