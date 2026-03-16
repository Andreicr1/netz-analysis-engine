/**
 * Credit-specific API client wrappers.
 * Re-exports @netz/ui factories with credit backend base URL.
 */

import {
	createServerApiClient as createServer,
	createClientApiClient as createClient,
	setAuthRedirectHandler,
	setConflictHandler,
} from "@netz/ui/utils";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

/** Server-side API client (for +page.server.ts / +layout.server.ts). */
export function createServerApiClient(token: string) {
	return createServer(API_BASE, token);
}

/** Client-side API client (for browser components). */
export function createClientApiClient(getToken: () => Promise<string>) {
	return createClient(API_BASE, getToken);
}

export { setAuthRedirectHandler, setConflictHandler };
