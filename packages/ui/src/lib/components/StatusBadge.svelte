<script lang="ts">
	import { cn } from "../utils/cn.js";

	type StatusType = "deal_stage" | "regime" | "risk" | "review" | "content";

	interface Props {
		status: string;
		type?: StatusType;
		class?: string;
	}

	let { status, type = "risk", class: className }: Props = $props();

	const colorMaps: Record<StatusType, Record<string, string>> = {
		deal_stage: {
			screening: "#94A3B8",
			qualified: "#3B82F6",
			ic_review: "#8B5CF6",
			approved: "#10B981",
			declined: "#EF4444",
		},
		regime: {
			RISK_ON: "#10B981",
			RISK_OFF: "#F59E0B",
			INFLATION: "#F97316",
			CRISIS: "#EF4444",
		},
		risk: {
			low: "#10B981",
			medium: "#F59E0B",
			high: "#EF4444",
			critical: "#991B1B",
		},
		review: {
			pending: "#94A3B8",
			in_progress: "#3B82F6",
			approved: "#10B981",
			rejected: "#EF4444",
		},
		content: {
			draft: "#94A3B8",
			generated: "#3B82F6",
			approved: "#10B981",
			published: "#059669",
		},
	};

	let color = $derived(colorMaps[type]?.[status] ?? "#94A3B8");

	/** Format label: replace underscores, capitalize first letter */
	function formatLabel(s: string): string {
		return s
			.replace(/_/g, " ")
			.replace(/\b\w/g, (c) => c.toUpperCase());
	}
</script>

<span
	class={cn(
		"inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
		className,
	)}
	style="background-color: {color}20; color: {color};"
>
	<span
		class="h-1.5 w-1.5 rounded-full"
		style="background-color: {color};"
	></span>
	{formatLabel(status)}
</span>
