import type { ParamMatcher } from "@sveltejs/kit";

const VALID_VERTICALS = new Set(["private_credit", "liquid_funds"]);

export const match: ParamMatcher = (param) => {
	return VALID_VERTICALS.has(param);
};
