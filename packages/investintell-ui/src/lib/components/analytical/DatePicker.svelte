<!--
  DatePicker — Calendar inside Popover with Button trigger (shadcn composite pattern).
  Accepts/emits ISO date strings (YYYY-MM-DD) for easy form binding.
-->
<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import * as Popover from "$lib/components/ui/popover";
	import { Calendar } from "$lib/components/ui/calendar";
	import { Button } from "$lib/components/ui/button";
	import { CalendarIcon } from "lucide-svelte";
	import {
		CalendarDate,
		type DateValue,
		getLocalTimeZone,
		today,
	} from "@internationalized/date";

	interface Props {
		/** ISO date string (YYYY-MM-DD) */
		value?: string;
		onValueChange?: (value: string) => void;
		placeholder?: string;
		disabled?: boolean;
		/** Minimum selectable date (ISO string) */
		minValue?: string;
		/** Maximum selectable date (ISO string) */
		maxValue?: string;
		class?: string;
	}

	let {
		value = $bindable(""),
		onValueChange,
		placeholder = "Pick a date",
		disabled = false,
		minValue,
		maxValue,
		class: className,
	}: Props = $props();

	let open = $state(false);

	function parseISO(iso: string): CalendarDate | undefined {
		if (!iso) return undefined;
		const [y, m, d] = iso.split("-").map(Number);
		if (!y || !m || !d) return undefined;
		return new CalendarDate(y, m, d);
	}

	function toISO(date: DateValue): string {
		return `${String(date.year).padStart(4, "0")}-${String(date.month).padStart(2, "0")}-${String(date.day).padStart(2, "0")}`;
	}

	let calendarValue = $derived(parseISO(value));
	let minDateValue = $derived(minValue ? parseISO(minValue) : undefined);
	let maxDateValue = $derived(maxValue ? parseISO(maxValue) : undefined);

	let displayValue = $derived(
		value
			? new Date(value + "T00:00:00").toLocaleDateString("en-US", {
					year: "numeric",
					month: "short",
					day: "numeric",
				})
			: "",
	);

	function handleSelect(date: DateValue | undefined) {
		if (!date) return;
		const iso = toISO(date);
		value = iso;
		onValueChange?.(iso);
		open = false;
	}
</script>

<Popover.Root bind:open>
	<Popover.Trigger {disabled}>
		{#snippet child({ props })}
			<Button
				{...props}
				variant="outline"
				class={cn(
					"w-full justify-start text-left font-normal",
					!value && "text-muted-foreground",
					className,
				)}
			>
				<CalendarIcon class="mr-2 size-4" />
				{value ? displayValue : placeholder}
			</Button>
		{/snippet}
	</Popover.Trigger>
	<Popover.Content class="w-auto p-0" align="start">
		<Calendar
			value={calendarValue}
			onValueChange={handleSelect}
			minValue={minDateValue}
			maxValue={maxDateValue}
			captionLayout="dropdown"
			placeholder={calendarValue ?? today(getLocalTimeZone())}
		/>
	</Popover.Content>
</Popover.Root>
