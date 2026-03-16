/** Clerk auth stub factories and session monitoring for SvelteKit frontends. */

import type { BrandingConfig } from "./types.js";

// ── Session Expiry Monitor ──────────────────────────────────────

/** Default warning threshold: 5 minutes before JWT expiry. */
const SESSION_WARNING_MS = 5 * 60 * 1000;

/**
 * Decode JWT `exp` claim and schedule a warning callback before expiry.
 *
 * Critical for long-running operations (IC memo ~3min, DD report ~3min,
 * backtest ~variable) that must not be silently interrupted.
 *
 * @returns Cleanup function to cancel the timer.
 */
export function startSessionExpiryMonitor(
	token: string,
	onWarning: () => void,
	warningMs: number = SESSION_WARNING_MS,
): () => void {
	try {
		const parts = token.split(".");
		if (parts.length !== 3) return () => {};

		const payload = JSON.parse(atob(parts[1]));
		const exp = payload.exp;
		if (typeof exp !== "number") return () => {};

		const expMs = exp * 1000;
		const warningAt = expMs - warningMs;
		const delay = warningAt - Date.now();

		if (delay <= 0) {
			// Already within warning window — fire immediately
			onWarning();
			return () => {};
		}

		const timer = setTimeout(onWarning, delay);
		return () => clearTimeout(timer);
	} catch {
		// Malformed token — don't crash, just skip monitoring
		return () => {};
	}
}

export interface ClerkHookOptions {
	publishableKey: string;
	secretKey: string;
	devBypass?: boolean;
}

export interface RootLayoutLoaderOptions {
	brandingUrl: string;
	defaultBranding: BrandingConfig;
	cacheTtlMs?: number;
}

/**
 * Create a SvelteKit handle function that validates Clerk JWTs.
 *
 * Stub — actual Clerk integration is per-frontend.
 * Each frontend fills in the implementation using clerk-sveltekit or manual JWT verification.
 */
export function createClerkHook(_options: ClerkHookOptions) {
	return async ({ event, resolve }: { event: unknown; resolve: (event: unknown) => Promise<Response> }) => {
		// Stub: pass through without auth validation.
		// Real implementation validates JWT, extracts org_id, attaches to event.locals.
		return resolve(event);
	};
}

/**
 * Create a SvelteKit root +layout.server.ts load function that fetches branding.
 *
 * Stub — actual implementation fetches from backend API and caches.
 */
export function createRootLayoutLoader(options: RootLayoutLoaderOptions) {
	return async () => {
		// Stub: return default branding.
		// Real implementation fetches from options.brandingUrl, caches for cacheTtlMs.
		return {
			branding: options.defaultBranding,
		};
	};
}
