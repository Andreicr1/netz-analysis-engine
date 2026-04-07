import { RuleTester } from "eslint";
import { describe, it } from "vitest";

import rule from "../src/rules/require-svelte-boundary.js";

const ruleTester = new RuleTester({
	languageOptions: {
		ecmaVersion: "latest",
		sourceType: "module",
	},
});

describe("require-svelte-boundary", () => {
	it("runs", () => {
		ruleTester.run("require-svelte-boundary", rule, {
			valid: [
				// Not a page/layout file — ignored.
				{
					code: "// <Foo /> is fine in any other file",
					filename: "src/lib/components/Foo.svelte",
				},
				// Page with a boundary.
				{
					code:
						"// <svelte:boundary>\n" +
						"//   <FundDetailPanel />\n" +
						"// </svelte:boundary>",
					filename: "src/routes/+page.svelte",
				},
				// Page with no components — static HTML only.
				{
					code: "// <h1>Static</h1>",
					filename: "src/routes/about/+page.svelte",
				},
			],
			invalid: [
				{
					code: "// <FundDetailPanel data={data} />",
					filename: "src/routes/fund/+page.svelte",
					errors: [{ messageId: "missingBoundary" }],
				},
				{
					code: "// <ManagerPanel />",
					filename: "src/routes/manager/+layout.svelte",
					errors: [{ messageId: "missingBoundary" }],
				},
			],
		});
	});
});
