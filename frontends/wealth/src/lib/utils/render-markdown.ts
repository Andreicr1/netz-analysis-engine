/**
 * Safe regex-based markdown → HTML renderer with DOMPurify defense-in-depth.
 *
 * Backend nh3 sanitizes at persist boundary; DOMPurify is the frontend safety net.
 * Supports: headings, bold, italic, code, lists, paragraphs.
 * Output uses `.rw-*` class names for scoped styling.
 */

import DOMPurify from "dompurify";

const ALLOWED_TAGS = [
	"h1", "h2", "h3", "h4", "h5", "h6",
	"p", "strong", "em", "code", "ul", "ol", "li",
	"a", "sup", "sub", "br", "blockquote", "pre",
	"table", "thead", "tbody", "tr", "th", "td",
];
const ALLOWED_ATTR = ["href", "title", "class", "colspan", "rowspan"];

export function renderMarkdown(md: string | null): string {
	if (!md) return '<p class="rw-empty">Content not yet generated.</p>';
	const html = md
		.replace(/^### (.+)$/gm, '<h3 class="rw-h3">$1</h3>')
		.replace(/^## (.+)$/gm, '<h2 class="rw-h2">$1</h2>')
		.replace(/^# (.+)$/gm, '<h1 class="rw-h1">$1</h1>')
		.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
		.replace(/\*(.+?)\*/g, "<em>$1</em>")
		.replace(/`(.+?)`/g, '<code class="rw-code">$1</code>')
		.replace(/^- (.+)$/gm, '<li class="rw-li">$1</li>')
		.replace(/(<li[^>]*>.*<\/li>\n?)+/g, '<ul class="rw-ul">$&</ul>')
		.replace(/^(?!<[hul]|<li|<strong|<em|<code)(.+)$/gm, '<p class="rw-p">$1</p>')
		.replace(/\n{2,}/g, "");
	return DOMPurify.sanitize(html, {
		ALLOWED_TAGS,
		ALLOWED_ATTR,
	});
}

/**
 * Recursively flatten a nested object into dot-notation key-value pairs.
 * Used for displaying evidence_refs and quant_data in content/DD report detail views.
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
