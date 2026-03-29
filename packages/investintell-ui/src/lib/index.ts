// @investintell/ui — InvestIntell Design System
// ===============================================
// Barrel export for analytical, layout, chart, and utility modules.
//
// shadcn-svelte components are NOT re-exported here to avoid name collisions
// (Root, Content, Trigger etc. are generic across many components).
// Import them directly from their paths:
//   import { Button } from "@investintell/ui/components/ui/button";
//   import * as Dialog from "@investintell/ui/components/ui/dialog";

// ── Analytical Components ────────────────────────────────────
export { default as MetricCard } from "./components/analytical/MetricCard.svelte";
export { default as UtilizationBar } from "./components/analytical/UtilizationBar.svelte";
export { default as RegimeBanner } from "./components/analytical/RegimeBanner.svelte";
export { default as StatusBadge } from "./components/analytical/StatusBadge.svelte";
export type { StatusConfig, StatusResolver, StatusSeverity } from "./components/analytical/StatusBadge.svelte";
export { default as AlertFeed } from "./components/analytical/AlertFeed.svelte";
export type { WealthAlert } from "./components/analytical/AlertFeed.svelte";
export { default as ServiceHealthCard } from "./components/analytical/ServiceHealthCard.svelte";
export { default as WorkerLogFeed } from "./components/analytical/WorkerLogFeed.svelte";
export { default as HeatmapTable } from "./components/analytical/HeatmapTable.svelte";
export { default as SectionCard } from "./components/analytical/SectionCard.svelte";
export { default as DataCard } from "./components/analytical/DataCard.svelte";
export { default as EmptyState } from "./components/analytical/EmptyState.svelte";
export { default as PeriodSelector } from "./components/analytical/PeriodSelector.svelte";
export { default as EntityContextHeader } from "./components/analytical/EntityContextHeader.svelte";
export { default as LongRunningAction } from "./components/analytical/LongRunningAction.svelte";
export { default as PDFDownload } from "./components/analytical/PDFDownload.svelte";
export { default as ThemeToggle } from "./components/analytical/ThemeToggle.svelte";
export { default as LanguageToggle } from "./components/analytical/LanguageToggle.svelte";
export { default as ErrorBoundary } from "./components/analytical/ErrorBoundary.svelte";
export { default as ConnectionLost } from "./components/analytical/ConnectionLost.svelte";
export { default as BackendUnavailable } from "./components/analytical/BackendUnavailable.svelte";
export { default as Toast } from "./components/analytical/Toast.svelte";
export { default as PageTabs } from "./components/analytical/PageTabs.svelte";
export { default as ConfirmDialog } from "./components/analytical/ConfirmDialog.svelte";
export { default as ActionButton } from "./components/analytical/ActionButton.svelte";
export { default as FormField } from "./components/analytical/FormField.svelte";
export { default as ConsequenceDialog } from "./components/analytical/ConsequenceDialog.svelte";
export type { ConsequenceDialogMetadataItem, ConsequenceDialogPayload } from "./components/analytical/ConsequenceDialog.svelte";
export { default as AuditTrailPanel } from "./components/analytical/AuditTrailPanel.svelte";
export type { AuditTrailEntry, AuditTrailStatus, AuditTrailFieldChange } from "./components/analytical/AuditTrailPanel.svelte";
export { default as AlertBanner } from "./components/analytical/AlertBanner.svelte";
export { default as DataTable } from "./components/analytical/DataTable.svelte";
export { default as DataTableToolbar } from "./components/analytical/DataTableToolbar.svelte";

// ── Admin Components ─────────────────────────────────────────
export { default as ConfigEditor } from "./components/analytical/ConfigEditor.svelte";
export { default as ConfigDiffView } from "./components/analytical/ConfigDiffView.svelte";
export type { ConfigDiffOut } from "./components/analytical/ConfigDiffView.svelte";
export { default as CodeEditor } from "./components/analytical/CodeEditor.svelte";
export { resolveAdminStatus } from "./utils/admin-status.js";

// ── Layouts ──────────────────────────────────────────────────
export { default as AppLayout } from "./components/layouts/AppLayout.svelte";
export { default as AppShell } from "./components/layouts/AppShell.svelte";
export { default as Sidebar } from "./components/layouts/Sidebar.svelte";
export { default as TopNav } from "./components/layouts/TopNav.svelte";
export { default as ContextSidebar } from "./components/layouts/ContextSidebar.svelte";
export { default as ContextPanel } from "./components/layouts/ContextPanel.svelte";
export { default as InvestorShell } from "./components/layouts/InvestorShell.svelte";
export { default as PageHeader } from "./components/layouts/PageHeader.svelte";

// ── Charts ───────────────────────────────────────────────────
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

// ── Utilities ────────────────────────────────────────────────
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
