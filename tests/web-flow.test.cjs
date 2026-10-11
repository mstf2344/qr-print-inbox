const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const tick = () => new Promise(resolve=>setImmediate(resolve));

async function setup({loseUpload=false,loseFinalize=false,expired=false,stored=false}={}) {
  class Element {
    constructor(id) {this.id=id;this.children=[];this.hidden=['activity','error','receipt','restart'].includes(id);this.classList={add(){},remove(){}};}
    replaceChildren(){this.children=[];}
    append(...children){this.children.push(...children);}
    setAttribute(){}
    focus(){this.focused=true;}
  }
  const nodes = new Map();
  const node = id => {if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);};
  const token = 'a'.repeat(43);
  const session = {status:'uploading',files:[]};
  let storage = stored ? token : null;
  let uploads=0,finalizes=0;
  const response = (data,status=200)=>({ok:status<300,status,json:async()=>JSON.parse(JSON.stringify(data))});
  const context = vm.createContext({
    document:{getElementById:node,createElement:()=>new Element(),addEventListener(){}},
    sessionStorage:{getItem:()=>storage,setItem:(key,value)=>{storage=value;},removeItem:()=>{storage=null;}},
    AbortController,setTimeout,clearTimeout,console,
    fetch:async(url,options)=>{
      if(url==='/api/v1/config')return response({max_file_size_mb:25,max_session_size_mb:100,max_files_per_session:10,allowed_extensions:['.png']});
      if(url==='/api/v1/sessions')return response({token},201);
      if(expired)return response({detail:'Oturum bulunamadı.'},404);
      if(url.endsWith('/status'))return response(session);
      if(url.endsWith('/finalize')) {
        finalizes++; Object.assign(session,{status:'complete',customer_number:7});
        if(loseFinalize){loseFinalize=false;throw new TypeError('network');}
        return response(session);
      }
      throw new Error('unexpected request');
    },
    XMLHttpRequest:class {
      constructor(){this.upload={};}
      open(){}
      setRequestHeader(name,value){if(name==='X-File-Name')this.name=decodeURIComponent(value);}
      send(file){
        uploads++; session.files.push({name:this.name,size:file.size});
        if(loseUpload){loseUpload=false;this.onerror();return;}
        this.status=201;this.responseText=JSON.stringify({name:this.name,status:'ready'});this.onload();
      }
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/app.js'),'utf8')+'\nglobalThis.ui={add,send,reset};',context);
  await tick();
  return {ui:context.ui,node,counts:()=>({uploads,finalizes}),storage:()=>storage};
}

test('multiple files yield a receipt only after delivery confirmation',async()=>{
  const h=await setup();
  h.ui.add([{name:'a.png',size:100},{name:'b.png',size:100}]);
  await h.ui.send();
  assert.deepEqual(h.counts(),{uploads:2,finalizes:1});
  assert.equal(h.node('number').textContent,'007');
  assert.equal(h.node('receipt').hidden,false);
  assert.equal(h.storage(),null);
});

test('a lost upload response is reviewed without blindly repeating the file',async()=>{
  const h=await setup({loseUpload:true});
  h.ui.add([{name:'a.png',size:100}]);
  await h.ui.send();
  assert.equal(h.node('activity').hidden,true);
  assert.equal(h.node('restart').hidden,true);
  await h.ui.send(); // Read the accepted server list, wait for customer review.
  assert.deepEqual(h.counts(),{uploads:1,finalizes:0});
  assert.equal(h.node('receipt').hidden,true);
  await h.ui.send();
  assert.deepEqual(h.counts(),{uploads:1,finalizes:1});
  assert.equal(h.node('receipt').hidden,false);
});

test('a lost finalize response restores the same receipt without another finalize',async()=>{
  const h=await setup({loseFinalize:true});
  h.ui.add([{name:'a.png',size:100}]);
  await h.ui.send();
  assert.equal(h.node('receipt').hidden,true);
  await h.ui.send();
  assert.deepEqual(h.counts(),{uploads:1,finalizes:1});
  assert.equal(h.node('number').textContent,'007');
});

test('an expired restored session unlocks a fresh selection and drops its token',async()=>{
  const h=await setup({expired:true,stored:true});
  await h.ui.send();
  assert.equal(h.node('choose').disabled,false);
  assert.equal(h.node('send').disabled,true);
  assert.equal(h.storage(),null);
});
