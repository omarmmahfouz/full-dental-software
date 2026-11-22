// The online demo: Cloudflare runs the system in one container (deploy/online/Dockerfile) and this Worker passes
// every page to it. The container sleeps after IDLE_MS without a page and wakes at the next one (a few seconds; the
// very first start fills the sample data and takes a few minutes, with a "starting" page that refreshes itself).
import { DurableObject } from "cloudflare:workers";

const PORT = 8000;
const IDLE_MS = 2 * 60 * 60 * 1000; // stays awake 2 hours after the last page

// What the container gets from the Worker's settings (vars in wrangler.jsonc, secrets with `wrangler secret put`).
const PASSED = [
	"DJANGO_SECRET_KEY", "DB_PASSWORD", "DEMO_PASSWORD",
	"DB_ENGINE", "DB_NAME", "DB_USER", "DB_HOSTS", "DB_PORT",
	"DJANGO_ALLOWED_HOSTS", "DJANGO_CSRF_TRUSTED_ORIGINS", "DJANGO_HTTPS", "DJANGO_SSL_REDIRECT",
	"ALLOWED_NETWORKS", "TRUSTED_PROXIES", "WEB_WORKERS", "WEB_THREADS",
];

export class DentalApp extends DurableObject {
	constructor(ctx, env) {
		super(ctx, env);
		const container = ctx.container;
		if (container?.running) {
			void ctx.blockConcurrencyWhile(() => container.setInactivityTimeout(IDLE_MS));
		}
	}

	async fetch(request) {
		const container = this.ctx.container;
		if (!container.running) {
			const env = {};
			for (const name of PASSED) {
				if (this.env[name] !== undefined) env[name] = String(this.env[name]);
			}
			container.start({ enableInternet: true, env });
		}
		await container.setInactivityTimeout(IDLE_MS);

		// The page keeps its address (the system checks it), and the system learns the visitor's own address.
		const url = new URL(request.url);
		url.protocol = "http:";
		const forwarded = new Request(url, request);
		forwarded.headers.set("X-Forwarded-Proto", "https");
		forwarded.headers.set("X-Forwarded-Host", new URL(request.url).host);
		const visitor = request.headers.get("CF-Connecting-IP");
		if (visitor) forwarded.headers.set("X-Real-IP", visitor);

		try {
			return await container.getTcpPort(PORT).fetch(forwarded);
		} catch (error) {
			// The system is still starting (or has just been updated): a short page that tries again by itself.
			return starting();
		}
	}
}

function starting() {
	const html = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="5">
<title>Starting…</title><style>
body{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#f4f6f8;color:#1d2a36}
main{text-align:center;padding:24px;max-width:420px}.dot{width:42px;height:42px;border-radius:50%;margin:0 auto 18px;
border:4px solid #cfd8e0;border-top-color:#1f6f8b;animation:s 1s linear infinite}@keyframes s{to{transform:rotate(1turn)}}
@media (prefers-reduced-motion:reduce){.dot{animation:none}}p{line-height:1.6}</style></head>
<body><main><div class="dot"></div><h1>The system is starting</h1>
<p>It was asleep after a quiet while. This page opens it by itself in a few seconds
(the very first time, or after an update, it can take a few minutes).</p>
<p dir="rtl" lang="ar">النظام يبدأ الآن بعد فترة بدون استخدام. ستفتح الصفحة وحدها خلال ثوانٍ
(أول مرة أو بعد تحديث قد تأخذ بضع دقائق).</p></main></body></html>`;
	return new Response(html, {
		status: 503,
		headers: { "Content-Type": "text/html; charset=utf-8", "Retry-After": "5", "Cache-Control": "no-store" },
	});
}

export default {
	fetch(request, env) {
		// One system for everyone: a single container, in Western Europe next to the database (wrangler.jsonc).
		return env.APP.getByName("main").fetch(request);
	},
};
