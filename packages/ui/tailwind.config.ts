import type { Config } from "tailwindcss";

/** Shared Tailwind preset for all Netz frontends.
 *  Frontends extend this config — never duplicate token definitions. */
export default {
	content: ["./src/**/*.{html,js,svelte,ts}"],
	theme: {
		extend: {
			colors: {
				netz: {
					navy: "var(--netz-brand-primary, #1B365D)",
					blue: "var(--netz-brand-secondary, #3A7BD5)",
					slate: "var(--netz-brand-accent, #8B9DAF)",
					light: "var(--netz-brand-light, #D4E4F7)",
					orange: "var(--netz-brand-highlight, #FF975A)",
					surface: "var(--netz-surface, #FFFFFF)",
					"surface-alt": "var(--netz-surface-alt, #F8FAFC)",
					border: "var(--netz-border, #E2E8F0)",
					"text-primary": "var(--netz-text-primary, #0F172A)",
					"text-secondary": "var(--netz-text-secondary, #475569)",
					"text-muted": "var(--netz-text-muted, #94A3B8)",
				},
			},
			fontFamily: {
				sans: ["var(--netz-font-sans, 'Inter Variable', Inter, sans-serif)"],
				mono: ["var(--netz-font-mono, 'JetBrains Mono', monospace)"],
			},
			spacing: {
				"netz-1": "var(--netz-space-1, 4px)",
				"netz-2": "var(--netz-space-2, 8px)",
				"netz-3": "var(--netz-space-3, 12px)",
				"netz-4": "var(--netz-space-4, 16px)",
				"netz-5": "var(--netz-space-5, 20px)",
				"netz-6": "var(--netz-space-6, 24px)",
				"netz-8": "var(--netz-space-8, 32px)",
				"netz-10": "var(--netz-space-10, 40px)",
				"netz-12": "var(--netz-space-12, 48px)",
				"netz-16": "var(--netz-space-16, 64px)",
			},
			boxShadow: {
				"netz-1": "var(--netz-shadow-1, 0 1px 2px 0 rgba(0,0,0,0.05))",
				"netz-2": "var(--netz-shadow-2, 0 1px 3px 0 rgba(0,0,0,0.1), 0 1px 2px -1px rgba(0,0,0,0.1))",
				"netz-3": "var(--netz-shadow-3, 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.1))",
				"netz-4": "var(--netz-shadow-4, 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1))",
				"netz-5": "var(--netz-shadow-5, 0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1))",
			},
			transitionDuration: {
				"netz-fast": "var(--netz-duration-fast, 150ms)",
				"netz-normal": "var(--netz-duration-normal, 250ms)",
				"netz-slow": "var(--netz-duration-slow, 350ms)",
			},
		},
	},
	plugins: [],
} satisfies Config;
