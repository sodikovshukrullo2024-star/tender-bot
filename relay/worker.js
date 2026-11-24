// Cloudflare Worker for tender-bot:
//  1) relays Telegram Bot API calls (GitHub's servers are blocked by Telegram)
//  2) every 30 minutes, tells GitHub to run the bot (GitHub's own timer is unreliable)
const KEY = "6708e89b3e95f5b7";
const REPO = "sodikovshukrullo2024-star/tender-bot";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/" + KEY + "/bot")) return new Response("Not found", { status: 404 });
    const target = "https://api.telegram.org" + url.pathname.slice(KEY.length + 1) + url.search;
    const init = { method: request.method, headers: { "content-type": request.headers.get("content-type") || "application/x-www-form-urlencoded" } };
    if (request.method !== "GET" && request.method !== "HEAD") init.body = await request.arrayBuffer();
    const resp = await fetch(target, init);
    return new Response(resp.body, { status: resp.status, headers: { "content-type": "application/json" } });
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(fetch(`https://api.github.com/repos/${REPO}/actions/workflows/check.yml/dispatches`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "tender-relay",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main" }),
    }).then(r => console.log("GitHub dispatch:", r.status)));
  },
};
