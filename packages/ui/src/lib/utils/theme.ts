import type { Handle } from "@sveltejs/kit";

const VALID_THEMES = new Set(["dark", "light"]);

/**
 * Create a SvelteKit handle hook that injects data-theme into SSR HTML.
 * Reads the "netz-theme" cookie; falls back to defaultTheme if invalid.
 * Must match the data-theme value in the frontend's app.html.
 */
export function createThemeHook(options: { defaultTheme?: "dark" | "light" } = {}): Handle {
	const defaultTheme = options.defaultTheme ?? "light";
	return async ({ event, resolve }) => {
		const raw = event.cookies.get("netz-theme") || defaultTheme;
		const theme = VALID_THEMES.has(raw) ? raw : defaultTheme;
		return resolve(event, {
			transformPageChunk: ({ html }) =>
				html.replace(`data-theme="${defaultTheme}"`, `data-theme="${theme}"`),
		});
	};
}
