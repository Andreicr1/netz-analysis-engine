import type { Config } from "tailwindcss";

export default {
	content: [
		"./src/**/*.{html,js,svelte,ts}",
		"../../packages/ui/src/**/*.{html,js,svelte,ts}",
	],
	theme: {
		extend: {
			colors: {
				netz: {
					navy: "var(--netz-navy)",
					blue: "var(--netz-blue)",
					slate: "var(--netz-slate)",
					light: "var(--netz-light)",
					orange: "var(--netz-orange)",
				},
			},
			fontFamily: {
				sans: ["var(--netz-font-sans)", "Inter Variable", "system-ui", "sans-serif"],
				mono: ["var(--netz-font-mono)", "JetBrains Mono", "monospace"],
			},
		},
	},
} satisfies Config;
