/**
 * Netz Workers Container — Cloudflare Containers entrypoint.
 *
 * Same FastAPI image as backend, but scale-to-zero (sleeps after 30m idle).
 * Woken by Cron Worker POST to /internal/workers/dispatch.
 */

import { Container } from "@cloudflare/containers";

interface Env {
	WORKERS_CONTAINER: DurableObjectNamespace<NetzWorkers>;
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
	// Vars
	APP_ENV: string;
	FEATURE_R2_ENABLED: string;
	R2_ACCOUNT_ID: string;
	NETZ_WORKER_MODE: string;
}

export class NetzWorkers extends Container<Env> {
	defaultPort = 8000;
	sleepAfter = "30m";

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
			NETZ_WORKER_MODE: env.NETZ_WORKER_MODE ?? "true",
		};
	}
}

export default {
	async fetch(request: Request, env: Env): Promise<Response> {
		const id = env.WORKERS_CONTAINER.idFromName("default");
		const stub = env.WORKERS_CONTAINER.get(id);
		return stub.fetch(request);
	},
};
