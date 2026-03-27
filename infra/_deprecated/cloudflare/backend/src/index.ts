/**
 * Netz Backend Container — Cloudflare Containers entrypoint.
 *
 * Extends Container to run the FastAPI backend as a Durable Object.
 * The gateway worker proxies requests to this container.
 * Secrets are forwarded from Worker secrets to container env vars.
 */

import { Container } from "@cloudflare/containers";

interface Env {
	BACKEND_CONTAINER: DurableObjectNamespace<NetzBackend>;
	// Worker secrets — forwarded to container as env vars
	DATABASE_URL: string;
	REDIS_URL: string;
	OPENAI_API_KEY: string;
	MISTRAL_API_KEY: string;
	CLERK_SECRET_KEY: string;
	CLERK_JWKS_URL: string;
	R2_ACCESS_KEY_ID: string;
	R2_SECRET_ACCESS_KEY: string;
	R2_BUCKET_NAME: string;
	WORKER_DISPATCH_SECRET: string;
	FRED_API_KEY: string;
	EDGAR_IDENTITY: string;
	// Vars (non-secret, from wrangler.toml)
	APP_ENV: string;
	FEATURE_R2_ENABLED: string;
	R2_ACCOUNT_ID: string;
}

export class NetzBackend extends Container<Env> {
	defaultPort = 8000;

	override getContainerEnv(env: Env): Record<string, string> {
		return {
			DATABASE_URL: env.DATABASE_URL,
			REDIS_URL: env.REDIS_URL,
			OPENAI_API_KEY: env.OPENAI_API_KEY,
			MISTRAL_API_KEY: env.MISTRAL_API_KEY,
			CLERK_SECRET_KEY: env.CLERK_SECRET_KEY,
			CLERK_JWKS_URL: env.CLERK_JWKS_URL,
			R2_ACCESS_KEY_ID: env.R2_ACCESS_KEY_ID,
			R2_SECRET_ACCESS_KEY: env.R2_SECRET_ACCESS_KEY,
			R2_BUCKET_NAME: env.R2_BUCKET_NAME,
			R2_ACCOUNT_ID: env.R2_ACCOUNT_ID ?? "",
			WORKER_DISPATCH_SECRET: env.WORKER_DISPATCH_SECRET,
			FRED_API_KEY: env.FRED_API_KEY,
			EDGAR_IDENTITY: env.EDGAR_IDENTITY ?? "Netz Analysis Engine tech@netzco.com",
			APP_ENV: env.APP_ENV ?? "production",
			FEATURE_R2_ENABLED: env.FEATURE_R2_ENABLED ?? "true",
		};
	}
}

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const id = env.BACKEND_CONTAINER.idFromName("default");
		const stub = env.BACKEND_CONTAINER.get(id);
		return stub.fetch(request);
	},
};
