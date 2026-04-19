/**
 * Client hook — session expiry monitor.
 *
 * Shows a 2-minute pre-expiry warning so long-running terminal analyses
 * (live workbench polling, screener tasks) surface a session-renewal UX
 * before Clerk auto-refresh silently kicks in.
 *
 * The actual token used by the warning is picked up inside +layout.svelte
 * via setContext("netz:getToken"). This hook is intentionally minimal
 * because X2+ components wire the real token flow.
 */
import type { HandleClientError } from "@sveltejs/kit";

export const handleError: HandleClientError = ({ error }) => {
	const message = error instanceof Error ? error.message : String(error);
	return {
		message,
	};
};
