// @netz/ui — Shared Design System
// ================================
// Barrel export for all components, layouts, charts, and utilities.

// ── Components ──────────────────────────────────────────────
export { default as Button } from "./components/Button.svelte";
export { default as Card } from "./components/Card.svelte";
export { default as Badge } from "./components/Badge.svelte";
export { default as Dialog } from "./components/Dialog.svelte";
export { default as Sheet } from "./components/Sheet.svelte";
export { default as Tabs } from "./components/Tabs.svelte";
export { default as Input } from "./components/Input.svelte";
export { default as Select } from "./components/Select.svelte";
export { default as Textarea } from "./components/Textarea.svelte";
export { default as Tooltip } from "./components/Tooltip.svelte";
export { default as DropdownMenu } from "./components/DropdownMenu.svelte";
export { default as Skeleton } from "./components/Skeleton.svelte";

// ── Data Components ─────────────────────────────────────────
export { default as DataTable } from "./components/DataTable.svelte";
export { default as DataTableToolbar } from "./components/DataTableToolbar.svelte";

// ── Netz Composites ─────────────────────────────────────────
export { default as DataCard } from "./components/DataCard.svelte";
export { default as StatusBadge } from "./components/StatusBadge.svelte";
export { default as EmptyState } from "./components/EmptyState.svelte";
export { default as PDFDownload } from "./components/PDFDownload.svelte";
export { default as LanguageToggle } from "./components/LanguageToggle.svelte";
export { default as ErrorBoundary } from "./components/ErrorBoundary.svelte";
export { default as ConnectionLost } from "./components/ConnectionLost.svelte";
export { default as BackendUnavailable } from "./components/BackendUnavailable.svelte";
export { default as Toast } from "./components/Toast.svelte";
export { default as PageTabs } from "./components/PageTabs.svelte";

// ── Layouts ─────────────────────────────────────────────────
export { default as AppLayout } from "./layouts/AppLayout.svelte";
export { default as AppShell } from "./layouts/AppShell.svelte";
export { default as Sidebar } from "./layouts/Sidebar.svelte";
export { default as ContextPanel } from "./layouts/ContextPanel.svelte";
export { default as InvestorShell } from "./layouts/InvestorShell.svelte";
export { default as PageHeader } from "./layouts/PageHeader.svelte";

// ── Charts ─────────────────────────────────────────────────
export {
	ChartContainer,
	TimeSeriesChart,
	RegimeChart,
	GaugeChart,
	BarChart,
	FunnelChart,
	HeatmapChart,
	ScatterChart,
} from "./charts/index.js";
export type { BaseChartProps } from "./charts/index.js";

// ── Utilities ───────────────────────────────────────────────
export { cn } from "./utils/cn.js";
export type { NavItem, BrandingConfig } from "./utils/types.js";
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
} from "./utils/api-client.js";
export { createSSEStream, createSSEWithSnapshot } from "./utils/sse-client.svelte.js";
export type { SSEConfig, SSEConnection, SSEStatus, SSEEvent, SSESnapshotConfig, SSESnapshotConnection } from "./utils/sse-client.svelte.js";
export {
	formatCurrency,
	formatPercent,
	formatCompact,
	formatDate,
	formatDateRange,
	formatISIN,
} from "./utils/format.js";
export {
	defaultBranding,
	brandingToCSS,
	injectBranding,
} from "./utils/branding.js";
export { createClerkHook, createRootLayoutLoader, startSessionExpiryMonitor } from "./utils/auth.js";
export type { ClerkHookOptions, RootLayoutLoaderOptions } from "./utils/auth.js";
