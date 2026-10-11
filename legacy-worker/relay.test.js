import test from "node:test";
import assert from "node:assert/strict";
import worker,{Pipe,Relay} from "./src.js";

const id="a".repeat(32);
const headers={"X-Inbox-Device":id};
const req=(path,init={})=>new Request("https://relay.test"+path,init);
const bridge=(path,init={})=>req("/bridge"+path,{...init,headers:{...headers,...init.headers}});

test("offline PC and a second connected PC are rejected",async()=>{
  const relay=new Relay({},{});
  assert.equal((await relay.fetch(req("/healthz"))).status,503);
  assert.equal((await relay.fetch(bridge("/ping"))).status,200);
  assert.equal((await relay.fetch(bridge("/ping",{headers:{"X-Inbox-Device":"b".repeat(32)}}))).status,409);
});
test("one chunk waits for consumer acknowledgement; cancellation unblocks producer",async()=>{
  const pipe=new Pipe(); let consumed=false;
  const writing=pipe.write(new Uint8Array([1,2])).then(()=>{consumed=true;});
  await Promise.resolve(); assert.equal(consumed,false);
  assert.deepEqual((await pipe.read()).value,new Uint8Array([1,2]));
  await writing; assert.equal(consumed,true);
  const pending=pipe.write(new Uint8Array([3])); pipe.cancel();
  await assert.rejects(pending); assert.equal((await pipe.read()).done,true);
});
test("file flows through bounded RAM chunks, response resolves once, no storage used",async()=>{
  const state={get storage(){throw new Error("no cloud file storage allowed");}};
  const relay=new Relay(state,{}); await relay.fetch(bridge("/ping"));
  const content=new Uint8Array(200000).fill(7);
  const answer=relay.fetch(req("/api/v1/sessions/"+"t".repeat(43)+"/files",{
    method:"POST",body:content,headers:{"X-Inbox-Client-IP":"192.0.2.1","X-File-Name":"test.png"},
  }));
  const {job}=await (await relay.fetch(bridge("/poll"))).json();
  assert.equal(job.ip,"192.0.2.1"); assert.equal(job.filename,"test.png");
  const body=await relay.fetch(bridge("/body/"+job.id));
  assert.deepEqual(new Uint8Array(await body.arrayBuffer()),content);
  const reply={status:201,body:JSON.stringify({name:"test.png",status:"ready"})};
  assert.equal((await relay.fetch(bridge("/reply/"+job.id,{method:"POST",body:JSON.stringify(reply)}))).status,200);
  assert.equal((await answer).status,201); assert.equal(relay.jobs.size,0);
  assert.equal((await relay.fetch(bridge("/reply/"+job.id,{method:"POST",body:JSON.stringify(reply)}))).status,404);
});
test("untrusted agent calls are blocked before reaching the object",async()=>{
  const env={GATEWAY_SECRET:"s".repeat(48),RELAY:{idFromName:()=>1,get:()=>({fetch:()=>{throw new Error("must not reach DO");}})}};
  assert.equal((await worker.fetch(bridge("/poll"),env)).status,403);
});
test("requests with no file body are delivered and invalid replies remain closed",async()=>{
  const relay=new Relay({},{}); await relay.fetch(bridge("/ping"));
  const answer=relay.fetch(req("/api/v1/sessions",{method:"POST"}));
  const {job}=await (await relay.fetch(bridge("/poll"))).json();
  assert.equal((await relay.fetch(bridge("/reply/"+job.id,{method:"POST",body:'{"status":200,"body":"invalid"}'}))).status,422);
  await relay.fetch(bridge("/reply/"+job.id,{method:"POST",body:JSON.stringify({status:201,body:'{"token":"example"}'})}));
  assert.equal((await answer).status,201);
});
test("ten concurrent finalize requests queue safely without the upload concurrency limit",async()=>{
  const relay=new Relay({},{}); await relay.fetch(bridge("/ping"));
  const answers=Array.from({length:10},()=>relay.fetch(req(
    "/api/v1/sessions/"+"t".repeat(43)+"/finalize",{method:"POST"})));
  assert.equal(relay.jobs.size,10);
  for(let i=0;i<10;i++) {
    const {job}=await (await relay.fetch(bridge("/poll"))).json();
    await relay.fetch(bridge("/reply/"+job.id,{method:"POST",body:JSON.stringify({status:200,body:'{"status":"complete"}'})}));
  }
  assert.ok((await Promise.all(answers)).every(response=>response.status===200));
  assert.equal(relay.jobs.size,0);
});
test("an authenticated disconnect fails pending requests and immediately marks the PC offline",async()=>{
  const relay=new Relay({},{}); await relay.fetch(bridge("/ping"));
  const answer=relay.fetch(req("/healthz"));
  await relay.fetch(bridge("/disconnect"));
  assert.equal((await answer).status,503);
  assert.equal((await relay.fetch(req("/api/v1/config"))).status,503);
});
