<!--
  FlashNumber — NYSE-style pulse wrapper for any live numeric value.

  Detects up/down transitions on `value` and flashes the background
  for ~600ms (neon green on rise, neon red on fall). The container is
  inline so it drops into any `<td>` / `<span>` without breaking
  layout. Wraps a snippet so the caller controls formatting and
  keeps `tabular-nums` discipline.

  Stable across tick-buffer flushes: when the parent `#each` block is
  keyed (e.g. by ticker), this component's `prev` survives re-renders
  and only animates on genuine value changes — not on list reorders.
-->
<script lang="ts">
	interface Props {
		value: number | null | undefined;
		children: import("svelte").Snippet;
		/** Disable the flash effect (e.g. while loading skeletons). */
		disabled?: boolean;
	}

	let { value, children, disabled = false }: Props = $props();

	// prev is seeded from inside the effect on first run so the linter
	// doesn't flag the top-level `value` read as "only captures initial".
	let prev = $state<number | null>(null);
	let seeded = false;
	let flash = $state<"up" | "down" | null>(null);
	let timer: ReturnType<typeof setTimeout> | null = null;

	$effect(() => {
		if (disabled) return;
		const current = value ?? null;
		if (!seeded) {
			prev = current;
			seeded = true;
			return;
		}
		if (current === null || prev === null) {
			prev = current;
			return;
		}
		if (current !== prev) {
			flash = current > prev ? "up" : "down";
			prev = current;
			if (timer) clearTimeout(timer);
			timer = setTimeout(() => {
				flash = null;
				timer = null;
			}, 600);
		}
		return () => {
			if (timer) {
				clearTimeout(timer);
				timer = null;
			}
		};
	});
</script>

<span
	class="flash-wrap"
	class:flash-up={flash === "up"}
	class:flash-down={flash === "down"}
>
	{@render children()}
</span>

<style>
	.flash-wrap {
		display: inline-block;
		border-radius: 3px;
		padding: 0 3px;
		margin: 0 -3px;
		transition:
			background-color 140ms ease-out,
			box-shadow 140ms ease-out,
			color 140ms ease-out;
		will-change: background-color, box-shadow;
	}

	.flash-up {
		animation: flash-up 600ms ease-out forwards;
	}

	.flash-down {
		animation: flash-down 600ms ease-out forwards;
	}

	@keyframes flash-up {
		0% {
			background-color: rgba(17, 236, 121, 0.38);
			box-shadow: 0 0 14px rgba(17, 236, 121, 0.55);
		}
		60% {
			background-color: rgba(17, 236, 121, 0.18);
			box-shadow: 0 0 6px rgba(17, 236, 121, 0.25);
		}
		100% {
			background-color: transparent;
			box-shadow: 0 0 0 transparent;
		}
	}

	@keyframes flash-down {
		0% {
			background-color: rgba(252, 26, 26, 0.38);
			box-shadow: 0 0 14px rgba(252, 26, 26, 0.55);
		}
		60% {
			background-color: rgba(252, 26, 26, 0.18);
			box-shadow: 0 0 6px rgba(252, 26, 26, 0.25);
		}
		100% {
			background-color: transparent;
			box-shadow: 0 0 0 transparent;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.flash-up,
		.flash-down {
			animation: none;
		}
	}
</style>
