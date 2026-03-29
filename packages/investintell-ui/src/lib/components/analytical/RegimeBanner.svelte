<script lang="ts">
	import { cn } from "../../utils/cn.js";

	interface Signal {
		label: string;
		value: string;
	}

	interface Props {
		regime: string | null;
		duration?: string;
		signals?: Signal[];
		macroHref?: string;
		class?: string;
	}

	let { regime, duration, signals, macroHref, class: className }: Props = $props();

	type RegimeTone = "warning" | "danger" | "highlight";

	const regimeTone: Record<string, RegimeTone> = {
		RISK_OFF: "warning",
		CRISIS: "danger",
		INFLATION: "highlight",
	};

	const toneStyles: Record<RegimeTone, { bg: string; text: string; chip: string; link: string }> = {
		warning: {
			bg: "var(--ii-warning)",
			text: "#7c2d12",
			chip: "rgba(0,0,0,0.12)",
			link: "#78350f",
		},
		danger: {
			bg: "var(--ii-danger)",
			text: "#ffffff",
			chip: "rgba(255,255,255,0.2)",
			link: "#fee2e2",
		},
		highlight: {
			bg: "var(--ii-brand-accent)",
			text: "#1c1917",
			chip: "rgba(0,0,0,0.12)",
			link: "#431407",
		},
	};

	const visible = $derived(
		regime !== null && regime !== "RISK_ON" && regime in regimeTone,
	);
	const tone = $derived<RegimeTone | null>(regime ? (regimeTone[regime] ?? null) : null);
	const styles = $derived(tone ? toneStyles[tone] : null);
</script>

{#if visible && styles}
	<div
		class={cn("w-full px-4 py-2.5", className)}
		style="background-color: {styles.bg};"
		role="alert"
		aria-live="polite"
	>
		<div class="mx-auto flex max-w-screen-2xl flex-wrap items-center gap-x-4 gap-y-1.5">
			<!-- Regime label + duration -->
			<div class="flex items-center gap-2">
				<span
					class="text-xs font-bold uppercase tracking-widest"
					style="color: {styles.text};"
				>
					{regime}
				</span>
				{#if duration}
					<span class="text-xs font-medium" style="color: {styles.text}; opacity: 0.75;">
						{duration}
					</span>
				{/if}
			</div>

			<!-- Signal chips -->
			{#if signals && signals.length > 0}
				<div class="flex flex-wrap items-center gap-1.5">
					{#each signals as sig (sig.label)}
						<span
							class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
							style="background-color: {styles.chip}; color: {styles.text};"
						>
							<span class="opacity-75">{sig.label}</span>
							<span class="font-semibold">{sig.value}</span>
						</span>
					{/each}
				</div>
			{/if}

			<!-- Macro detail link -->
			{#if macroHref}
				<a
					href={macroHref}
					class="ml-auto text-xs font-medium underline underline-offset-2 hover:opacity-80"
					style="color: {styles.link};"
				>
					Ver análise macro →
				</a>
			{/if}
		</div>
	</div>
{/if}
