// shadcn-svelte utility module — imported by all generated UI components as "$lib/utils.js"

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge Tailwind classes with conflict resolution. */
export function cn(...inputs: ClassValue[]): string {
	return twMerge(clsx(inputs));
}

// ── shadcn-svelte helper types ──────────────────────────────
// Re-export from bits-ui to keep the contract identical

export type {
	WithElementRef,
	WithoutChild,
	WithoutChildren,
	WithoutChildrenOrChild,
} from "bits-ui";
