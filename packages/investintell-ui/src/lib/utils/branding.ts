/** Branding utilities for tenant theming. */

import type { BrandingConfig } from "./types.js";

// -- Sanitization ---------------------------------------------------------
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

// -- Defaults -------------------------------------------------------------

/** Default light branding — matches :root tokens in tokens.css. */
export const defaultBranding: BrandingConfig = {
	primary_color: "#18324d",
	secondary_color: "#3e628d",
	accent_color: "#8395a8",
	light_color: "#e6edf6",
	highlight_color: "#c58757",
	surface_color: "#f4f7fb",
	surface_alt_color: "#edf2f7",
	surface_elevated_color: "#ffffff",
	surface_inset_color: "#e7edf4",
	border_color: "#c5d0de",
	text_primary: "#122033",
	text_secondary: "#48586b",
	text_muted: "#6f7f93",
	font_sans: "'Inter Variable', system-ui, sans-serif",
	font_mono: "'JetBrains Mono', monospace",
	logo_light_url: null,
	logo_dark_url: null,
	favicon_url: null,
	org_name: "Netz",
	org_slug: "netz",
};

/** Default dark branding — matches [data-theme="dark"] tokens in tokens.css. */
export const defaultDarkBranding: BrandingConfig = {
	primary_color: "#84a8d0",
	secondary_color: "#7ea4d8",
	accent_color: "#96a7bc",
	light_color: "#22324a",
	highlight_color: "#d49a68",
	surface_color: "#0c1220",
	surface_alt_color: "#152638",
	surface_elevated_color: "#1a2d44",
	surface_inset_color: "#0b121c",
	border_color: "#345270",
	text_primary: "#f4f7fb",
	text_secondary: "#c0cad7",
	text_muted: "#8d9caf",
	font_sans: "'Inter Variable', system-ui, sans-serif",
	font_mono: "'JetBrains Mono', monospace",
	logo_light_url: null,
	logo_dark_url: null,
	favicon_url: null,
	org_name: "Netz",
	org_slug: "netz",
};

// -- WCAG Contrast Validation ---------------------------------------------

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

// -- CSS var mapping ------------------------------------------------------

const CSS_VAR_MAP: Record<keyof BrandingConfig, string | null> = {
	primary_color: "--ii-brand-primary",
	secondary_color: "--ii-brand-secondary",
	accent_color: "--ii-brand-accent",
	light_color: "--ii-brand-light",
	highlight_color: "--ii-brand-highlight",
	surface_color: "--ii-surface",
	surface_alt_color: "--ii-surface-alt",
	surface_elevated_color: "--ii-surface-elevated",
	surface_inset_color: "--ii-surface-inset",
	border_color: "--ii-border",
	text_primary: "--ii-text-primary",
	text_secondary: "--ii-text-secondary",
	text_muted: "--ii-text-muted",
	font_sans: "--ii-font-sans",
	font_mono: "--ii-font-mono",
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

			// To support the native CSS dark/light mode toggle via tokens.css cascade,
			// we MUST NOT inject values that exactly match the default system tokens.
			// If we inject them as inline styles, the CSS cascade (and toggle) breaks.
			const matchesLight = safe === String(defaultBranding[key as keyof BrandingConfig]);
			const matchesDark = safe === String(defaultDarkBranding[key as keyof BrandingConfig]);

			if (safe && !matchesLight && !matchesDark) {
				element.style.setProperty(varName, safe);
			} else {
				// Clear any previously injected default so tokens.css takes over natively
				element.style.removeProperty(varName);
			}
		}
	}
}
