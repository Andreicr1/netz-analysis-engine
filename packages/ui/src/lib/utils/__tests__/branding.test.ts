import { describe, it, expect } from "vitest";
import { defaultBranding, brandingToCSS } from "../branding.js";

describe("defaultBranding", () => {
	it("has Netz default primary color", () => {
		expect(defaultBranding.primary_color).toBe("#1B365D");
	});

	it("has all required fields", () => {
		expect(defaultBranding.org_name).toBe("Netz");
		expect(defaultBranding.font_sans).toBeTruthy();
		expect(defaultBranding.surface_color).toBeTruthy();
	});
});

describe("brandingToCSS", () => {
	it("converts branding to CSS custom properties", () => {
		const css = brandingToCSS(defaultBranding);
		expect(css).toContain("--netz-brand-primary:");
		expect(css).toContain("#1B365D");
		expect(css).toContain("--netz-font-sans:");
	});

	it("includes all color properties", () => {
		const css = brandingToCSS(defaultBranding);
		expect(css).toContain("--netz-brand-secondary:");
		expect(css).toContain("--netz-surface:");
		expect(css).toContain("--netz-text-primary:");
	});
});
