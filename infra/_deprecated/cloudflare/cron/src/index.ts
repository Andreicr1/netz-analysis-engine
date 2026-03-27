/**
 * Netz Cron Worker — Cloudflare Scheduled Worker
 *
 * Dispatches background workers via POST to the workers container.
 * Each cron expression maps to a group of workers to run together.
 * The workers container handles idempotency, timeouts, and advisory locks.
 */

interface Env {
  WORKERS_ORIGIN: string;
  WORKER_SECRET: string;
}

const SCHEDULE_MAP: Record<string, string[]> = {
  "0 6 * * *": ["macro_ingestion", "benchmark_ingest", "treasury_ingestion"],
  "30 6 * * *": ["ingestion", "instrument_ingestion"],
  "0 7 * * *": ["risk_calc"],
  "30 7 * * *": ["portfolio_eval", "drift_check", "regime_fit"],
  "0 8 * * *": ["screening_batch", "watchlist_batch"],
  "0 8 * * 1": ["ofr_ingestion"],
  "0 5 1 */3 *": [
    "sec_refresh",
    "nport_ingestion",
    "bis_ingestion",
    "imf_ingestion",
  ],
};

export default {
  async scheduled(
    event: ScheduledEvent,
    env: Env,
    ctx: ExecutionContext,
  ): Promise<void> {
    const workers = SCHEDULE_MAP[event.cron];
    if (!workers) {
      console.log(`No workers mapped for cron: ${event.cron}`);
      return;
    }

    console.log(`Dispatching workers for cron ${event.cron}: ${workers.join(", ")}`);

    const response = await fetch(
      `${env.WORKERS_ORIGIN}/internal/workers/dispatch`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Worker-Secret": env.WORKER_SECRET,
        },
        body: JSON.stringify({ workers }),
      },
    );

    if (!response.ok) {
      const body = await response.text();
      console.error(`Dispatch failed (${response.status}): ${body}`);
    } else {
      const result = await response.json();
      console.log(`Dispatch result:`, JSON.stringify(result));
    }
  },
};
