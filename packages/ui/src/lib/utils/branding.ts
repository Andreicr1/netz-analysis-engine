/** Branding utilities for tenant theming. */

import type { BrandingConfig } from "./types.js";

/** Netz navy default branding theme — matches design tokens in tokens.css. */
export const defaultBranding: BrandingConfig = {
	primary_color: "#1B365D",
	secondary_color: "#3A7BD5",
	accent_color: "#8B9DAF",
	light_color: "#D4E4F7",
	highlight_color: "#FF975A",
	surface_color: "#FFFFFF",
	surface_alt_color: "#F8FAFC",
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

const CSS_VAR_MAP: Record<keyof BrandingConfig, string | null> = {
	primary_color: "--netz-brand-primary",
	secondary_color: "--netz-brand-secondary",
	accent_color: "--netz-brand-accent",
	light_color: "--netz-brand-light",
	highlight_color: "--netz-brand-highlight",
	surface_color: "--netz-surface",
	surface_alt_color: "--netz-surface-alt",
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
			parts.push(`${varName}: ${value}`);
		}
	}
	return parts.join("; ");
}

/**
 * Set CSS custom properties on a DOM element from BrandingConfig.
 */
export function injectBranding(element: HTMLElement, config: BrandingConfig): void {
	for (const [key, varName] of Object.entries(CSS_VAR_MAP)) {
		if (!varName) continue;
		const value = config[key as keyof BrandingConfig];
		if (value != null) {
			element.style.setProperty(varName, value);
		}
	}
}

/**
 * Read current CSS custom properties from the document and return a partial BrandingConfig.
 */
export function getBrandingFromCSS(): Partial<BrandingConfig> {
	if (typeof document === "undefined") return {};

	const style = getComputedStyle(document.documentElement);
	const result: Partial<BrandingConfig> = {};

	for (const [key, varName] of Object.entries(CSS_VAR_MAP)) {
		if (!varName) continue;
		const value = style.getPropertyValue(varName).trim();
		if (value) {
			(result as Record<string, string>)[key] = value;
		}
	}

	return result;
}
