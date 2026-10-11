import test from "node:test";
import assert from "node:assert/strict";
import {handle} from "../src/index.js";

const token = "a".repeat(43);
const env = {GATEWAY_SECRET:"test-only-".repeat(5),ASSETS:{fetch:()=>new Response("test asset")}};
const request = (path="/api/v1/config",init={}) => new Request("https://test.workers.dev"+path,
  {...init,headers:{"CF-Connecting-IP":"192.0.2.1",...init.headers}});
const json = (body={status:"ok"},status=200) => new Response(JSON.stringify(body),
  {status,headers:{"Content-Type":"application/json","X-Inbox-Service":"qr-print-inbox"}});

test("fixed upstream, gateway authentication, no caller cookies or credentials",async()=>{
  const result = await handle(request(undefined,{headers:{Cookie:"secret",Authorization:"secret","X-Inbox-Client-IP":"fake"}}),env,async(url,init)=>{
    assert.equal(url,"https://upstream.example.com/api/v1/config");
    assert.equal(init.headers.skip_zrok_interstitial,"1");
    assert.equal(init.headers["X-Inbox-Gateway"],env.GATEWAY_SECRET);
    assert.equal(init.headers["X-Inbox-Client-IP"],"192.0.2.1");
    assert.equal(init.headers.Cookie,undefined); assert.equal(init.headers.Authorization,undefined);
    assert.equal(init.redirect,"manual"); assert.equal(init.cache,"no-store"); return json();
  });
  assert.equal(result.status,200); assert.equal(result.headers.get("cache-control"),"no-store");
  assert.ok(!(await result.text()).includes(env.GATEWAY_SECRET));
});

test("only explicit assets are served even when PC is offline",async()=>{
  for (const path of ["/","/app.js","/style.css"]) {
    const result = await handle(request(path),env,()=>{throw new Error("must not fetch");});
    assert.equal(result.status,200); assert.equal(await result.text(),"test asset");
  }
});

test("unknown paths, queries, bad tokens, methods and cross-origin requests are closed",async()=>{
  for (const [path,init,status] of [
    ["/.env",{},404],["/index.html",{},404],["/?url=https://evil.example",{},404],
    ["/api/v1/sessions/bad/status",{},404],["/api/v1/sessions",{},405],
    ["/",{method:"POST"},405],["//evil.example/",{},404],
    ["/api/v1/config",{headers:{Origin:"https://evil.example"}},403],
  ]) assert.equal((await handle(request(path,init),env,()=>{throw new Error("must not fetch");})).status,status);
});

test("unconfigured secret, offline, redirect, warning HTML, wrong marker and huge JSON fail closed",async()=>{
  assert.equal((await handle(request(),{},()=>{throw new Error();})).status,503);
  for (const upstream of [
    ()=>{throw new Error("private details");},
    ()=>new Response(null,{status:302,headers:{Location:"https://evil.example"}}),
    ()=>new Response("Visit Share"),()=>new Response('{}',{headers:{"Content-Type":"application/json"}}),
    ()=>json({data:"x".repeat(16385)}),
  ]) {
    const result = await handle(request(),env,upstream); assert.equal(result.status,503);
    assert.ok(!(await result.text()).includes("private details"));
  }
});

test("valid upload body streams unchanged and filenames remain encoded",async()=>{
  const bytes = new Uint8Array([1,2,3,4]);
  const result = await handle(request(`/api/v1/sessions/${token}/files`,{
    method:"POST",body:bytes,headers:{"Content-Type":"application/octet-stream","X-File-Name":"%C3%B6rnek.png"},
  }),env,async(url,init)=>{
    assert.equal(init.headers["X-File-Name"],"%C3%B6rnek.png");
    assert.deepEqual(new Uint8Array(await new Response(init.body).arrayBuffer()),bytes);
    return json({status:"ready"},201);
  });
  assert.equal(result.status,201);
});

test("declared and streamed oversize uploads cannot reach accept",async()=>{
  const path = `/api/v1/sessions/${token}/files`;
  const headers = {"Content-Type":"application/octet-stream","X-File-Name":"test.png"};
  assert.equal((await handle(request(path,{method:"POST",body:"x",headers:{...headers,"Content-Length":"26214401"}}),env,()=>{throw new Error("must not fetch");})).status,413);
  const result = await handle(request(path,{method:"POST",body:new Uint8Array(26214401),headers}),env,async(url,init)=>{
    await assert.rejects(()=>new Response(init.body).arrayBuffer()); return new Response(null,{status:502});
  });
  assert.equal(result.status,503);
});

test("backend validation and quota errors remain JSON with safe headers",async()=>{
  for (const code of [403,404,408,409,413,415,422,429,503,507]) {
    const result = await handle(request(),env,()=>json({detail:"test error"},code));
    assert.equal(result.status,code); assert.deepEqual(await result.json(),{detail:"test error"});
    if ([429,503].includes(code)) assert.equal(result.headers.get("retry-after"),"60");
  }
});
