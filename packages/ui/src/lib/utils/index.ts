// @netz/ui — Utility Exports
// ===========================

export { cn } from "./cn.js";
export type { NavItem, BrandingConfig } from "./types.js";

// API client
export {
	NetzApiClient,
	AuthError,
	ForbiddenError,
	ValidationError,
	ServerError,
	ConflictError,
	createServerApiClient,
	createClientApiClient,
	setAuthRedirectHandler,
	setConflictHandler,
	resetRedirectGate,
	isRedirecting,
} from "./api-client.js";

// SSE client
export { createSSEStream, createSSEWithSnapshot } from "./sse-client.svelte.js";
export type { SSEConfig, SSEConnection, SSEStatus, SSEEvent, SSESnapshotConfig, SSESnapshotConnection } from "./sse-client.svelte.js";

// Formatting
export {
	formatCurrency,
	formatPercent,
	formatCompact,
	formatDate,
	formatDateRange,
	formatISIN,
} from "./format.js";

// Branding
export {
	defaultBranding,
	brandingToCSS,
	injectBranding,
	getBrandingFromCSS,
} from "./branding.js";

// Auth stubs + session monitoring
export {
	createClerkHook,
	createRootLayoutLoader,
	startSessionExpiryMonitor,
} from "./auth.js";
export type { ClerkHookOptions, RootLayoutLoaderOptions } from "./auth.js";
