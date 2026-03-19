/** Branding utilities for tenant theming. */

import type { BrandingConfig } from "./types.js";

// ── Sanitization ─────────────────────────────────────────────
const HEX_RE = /^#[0-9a-fA-F]{3,8}$/;
const RGB_HSL_RE = /^(rgb|hsl)a?\(\s*[\d.%,\s/]+\)$/;
const FONT_RE = /^['"][^'"]+['"](\s*,\s*['"][^'"]+['"]|\s*,\s*[a-zA-Z-]+)*(\s*,\s*[a-zA-Z-]+)*$/;
const DANGEROUS_RE = /url\(|expression\(|@import|;|\{|\}/i;

function isValidColor(value: string): boolean {
	return (HEX_RE.test(value) || RGB_HSL_RE.test(value)) && !DANGEROUS_RE.test(value);
}

function isValidFont(value: string): boolean {
	return FONT_RE.test(value) && !DANGEROUS_RE.test(value);
}

/** Sanitize a CSS value before injection. Returns null if invalid. */
function sanitizeCSSValue(key: string, value: string): string | null {
	if (key === "font_sans" || key === "font_mono") {
		return isValidFont(value) ? value : null;
	}
	return isValidColor(value) ? value : null;
}

// ── Defaults ─────────────────────────────────────────────────

/** Netz light default branding — matches :root tokens in tokens.css. */
export const defaultBranding: BrandingConfig = {
	primary_color: "#1B365D",
	secondary_color: "#3A7BD5",
	accent_color: "#8B9DAF",
	light_color: "#D4E4F7",
	highlight_color: "#FF975A",
	surface_color: "#FFFFFF",
	surface_alt_color: "#F8FAFC",
	surface_elevated_color: "#FFFFFF",
	surface_inset_color: "#F1F5F9",
	border_color: "#E2E8F0",
	text_primary: "#0F172A",
	text_secondary: "#475569",
	text_muted: "#94A3B8",
	font_sans: "'Inter Variable', Inter, system-ui, sans-serif",
	font_mono: "'JetBrains Mono', monospace",
	logo_light_url: null,
	logo_dark_url: null,
	favicon_url: null,
	org_name: "Netz",
	org_slug: "netz",
};

/** Netz dark default branding — matches [data-theme="dark"] tokens in tokens.css. */
export const defaultDarkBranding: BrandingConfig = {
	primary_color: "#4A90D9",
	secondary_color: "#60A5FA",
	accent_color: "#94A3B8",
	light_color: "#1E3A5F",
	highlight_color: "#FF975A",
	surface_color: "#0F1117",
	surface_alt_color: "#161922",
	surface_elevated_color: "#1C1F2B",
	surface_inset_color: "#090C10",
	border_color: "#2A2F3D",
	text_primary: "#F1F5F9",
	text_secondary: "#94A3B8",
	text_muted: "#64748B",
	font_sans: "'Inter Variable', Inter, system-ui, sans-serif",
	font_mono: "'JetBrains Mono', monospace",
	logo_light_url: null,
	logo_dark_url: null,
	favicon_url: null,
	org_name: "Netz",
	org_slug: "netz",
};

// ── WCAG Contrast Validation ─────────────────────────────────

/** Parse hex color to [r, g, b]. Returns null if invalid. */
function hexToRgb(hex: string): [number, number, number] | null {
	const m = /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6,8})$/.exec(hex);
	if (!m || !m[1]) return null;
	const h = m[1];
	if (h.length === 3) {
		return [
			parseInt(h.charAt(0) + h.charAt(0), 16),
			parseInt(h.charAt(1) + h.charAt(1), 16),
			parseInt(h.charAt(2) + h.charAt(2), 16),
		];
	}
	return [
		parseInt(h.slice(0, 2), 16),
		parseInt(h.slice(2, 4), 16),
		parseInt(h.slice(4, 6), 16),
	];
}

/** Relative luminance per WCAG 2.1. */
function relativeLuminance([r, g, b]: [number, number, number]): number {
	function linearize(c: number): number {
		const s = c / 255;
		return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
	}
	return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b);
}

