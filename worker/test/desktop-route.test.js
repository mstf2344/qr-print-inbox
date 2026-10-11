import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

test("desktop bridge uses a fixed service binding and preserves its authenticated request",async()=>{
  let seen;
  const env={COMPATIBLE_SERVICE:{fetch:async request=>{seen=request; return new Response("ok");}}};
  const request=new Request("https://shop.test/desktop/bridge/poll",{headers:{"X-Inbox-Agent":"fixture"}});
  assert.equal((await worker.fetch(request,env)).status,200);
  assert.equal(new URL(seen.url).pathname,"/bridge/poll");
  assert.equal(seen.headers.get("X-Inbox-Agent"),"fixture");
});
test("production switches to the compatible client only with the explicit deployment flag",async()=>{
  let seen;
  const env={USE_COMPATIBLE_AGENT:"true",COMPATIBLE_SERVICE:{fetch:async request=>{seen=request; return new Response("ok");}}};
  const request=new Request("https://shop.test/api/v1/config");
  await worker.fetch(request,env);
  assert.equal(seen,request);
});
