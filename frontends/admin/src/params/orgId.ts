import type { ParamMatcher } from "@sveltejs/kit";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ORG_PREFIX_RE = /^org_[a-zA-Z0-9]+$/;

export const match: ParamMatcher = (param) => {
	return UUID_RE.test(param) || ORG_PREFIX_RE.test(param);
};
