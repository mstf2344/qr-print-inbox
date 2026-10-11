// Outbound HTTP relay for Windows 7: bounded RAM buffers only, no storage calls.
import {handle} from "../worker/src/index.js";

const json = (body,status=200) => new Response(JSON.stringify(body),{status,
  headers:{"Content-Type":"application/json", "Cache-Control":"no-store",
    "X-Inbox-Service":"qr-print-inbox"}});
const offline = () => json({detail:"PC bağlantısı hazır değil. Biraz sonra tekrar deneyin."},503);

// One outstanding chunk: consumer acknowledgements apply backpressure to the phone.
export class Pipe {
  constructor() { this.slot=null; this.waiter=null; this.closed=false; }
  write(value) {
    if (this.closed) return Promise.reject(new Error("closed"));
    return new Promise((resolve,reject)=>{
      this.slot={value,resolve,reject};
      if (this.waiter) { const wake=this.waiter; this.waiter=null; wake(); }
    });
  }
  async read() {
    if (!this.slot && !this.closed) await new Promise(resolve=>{this.waiter=resolve;});
    if (!this.slot) return {done:true};
    const slot=this.slot; this.slot=null; slot.resolve();
    return slot.value===null ? {done:true} : {done:false,value:slot.value};
  }
  cancel() {
    this.closed=true;
    if (this.slot) { this.slot.reject(new Error("cancelled")); this.slot=null; }
    if (this.waiter) { this.waiter(); this.waiter=null; }
  }
}

export class Relay {
  constructor(state,env) {
    this.env=env; this.jobs=new Map(); this.agent=null; this.seen=0; this.pollWake=null;
  }
  validAgent(request) {
    const device=request.headers.get("X-Inbox-Device");
    if (!device || !/^[a-f0-9]{32}$/.test(device)) return false;
    if (this.agent && this.agent!==device && Date.now()-this.seen<35000) return false;
    this.agent=device; this.seen=Date.now(); return true;
  }
  async fetch(request) {
    const path=new URL(request.url).pathname;
    if (path.startsWith("/bridge/")) {
      if (!this.validAgent(request)) return json({detail:"Başka bir PC bağlı."},409);
      if (path==="/bridge/disconnect") {
        this.seen=0; this.agent=null;
        for (const job of this.jobs.values()) job.resolve(offline());
        if (this.pollWake) this.pollWake();
        return json({ok:true});
      }
      if (path==="/bridge/ping") return json({ok:true});
      if (path==="/bridge/poll") {
        const next=()=>[...this.jobs.values()].find(job=>!job.claimed);
        if (!next()) await new Promise(resolve=>{
          this.pollWake=resolve; setTimeout(resolve,20000);
        });
        this.pollWake=null;
        const job=next();
        if (!job) return json({job:null});
        job.claimed=true;
        return json({job:job.meta});
      }
      const match=/^\/bridge\/(body|reply)\/([a-f0-9-]{36})$/.exec(path);
      if (!match) return json({detail:"Bulunamadı."},404);
      const job=this.jobs.get(match[2]);
      if (!job || !job.claimed) return json({detail:"İstek sona erdi."},404);
      if (match[1]==="body" && request.method==="GET" && !job.bodyRead) {
        job.bodyRead=true;
        return new Response(new ReadableStream({
          pull:async controller=>{
            const chunk=await job.pipe.read();
            if (chunk.done) controller.close(); else controller.enqueue(chunk.value);
          },cancel:()=>job.pipe.cancel(),
        }),{headers:{"Content-Type":"application/octet-stream","Cache-Control":"no-store"}});
      }
      if (match[1]==="reply" && request.method==="POST") {
        if (Number(request.headers.get("Content-Length"))>20000) return json({},413);
        const text=await request.text();
        if (text.length>20000) return json({},413);
        let reply;
        try { reply=JSON.parse(text); JSON.parse(reply.body); } catch { return json({},422); }
        if (!Number.isInteger(reply.status) || reply.status<200 || reply.status>599 ||
            typeof reply.body!=="string" || reply.body.length>16384) return json({},422);
        job.resolve(new Response(reply.body,{status:reply.status,headers:{
          "Content-Type":"application/json", "X-Inbox-Service":"qr-print-inbox"}}));
        return json({ok:true});
      }
      return json({},405);
    }
    if (!this.agent || Date.now()-this.seen>35000) return offline();
    const uploads=[...this.jobs.values()].filter(job=>job.meta.path.endsWith("/files")).length;
    if (this.jobs.size>=32 || path.endsWith("/files") && uploads>=4) {
      return json({detail:"Diğer yüklemelerin bitmesini bekleyin."},429);
    }
    const id=crypto.randomUUID(); const pipe=new Pipe();
    const meta={id,path,method:request.method,
      filename:request.headers.get("X-File-Name") || "",
      ip:request.headers.get("X-Inbox-Client-IP")};
    let resolve;
    const answer=new Promise(done=>{resolve=done;});
    const job={meta,pipe,resolve,claimed:false,bodyRead:false}; this.jobs.set(id,job);
    const timer=setTimeout(()=>resolve(offline()),path.endsWith("/files") ? 185000 : 25000);
    const lease=setInterval(()=>{if(Date.now()-this.seen>35000) resolve(offline());},5000);
    if (this.pollWake) this.pollWake();
    // Read the request in its own request context; other requests see only RAM chunks.
    let bodyReader;
    const pump=(async()=>{
      if (!request.body) return;
      const reader=request.body.getReader(); bodyReader=reader;
      try {
        let size=0;
        while (true) {
          const {value,done}=await reader.read(); if (done) break;
          size+=value.length;
          if (size>25*1024*1024) throw new Error("limit");
          for (let offset=0;offset<value.length;offset+=65536) {
            await pipe.write(value.slice(offset,offset+65536));
          }
        }
        await pipe.write(null);
      } catch { resolve(offline()); }
      finally { await reader.cancel().catch(()=>{}); }
    })();
    try { return await answer; }
    finally {
      clearTimeout(timer); clearInterval(lease); pipe.cancel(); this.jobs.delete(id);
      await bodyReader?.cancel().catch(()=>{}); await pump;
    }
  }
}

async function authorized(request,env) {
  const supplied=request.headers.get("X-Inbox-Agent") || "";
  if (!env.GATEWAY_SECRET || supplied.length!==env.GATEWAY_SECRET.length) return false;
  const digest=async value=>new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(value)));
  const [a,b]=await Promise.all([digest(supplied),digest(env.GATEWAY_SECRET)]);
  return a.reduce((difference,value,i)=>difference | (value^b[i]),0)===0;
}

export default {async fetch(request,env) {
  const url=new URL(request.url);
  const stub=env.RELAY.get(env.RELAY.idFromName("file-inbox"));
  if (url.pathname.startsWith("/bridge/")) {
    if (url.search || !(await authorized(request,env))) return json({detail:"Yetkisiz bağlantı."},403);
    return stub.fetch(request);
  }
  return handle(request,env,(target,options)=>stub.fetch(new Request(target,options)));
}};
