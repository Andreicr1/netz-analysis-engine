/// <reference types="@sveltejs/kit" />

import type { Actor } from "./hooks.server";

declare global {
	namespace App {
		interface Locals {
			actor: Actor;
			token: string;
		}
	}
}

export {};
