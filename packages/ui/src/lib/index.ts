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
export { default as AlertBanner } from "./components/AlertBanner.svelte";

// ── Data Components ─────────────────────────────────────────
export { default as DataTable } from "./components/DataTable.svelte";
export { default as DataTableToolbar } from "./components/DataTableToolbar.svelte";

// ── Shared Mutation Components ──────────────────────────────
export { default as ConfirmDialog } from "./components/ConfirmDialog.svelte";
export { default as ActionButton } from "./components/ActionButton.svelte";
export { default as FormField } from "./components/FormField.svelte";
export { default as ConsequenceDialog } from "./components/ConsequenceDialog.svelte";
export type { ConsequenceDialogMetadataItem, ConsequenceDialogPayload } from "./components/ConsequenceDialog.svelte";
export { default as AuditTrailPanel } from "./components/AuditTrailPanel.svelte";
export type { AuditTrailEntry, AuditTrailStatus, AuditTrailFieldChange } from "./components/AuditTrailPanel.svelte";

// ── Netz Composites ─────────────────────────────────────────
export { default as DataCard } from "./components/DataCard.svelte";
export { default as StatusBadge } from "./components/StatusBadge.svelte";
export type { StatusConfig, StatusResolver, StatusSeverity } from "./components/StatusBadge.svelte";
export { default as EmptyState } from "./components/EmptyState.svelte";
export { default as PDFDownload } from "./components/PDFDownload.svelte";
export { default as ThemeToggle } from "./components/ThemeToggle.svelte";
export { default as LanguageToggle } from "./components/LanguageToggle.svelte";
export { default as ErrorBoundary } from "./components/ErrorBoundary.svelte";
export { default as ConnectionLost } from "./components/ConnectionLost.svelte";
export { default as BackendUnavailable } from "./components/BackendUnavailable.svelte";
export { default as Toast } from "./components/Toast.svelte";
export { default as PageTabs } from "./components/PageTabs.svelte";
export { default as MetricCard } from "./components/MetricCard.svelte";
export { default as UtilizationBar } from "./components/UtilizationBar.svelte";
export { default as RegimeBanner } from "./components/RegimeBanner.svelte";
export { default as AlertFeed } from "./components/AlertFeed.svelte";
export type { WealthAlert } from "./components/AlertFeed.svelte";
export { default as SectionCard } from "./components/SectionCard.svelte";
export { default as HeatmapTable } from "./components/HeatmapTable.svelte";
export { default as PeriodSelector } from "./components/PeriodSelector.svelte";
export { default as EntityContextHeader } from "./components/EntityContextHeader.svelte";
export { default as LongRunningAction } from "./components/LongRunningAction.svelte";

// ── Admin Components ────────────────────────────────────────
export { default as ConfigEditor } from "./components/admin/ConfigEditor.svelte";
export { default as ConfigDiffView } from "./components/admin/ConfigDiffView.svelte";
export type { ConfigDiffOut } from "./components/admin/ConfigDiffView.svelte";
export { default as ServiceHealthCard } from "./components/admin/ServiceHealthCard.svelte";
export { default as WorkerLogFeed } from "./components/admin/WorkerLogFeed.svelte";
export { default as CodeEditor } from "./components/admin/CodeEditor.svelte";
export { resolveAdminStatus } from "./utils/admin-status.js";

// ── Layouts ─────────────────────────────────────────────────
export { default as AppLayout } from "./layouts/AppLayout.svelte";
export { default as AppShell } from "./layouts/AppShell.svelte";
export { default as Sidebar } from "./layouts/Sidebar.svelte";
export { default as TopNav } from "./layouts/TopNav.svelte";
export { default as ContextSidebar } from "./layouts/ContextSidebar.svelte";
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
export type { NavItem, BrandingConfig, ContextNav } from "./utils/types.js";
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
export { createPoller } from "./utils/poller.svelte.js";
export type { PollerConfig, PollerState } from "./utils/poller.svelte.js";
export { createOptimisticMutation } from "./utils/optimistic.svelte.js";
export type { OptimisticMutation, OptimisticMutationConfig } from "./utils/optimistic.svelte.js";
export { canOpenSSE, registerSSE, unregisterSSE, getActiveSSECount } from "./utils/sse-registry.svelte.js";
export {
	formatAUM,
	formatBps,
	formatNAV,
	formatNumber,
	formatRatio,
	formatCurrency,
	formatPercent,
	formatCompact,
	formatDate,
	formatTime,
	formatDateTime,
	formatDateRange,
	formatRelativeDate,
	formatShortDate,
	formatISIN,
	plColor,
	plDirection,
} from "./utils/format.js";
export {
	defaultBranding,
	defaultDarkBranding,
	brandingToCSS,
	injectBranding,
	validateBrandingContrast,
} from "./utils/branding.js";
export type { ContrastViolation } from "./utils/branding.js";
export { createClerkHook, startSessionExpiryMonitor } from "./utils/auth.js";
export type { ClerkHookOptions } from "./utils/auth.js";
export { exportTableToCSV } from "./utils/table-export.js";
