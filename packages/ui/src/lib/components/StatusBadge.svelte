<script lang="ts">
	import { cn } from "../utils/cn.js";

	export type StatusSeverity = "neutral" | "info" | "success" | "warning" | "danger";

	export interface StatusConfig {
		label: string;
		severity: StatusSeverity;
		color: string;
	}

	export type StatusResolver = (token: string) => StatusConfig | undefined;

	interface Props {
		status: string;
		type?: string;
		label?: string;
		resolve?: StatusResolver;
		class?: string;
	}

	let { status, type = "default", label, resolve, class: className }: Props = $props();

	const severityColorMap: Record<StatusSeverity, string> = {
		neutral: "var(--netz-text-secondary)",
		info: "var(--netz-info)",
		success: "var(--netz-success)",
		warning: "var(--netz-warning)",
		danger: "var(--netz-danger)",
	};

	const successTokens = new Set([
		"approved",
		"completed",
		"healthy",
		"ok",
		"pass",
		"published",
		"ready",
		"resolved",
		"success",
	]);
	const warningTokens = new Set(["pending", "warning", "warn"]);
	const dangerTokens = new Set(["critical", "declined", "danger", "error", "failed", "rejected"]);
	const infoTokens = new Set(["active", "generated", "in_progress", "info", "processing", "running"]);

	/** Tokens that are intentionally neutral — suppress dev warning for these. */
	const NEUTRAL_STATUSES = new Set([
		"inactive",
		"archived",
		"draft",
		"unknown",
		"none",
		"default",
		"neutral",
		"n/a",
		"na",
		"cancelled",
		"closed",
		"expired",
		"paused",
		"suspended",
		"disabled",
	]);

	function formatLabel(value: string): string {
		if (!value) {
			return "Unknown";
		}

		return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
	}

	function inferSeverity(token: string): StatusSeverity {
		const normalizedToken = token.trim().toLowerCase();

		if (dangerTokens.has(normalizedToken)) {
			return "danger";
		}

		if (warningTokens.has(normalizedToken)) {
			return "warning";
		}

		if (successTokens.has(normalizedToken)) {
			return "success";
		}

		if (infoTokens.has(normalizedToken)) {
			return "info";
		}

		if (import.meta.env.DEV && !NEUTRAL_STATUSES.has(normalizedToken)) {
			console.warn(`StatusBadge: unrecognized status "${token}"`);
		}

		return "neutral";
	}

	let fallbackConfig = $derived.by<StatusConfig>(() => {
		const resolvedLabel = label ?? formatLabel(status);
		const severity = inferSeverity(status);

		return {
			label: resolvedLabel,
			severity,
			color: severityColorMap[severity],
		};
	});

	let config = $derived.by<StatusConfig>(() => resolve?.(status) ?? fallbackConfig);
	let badgeColor = $derived(config.color || severityColorMap[config.severity]);

	/** In dev mode, flag unrecognized tokens (those that triggered the neutral fallback via inferSeverity) with a dashed border. */
	let isDevUnknown = $derived.by(() => {
		if (!import.meta.env.DEV) return false;
		// Only flag when using the fallback (no custom resolver) and severity resolved to neutral
		if (resolve) return false;
		const normalizedToken = status.trim().toLowerCase();
		const known =
			successTokens.has(normalizedToken) ||
			warningTokens.has(normalizedToken) ||
			dangerTokens.has(normalizedToken) ||
			infoTokens.has(normalizedToken) ||
			NEUTRAL_STATUSES.has(normalizedToken);
		return !known;
	});
</script>

<span
	class={cn(
		"inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
		isDevUnknown && "dev-unknown",
		className,
	)}
	data-status-type={type}
	data-status-severity={config.severity}
	style={`background-color: color-mix(in srgb, ${badgeColor} 14%, transparent); color: ${badgeColor};${isDevUnknown ? " border: 1px dashed currentColor;" : ""}`}
>
	<span class="h-1.5 w-1.5 rounded-full" style={`background-color: ${badgeColor};`}></span>
	{config.label}
</span>
