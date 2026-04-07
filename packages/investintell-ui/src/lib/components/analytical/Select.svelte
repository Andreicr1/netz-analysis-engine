<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import * as SelectUI from "$lib/components/ui/select";

	interface Option {
		value: string;
		label: string;
	}

	interface Props {
		value?: string;
		onValueChange?: (value: string) => void;
		options: Option[];
		placeholder?: string;
		disabled?: boolean;
		searchable?: boolean;
		class?: string;
	}

	let {
		value = $bindable(""),
		onValueChange,
		options,
		placeholder = "Select...",
		disabled = false,
		searchable = false,
		class: className,
	}: Props = $props();

	let search = $state("");

	let filtered = $derived(
		searchable && search
			? options.filter((o) => o.label.toLowerCase().includes(search.toLowerCase()))
			: options,
	);

	let selectedLabel = $derived(
		options.find((o) => o.value === value)?.label ?? "",
	);

	function handleValueChange(v: string | undefined) {
		if (v !== undefined) {
			value = v;
			onValueChange?.(v);
		}
	}
</script>

<SelectUI.Root type="single" {value} onValueChange={handleValueChange} {disabled}>
	<SelectUI.Trigger class={cn("w-full", className)}>
		<span data-slot="select-value" class:text-muted-foreground={!value}>
			{value ? selectedLabel : placeholder}
		</span>
	</SelectUI.Trigger>
	<SelectUI.Content>
		{#if searchable}
			<div class="sticky top-0 z-10 border-b border-(--ii-border-subtle) bg-popover p-1.5">
				<!-- svelte-ignore a11y_autofocus -->
				<input
					bind:value={search}
					type="text"
					class="w-full rounded-md border border-input bg-transparent px-2.5 py-1.5 text-sm outline-none placeholder:text-muted-foreground focus:border-ring"
					placeholder="Search..."
					autocomplete="off"
					autofocus
					onclick={(e) => e.stopPropagation()}
					onkeydown={(e) => e.stopPropagation()}
				/>
			</div>
		{/if}
		{#if filtered.length === 0}
			<div class="py-3 text-center text-sm text-muted-foreground">No results</div>
		{:else}
			{#each filtered as opt (opt.value)}
				<SelectUI.Item value={opt.value} label={opt.label} />
			{/each}
		{/if}
	</SelectUI.Content>
</SelectUI.Root>
