/**
 * Safe markdown → HTML renderer using `marked` + DOMPurify defense-in-depth.
 *
 * marked handles full CommonMark including tables, horizontal rules,
 * numbered lists, and nested structures.
 * DOMPurify sanitizes the output — backend nh3 is the persist-boundary guard.
 */

import { marked } from "marked";
import DOMPurify from "dompurify";

const ALLOWED_TAGS = [
	"h1", "h2", "h3", "h4", "h5", "h6",
	"p", "strong", "em", "code", "pre",
	"ul", "ol", "li",
	"table", "thead", "tbody", "tr", "th", "td",
	"blockquote", "hr", "br",
	"a", "sup", "sub",
];
const ALLOWED_ATTR = ["href", "title", "class", "colspan", "rowspan", "align"];

// Configure marked: no async, use GFM (GitHub Flavored Markdown) for tables
marked.setOptions({ gfm: true, breaks: false });

export function renderMarkdown(md: string | null): string {
	if (!md) return '<p class="rw-empty">Content not yet generated.</p>';
	const raw = marked.parse(md) as string;
	return DOMPurify.sanitize(raw, { ALLOWED_TAGS, ALLOWED_ATTR });
}

/**
 * Recursively flatten a nested object into dot-notation key-value pairs.
 */
export function flattenObject(
	obj: Record<string, unknown>,
	prefix = "",
): Array<{ key: string; value: string }> {
	const entries: Array<{ key: string; value: string }> = [];
	for (const [k, v] of Object.entries(obj)) {
		const label = prefix ? `${prefix} \u203A ${k}` : k;
		if (v && typeof v === "object" && !Array.isArray(v)) {
			entries.push(...flattenObject(v as Record<string, unknown>, label));
		} else {
			entries.push({ key: label, value: String(v ?? "\u2014") });
		}
	}
	return entries;
}
