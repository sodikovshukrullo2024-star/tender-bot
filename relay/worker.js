// Cloudflare Worker: relays Telegram Bot API calls for tender-bot.
// URL format: https://<worker>.workers.dev/<KEY>/bot<TOKEN>/<method>
const KEY = "6708e89b3e95f5b7";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const prefix = "/" + KEY + "/bot";
    if (!url.pathname.startsWith(prefix)) {
      return new Response("Not found", { status: 404 });
    }
    const target = "https://api.telegram.org" + url.pathname.slice(KEY.length + 1) + url.search;
    const init = { method: request.method, headers: { "content-type": request.headers.get("content-type") || "application/x-www-form-urlencoded" } };
    if (request.method !== "GET" && request.method !== "HEAD") init.body = await request.arrayBuffer();
    const resp = await fetch(target, init);
    return new Response(resp.body, { status: resp.status, headers: { "content-type": "application/json" } });
  },
};