/** WCAG contrast ratio between two hex colors. Returns 1 if either is invalid. */
function contrastRatio(hex1: string, hex2: string): number {
	const rgb1 = hexToRgb(hex1);
	const rgb2 = hexToRgb(hex2);
	if (!rgb1 || !rgb2) return 1;
	const l1 = relativeLuminance(rgb1);
	const l2 = relativeLuminance(rgb2);
	const lighter = Math.max(l1, l2);
	const darker = Math.min(l1, l2);
	return (lighter + 0.05) / (darker + 0.05);
}

/** WCAG AA minimum contrast (4.5:1 for normal text). */
const WCAG_AA_MIN = 4.5;

/** Text/surface pairs that must meet WCAG AA contrast. */
const CONTRAST_PAIRS: Array<[keyof BrandingConfig, keyof BrandingConfig, string]> = [
	["text_primary", "surface_color", "text_primary vs surface_color"],
	["text_primary", "surface_alt_color", "text_primary vs surface_alt_color"],
	["text_primary", "surface_elevated_color", "text_primary vs surface_elevated_color"],
	["text_secondary", "surface_color", "text_secondary vs surface_color"],
	["text_muted", "surface_color", "text_muted vs surface_color"],
];

export type ContrastViolation = { pair: string; ratio: number; minimum: number };

/**
 * Validate WCAG AA contrast between text and surface colors.
 * Returns an array of violations (empty = valid).
 */
export function validateBrandingContrast(config: BrandingConfig): ContrastViolation[] {
	const violations: ContrastViolation[] = [];
	for (const [textKey, surfaceKey, label] of CONTRAST_PAIRS) {
		const textColor = config[textKey];
		const surfaceColor = config[surfaceKey];
		if (typeof textColor !== "string" || typeof surfaceColor !== "string") continue;
		if (!HEX_RE.test(textColor) || !HEX_RE.test(surfaceColor)) continue;
		const ratio = contrastRatio(textColor, surfaceColor);
		if (ratio < WCAG_AA_MIN) {
			violations.push({ pair: label, ratio: Math.round(ratio * 100) / 100, minimum: WCAG_AA_MIN });
		}
	}
	return violations;
}

// ── CSS var mapping ──────────────────────────────────────────

const CSS_VAR_MAP: Record<keyof BrandingConfig, string | null> = {
	primary_color: "--netz-brand-primary",
	secondary_color: "--netz-brand-secondary",
	accent_color: "--netz-brand-accent",
	light_color: "--netz-brand-light",
	highlight_color: "--netz-brand-highlight",
	surface_color: "--netz-surface",
	surface_alt_color: "--netz-surface-alt",
	surface_elevated_color: "--netz-surface-elevated",
	surface_inset_color: "--netz-surface-inset",
	border_color: "--netz-border",
	text_primary: "--netz-text-primary",
	text_secondary: "--netz-text-secondary",
	text_muted: "--netz-text-muted",
	font_sans: "--netz-font-sans",
	font_mono: "--netz-font-mono",
	logo_light_url: null,
	logo_dark_url: null,
	favicon_url: null,
	org_name: null,
	org_slug: null,
};

/**
 * Convert BrandingConfig to an inline CSS custom property string.
 * Only includes properties that have a CSS var mapping.
 */
export function brandingToCSS(config: BrandingConfig): string {
	const parts: string[] = [];
	for (const [key, varName] of Object.entries(CSS_VAR_MAP)) {
		if (!varName) continue;
		const value = config[key as keyof BrandingConfig];
		if (value != null) {
			const safe = sanitizeCSSValue(key, String(value));
			if (safe) parts.push(`${varName}: ${safe}`);
		}
	}
	return parts.join("; ");
}

/** Last-injected branding reference for shallow equality skip. */
let _lastBranding: BrandingConfig | null = null;

/**
 * Set CSS custom properties on a DOM element from BrandingConfig.
 * Skips re-injection if branding object reference is unchanged.
 * Sanitizes all values before injection.
 */
export function injectBranding(element: HTMLElement, config: BrandingConfig): void {
	if (!config) return;
	if (config === _lastBranding) return;
	_lastBranding = config;

	for (const [key, varName] of Object.entries(CSS_VAR_MAP)) {
		if (!varName) continue;
		const value = config[key as keyof BrandingConfig];
		if (value != null) {
			const safe = sanitizeCSSValue(key, String(value));
			if (safe) {
				element.style.setProperty(varName, safe);
			}
		}
	}
}
