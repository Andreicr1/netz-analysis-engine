/**
 * Netz API Gateway — Cloudflare Worker
 *
 * Proxies all requests to the backend container.
 * Blocks /internal/* unless caller presents X-Worker-Secret.
 * Preserves JWT auth headers and SSE streaming.
 */

interface Env {
  BACKEND_ORIGIN: string;
  WORKER_SECRET: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Block /internal/* — only Cron Workers with shared secret
    if (url.pathname.startsWith("/internal/")) {
      const secret = request.headers.get("X-Worker-Secret");
      if (!env.WORKER_SECRET || secret !== env.WORKER_SECRET) {
        return new Response("Forbidden", { status: 403 });
      }
    }

    // Proxy to backend container — preserve all headers (Clerk JWT, SSE)
    const backendUrl = new URL(
      url.pathname + url.search,
      env.BACKEND_ORIGIN,
    );

    const backendReq = new Request(backendUrl.toString(), {
      method: request.method,
      headers: request.headers,
      body: request.body,
      redirect: "follow",
    });

    const response = await fetch(backendReq);

    // SSE: strip Content-Length and enforce no-cache for streaming
    const headers = new Headers(response.headers);
    if (headers.get("content-type")?.includes("text/event-stream")) {
      headers.set("Cache-Control", "no-cache");
      headers.delete("Content-Length");
    }

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
