<!--
  Combobox — searchable select using Command + Popover (shadcn composite pattern).
  For simple selects without search, use Select instead.
-->
<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import * as Popover from "$lib/components/ui/popover";
	import * as Command from "$lib/components/ui/command";
	import { Button } from "$lib/components/ui/button";
	import { Check, ChevronsUpDown } from "lucide-svelte";

	interface ComboboxItem {
		value: string;
		label: string;
		disabled?: boolean;
	}

	interface ComboboxGroup {
		heading?: string;
		items: ComboboxItem[];
	}

	interface Props {
		value?: string;
		onValueChange?: (value: string) => void;
		items?: ComboboxItem[];
		groups?: ComboboxGroup[];
		placeholder?: string;
		searchPlaceholder?: string;
		emptyMessage?: string;
		disabled?: boolean;
		class?: string;
	}

	let {
		value = $bindable(""),
		onValueChange,
		items,
		groups,
		placeholder = "Select…",
		searchPlaceholder = "Search…",
		emptyMessage = "No results found.",
		disabled = false,
		class: className,
	}: Props = $props();

	let open = $state(false);

	// Resolve all items (flat or grouped) for label lookup
	let allItems = $derived(
		items ?? groups?.flatMap((g) => g.items) ?? [],
	);

	let selectedLabel = $derived(
		allItems.find((i) => i.value === value)?.label ?? "",
	);

	function handleSelect(itemValue: string) {
		const newValue = itemValue === value ? "" : itemValue;
		value = newValue;
		onValueChange?.(newValue);
		open = false;
	}
</script>

<Popover.Root bind:open>
	<Popover.Trigger {disabled}>
		{#snippet child({ props })}
			<Button
				{...props}
				variant="outline"
				role="combobox"
				aria-expanded={open}
				class={cn("w-full justify-between font-normal", !value && "text-muted-foreground", className)}
			>
				<span class="truncate">{value ? selectedLabel : placeholder}</span>
				<ChevronsUpDown class="ml-auto size-4 shrink-0 opacity-50" />
			</Button>
		{/snippet}
	</Popover.Trigger>
	<Popover.Content class="w-(--radix-popover-trigger-width) p-0" align="start">
		<Command.Root shouldFilter={true}>
			<Command.Input placeholder={searchPlaceholder} />
			<Command.List>
				<Command.Empty>{emptyMessage}</Command.Empty>
				{#if groups}
					{#each groups as group (group.heading ?? "")}
						<Command.Group heading={group.heading}>
							{#each group.items as item (item.value)}
								<Command.Item
									value={item.value}
									keywords={[item.label]}
									disabled={item.disabled}
									onSelect={() => handleSelect(item.value)}
								>
									<Check class={cn("mr-2 size-4", value === item.value ? "opacity-100" : "opacity-0")} />
									{item.label}
								</Command.Item>
							{/each}
						</Command.Group>
					{/each}
				{:else if items}
					{#each items as item (item.value)}
						<Command.Item
							value={item.value}
							keywords={[item.label]}
							disabled={item.disabled}
							onSelect={() => handleSelect(item.value)}
						>
							<Check class={cn("mr-2 size-4", value === item.value ? "opacity-100" : "opacity-0")} />
							{item.label}
						</Command.Item>
					{/each}
				{/if}
			</Command.List>
		</Command.Root>
	</Popover.Content>
</Popover.Root>
