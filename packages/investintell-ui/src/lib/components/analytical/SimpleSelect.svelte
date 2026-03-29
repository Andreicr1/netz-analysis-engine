<!--
  SimpleSelect — thin wrapper around shadcn Select providing the legacy simple API:
  <SimpleSelect value="10" onValueChange={fn} options={[{value, label}]} />
  Used by DataTable pagination. For new code, prefer the shadcn Select compound components directly.
-->
<script lang="ts">
	import * as Select from "$lib/components/ui/select";

	interface SelectOption {
		value: string;
		label: string;
	}

	let {
		value,
		onValueChange,
		options,
		class: className,
	}: {
		value: string;
		onValueChange: (value: string) => void;
		options: SelectOption[];
		class?: string;
	} = $props();

	function handleValueChange(v: string | undefined) {
		if (v !== undefined) {
			onValueChange(v);
		}
	}
</script>

<Select.Root type="single" {value} onValueChange={handleValueChange}>
	<Select.Trigger class={className}>
		{options.find((o) => o.value === value)?.label ?? value}
	</Select.Trigger>
	<Select.Content>
		{#each options as option (option.value)}
			<Select.Item value={option.value} label={option.label} />
		{/each}
	</Select.Content>
</Select.Root>
