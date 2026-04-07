import { RuleTester } from "eslint";
import { describe, it } from "vitest";

import rule from "../src/rules/no-unsafe-derived.js";

const ruleTester = new RuleTester({
	languageOptions: {
		ecmaVersion: "latest",
		sourceType: "module",
		globals: {
			$derived: "readonly",
		},
	},
});

describe("no-unsafe-derived", () => {
	it("runs", () => {
		ruleTester.run("no-unsafe-derived", rule, {
			valid: [
				// Optional chaining.
				{ code: "const aum = $derived(data?.aum_usd ?? 0);" },
				// No nullable identifier.
				{ code: "const doubled = $derived(count * 2);" },
				// Uses a local variable, not `data`.
				{ code: "const x = $derived(localState.value);" },
				// Function call is fine.
				{ code: "const c = $derived(compute(data));" },
			],
			invalid: [
				{
					code: "const aum = $derived(data.aum_usd);",
					errors: [{ messageId: "unsafeDerived" }],
				},
				{
					code: "const name = $derived(routeData.name);",
					errors: [{ messageId: "unsafeDerived" }],
				},
				{
					code: "const nested = $derived(factSheet.fund.name);",
					errors: [{ messageId: "unsafeDerived" }],
				},
			],
		});
	});
});
