const UPSTREAM = "https://upstream.example.com";
const MAX_FILE_BYTES = 25 * 1024 * 1024;
const SAFE_HEADERS = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
};

function error(status, detail) {
  return new Response(JSON.stringify({detail}), {
    status, headers: {...SAFE_HEADERS, "Content-Type":"application/json; charset=utf-8",
      ...([429,503].includes(status) ? {"Retry-After":"60"} : {})},
  });
}
const unavailable = () => error(503,"Şu anda bağlantı kurulamıyor. Alıcıya haber verin veya biraz sonra tekrar deneyin.");

async function boundedText(response) {
  if (!response.body) throw new Error("empty response");
  const reader = response.body.getReader();
  const chunks = []; let size = 0;
  while (true) {
    const {done,value} = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > 16384) { await reader.cancel(); throw new Error("response too large"); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk,offset); offset += chunk.byteLength; }
  return new TextDecoder().decode(bytes);
}

export async function handle(request, env, upstreamFetch = fetch) {
  const incoming = new URL(request.url);
  const path = incoming.pathname;
  if (incoming.search) return error(404,"Bulunamadı.");
  const asset = ["/","/style.css","/app.js"].includes(path);
  const status = /^\/api\/v1\/sessions\/[A-Za-z0-9_-]{43}\/status$/.test(path);
  const file = /^\/api\/v1\/sessions\/[A-Za-z0-9_-]{43}\/files$/.test(path);
  const finalize = /^\/api\/v1\/sessions\/[A-Za-z0-9_-]{43}\/finalize$/.test(path);
  const get = asset || status || ["/healthz","/api/v1/config"].includes(path);
  const post = file || finalize || path === "/api/v1/sessions";
  if (!get && !post) return error(404,"Bulunamadı.");
  if (request.method !== (get ? "GET" : "POST")) return error(405,"Bu işlem desteklenmiyor.");
  if (asset) {
    try {
      const target = new URL(path === "/" ? "/index.html" : path,incoming.origin);
      const response = await env.ASSETS.fetch(new Request(target));
      if (response.status !== 200) return unavailable();
      return new Response(response.body,{headers:{...SAFE_HEADERS,
        "Content-Type": path === "/app.js" ? "text/javascript; charset=utf-8"
          : path === "/style.css" ? "text/css; charset=utf-8" : "text/html; charset=utf-8"}});
    } catch { return unavailable(); }
  }
  if (!env.GATEWAY_SECRET || env.GATEWAY_SECRET.length < 32) return unavailable();
  const origin = request.headers.get("Origin");
  if (origin && origin !== incoming.origin) return error(403,"Bu bağlantı üzerinden işlem yapılamıyor.");
  const headers = {
    skip_zrok_interstitial:"1", Accept:"application/json",
    "X-Inbox-Gateway":env.GATEWAY_SECRET,
    "X-Inbox-Client-IP":request.headers.get("CF-Connecting-IP") || "",
  };
  let body;
  if (file) {
    const name = request.headers.get("X-File-Name");
    if (!name || name.length > 2048) return error(422,"Geçerli bir dosya adı gerekli.");
    if (request.headers.get("Content-Type") !== "application/octet-stream") return error(415,"Dosya türü desteklenmiyor.");
    const length = request.headers.get("Content-Length");
    if (length && (!/^\d+$/.test(length) || Number(length) > MAX_FILE_BYTES)) return error(413,"Dosya en fazla 25 MB olabilir.");
    if (!request.body) return error(422,"Boş dosya gönderilemez.");
    headers["Content-Type"] = "application/octet-stream";
    headers["X-File-Name"] = name;
    let received = 0;
    body = request.body.pipeThrough(new TransformStream({transform(chunk,controller) {
      received += chunk.byteLength;
      if (received > MAX_FILE_BYTES) throw new Error("upload limit");
      controller.enqueue(chunk);
    }}));
  }
  try {
    const response = await upstreamFetch(UPSTREAM + path,{
      method:request.method, headers, body, redirect:"manual", cache:"no-store",
      signal:AbortSignal.timeout(file ? 185000 : 25000),
    });
    if (response.status >= 300 && response.status < 400 ||
        response.headers.get("X-Inbox-Service") !== "qr-print-inbox" ||
        !response.headers.get("Content-Type")?.startsWith("application/json")) {
      await response.body?.cancel(); return unavailable();
    }
    const text = await boundedText(response);
    JSON.parse(text);
    return new Response(text,{status:response.status,headers:{...SAFE_HEADERS,
      "Content-Type":"application/json; charset=utf-8",
      ...([429,503].includes(response.status) ? {"Retry-After":"60"} : {})}});
  } catch { return unavailable(); }
}

export default {fetch:(request,env)=>{
  const url=new URL(request.url);
  if (env.COMPATIBLE_SERVICE && url.pathname.startsWith("/desktop/")) {
    url.pathname=url.pathname.slice("/desktop".length);
    return env.COMPATIBLE_SERVICE.fetch(new Request(url,request));
  }
  if (env.COMPATIBLE_SERVICE && env.USE_COMPATIBLE_AGENT==="true") {
    return env.COMPATIBLE_SERVICE.fetch(request);
  }
  return handle(request,env);
}};
