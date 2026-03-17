/// <reference types="@sveltejs/kit" />

import type { Actor } from "@netz/ui/utils";

declare global {
	namespace App {
		interface Locals {
			actor: Actor;
			token: string;
		}
	}
}

export {};
