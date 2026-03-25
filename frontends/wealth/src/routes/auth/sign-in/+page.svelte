<script lang="ts">
	import { onMount } from "svelte";
	import { browser } from "$app/environment";
	import { page } from "$app/stores";

	function clerkDomain(pk: string): string {
		const encoded = pk.replace(/^pk_(test|live)_/, "");
		return atob(encoded).replace(/\$$/, "");
	}

	onMount(async () => {
		if (!browser) return;

		const CLERK_PK =
			import.meta.env.VITE_CLERK_PUBLISHABLE_KEY ??
			$page.data.clerkPublishableKey ??
			"";
		if (!CLERK_PK) return;

		const domain = clerkDomain(CLERK_PK);

		await new Promise<void>((resolve, reject) => {
			if (document.querySelector("script[data-clerk-script]")) {
				resolve();
				return;
			}
			const script = document.createElement("script");
			script.setAttribute("data-clerk-script", "");
			script.async = true;
			script.src = `https://${domain}/npm/@clerk/clerk-js@latest/dist/clerk.browser.js`;
			script.onload = () => resolve();
			script.onerror = () => reject(new Error("Failed to load Clerk"));
			document.head.appendChild(script);
		});

		const ClerkClass = (window as any).Clerk;
		if (!ClerkClass) return;

		let clerk: any;
		if (typeof ClerkClass.load === "function") {
			clerk = ClerkClass;
		} else {
			clerk = new ClerkClass(CLERK_PK);
		}
		await clerk.load({ routerPush: () => {}, routerReplace: () => {} });

		if (clerk.session) {
			const token = await clerk.session.getToken();
			if (token) {
				document.cookie = `__session=${token}; path=/; secure; samesite=lax`;
				window.location.href = "/";
				return;
			}
		}

		const el = document.getElementById("clerk-sign-in");
		if (el) {
			el.innerHTML = "";
			clerk.mountSignIn(el, {
				fallbackRedirectUrl: "/",
				afterSignInUrl: "/",
			});
		}

		clerk.addListener(({ session }: any) => {
			if (session) {
				session.getToken().then((t: string) => {
					if (t) document.cookie = `__session=${t}; path=/; secure; samesite=lax`;
				});
			}
		});
	});
</script>

<div class="clerk-shell">
	<div id="clerk-sign-in">
		<p class="clerk-loading">Loading authentication...</p>
	</div>
</div>

<style>
	.clerk-shell {
		display: flex;
		min-height: 100vh;
		align-items: center;
		justify-content: center;
		background: #0a0a0a;
	}

	.clerk-loading {
		color: #666;
		font-size: 14px;
	}
</style>
