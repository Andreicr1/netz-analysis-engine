/** Clerk auth stub factories for SvelteKit frontends. */

import type { BrandingConfig } from "./types.js";

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
