"use strict";
const $ = (id) => document.getElementById(id);
let limits = {max_file_size_mb:25,max_session_size_mb:100,max_files_per_session:10,allowed_extensions:[".pdf",".docx",".pptx",".xlsx",".jpg",".jpeg",".png"]};
let selected = [];
let token = null;
let busy = false;
let started = false;
let uncertain = false;
const key = "print-inbox-session";
const mb = (size) => size < 104858 ? `${Math.max(1,Math.ceil(size/1024))} KB` : `${(size / 1048576).toLocaleString("tr-TR", {maximumFractionDigits:1})} MB`;
function message(text = "") { $("error").textContent = text; $("error").hidden = !text; }
function remember() { try { sessionStorage.setItem(key, token); } catch {} }
function forget() { try { sessionStorage.removeItem(key); } catch {} }
function render() {
  $("file-list").replaceChildren();
  selected.forEach((item, index) => {
    const row = document.createElement("li");
    const text = document.createElement("div"); text.className = "file-text";
    const name = document.createElement("span"); name.className = "file-name"; name.textContent = item.name;
    const meta = document.createElement("span"); meta.className = "file-meta";
    meta.textContent = `${mb(item.size)}${item.done ? " · Yüklendi" : ""}`;
    text.append(name,meta); row.append(text);
    if (!started && !busy) {
      const remove = document.createElement("button"); remove.className = "remove"; remove.type = "button";
      remove.textContent = "×"; remove.setAttribute("aria-label", `${item.name} dosyasını kaldır`);
      remove.onclick = () => { selected.splice(index,1); render(); }; row.append(remove);
    }
    $("file-list").append(row);
  });
  $("choose").disabled = busy || started;
  $("restart").hidden = busy || !started || uncertain || $("error").hidden;
  $("send").disabled = busy || (!selected.length && !token);
  $("send").textContent = busy ? "Gönderiliyor…" : uncertain ? "Gönderim durumunu kontrol et" : started ? "Gönderime devam et" : "Dosyaları gönder";
}
function add(files) {
  if (busy || started) return;
  message();
  const next = [...selected];
  for (const file of files) {
    const extension = "." + file.name.split(".").pop().toLowerCase();
    if (!limits.allowed_extensions.includes(extension)) return message(`${file.name}: bu dosya türü desteklenmiyor.`);
    if (!file.size) return message(`${file.name}: boş dosya gönderilemez.`);
    if (file.size > limits.max_file_size_mb * 1048576) return message(`${file.name}: dosya en fazla ${limits.max_file_size_mb} MB olabilir.`);
    next.push({file, name:file.name, size:file.size, done:false});
  }
  if (next.length > limits.max_files_per_session) return message(`En fazla ${limits.max_files_per_session} dosya seçebilirsiniz.`);
  if (next.reduce((sum,f)=>sum+f.size,0) > limits.max_session_size_mb * 1048576) return message(`Dosyaların toplamı en fazla ${limits.max_session_size_mb} MB olabilir.`);
  selected = next; render();
}
async function api(path, method="GET") {
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(),25000);
  try {
    const response = await fetch(path,{method,cache:"no-store",signal:controller.signal,headers:{Accept:"application/json"}});
    let data;
    try { data = await response.json(); } catch { throw new Error("Bağlantı kurulamadı. Biraz sonra tekrar deneyin."); }
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : "İşlem tamamlanamadı. Tekrar deneyin.");
      error.status = response.status; throw error;
    }
    return data;
  } finally { clearTimeout(timer); }
}
function receipt(data) {
  if (data.status !== "complete" || !Number.isInteger(data.customer_number)) throw new Error("Teslim doğrulanamadı. Alıcıya haber verin.");
  $("number").textContent = String(data.customer_number).padStart(3,"0");
  uncertain = false;
  $("upload-panel").hidden = true; $("receipt").hidden = false; $("receipt").focus(); forget();
}
function upload(item,index) {
  return new Promise((resolve,reject)=> {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/sessions/${token}/files`); xhr.timeout = 180000;
    xhr.setRequestHeader("Content-Type","application/octet-stream");
    xhr.setRequestHeader("X-File-Name",encodeURIComponent(item.name));
    xhr.upload.onprogress = (e) => {
      const percent = e.lengthComputable ? Math.round(e.loaded/e.total*100) : 0;
      $("progress").value = percent;
      $("progress-label").textContent = percent === 100 ? `${index+1}/${selected.length} · Dosya kontrol ediliyor…` : `${index+1}/${selected.length} · Yükleniyor %${percent}`;
    };
    xhr.onload = () => {
      let data; try { data = JSON.parse(xhr.responseText); } catch { return reject(new Error("Sunucu yanıtı alınamadı. Gönderim durumunu kontrol edin.")); }
      if (xhr.status < 200 || xhr.status >= 300) {
        const error = new Error(typeof data.detail === "string" ? data.detail : "Dosya yüklenemedi.");
        error.status = xhr.status; return reject(error);
      }
      item.done = true; item.name = data.name; resolve();
    };
    xhr.onerror = xhr.ontimeout = () => reject(new Error("Bağlantı kesildi. Gönderim durumunu kontrol ederek devam edin."));
    xhr.send(item.file);
  });
}
async function send() {
  if (busy) return;
  busy = true; message(); render();
  try {
    if (!token) { token = (await api("/api/v1/sessions","POST")).token; remember(); }
    started = true; render();
    const state = await api(`/api/v1/sessions/${token}/status`);
    if (state.status === "complete") return receipt(state);
    if (uncertain) {
      // Never blindly repeat an upload whose response was lost: identical names
      // are legal. Require review rather than silently creating a duplicate.
      uncertain = false;
      selected = state.files.map(f=>({...f,done:true}));
      render();
      if (!selected.length) {
        forget(); token = null; started = false;
        message("Tamamlanmış dosya bulunamadı. Dosyalarınızı yeniden seçin."); return;
      }
      message("PC’ye ulaşan dosyalar yukarıda. Liste tamamsa gönderime devam edin. Eksik varsa alıcıya haber verin.");
      return;
    }
    $("activity").hidden = false;
    for (let i=0;i<selected.length;i++) {
      if (selected[i].done) continue;
      $("progress").value = 0;
      $("progress-label").textContent = `${i+1}/${selected.length} · Yükleniyor…`;
      uncertain = true; await upload(selected[i],i); uncertain = false; render();
    }
    $("progress-label").textContent = "Gönderim tamamlanıyor…";
    uncertain = true;
    receipt(await api(`/api/v1/sessions/${token}/finalize`,"POST"));
  } catch(error) {
    $("activity").hidden = true;
    if (error.status === 404) { forget(); token=null; started=false; uncertain=false; selected=[]; }
    message(error.name === "AbortError" ? "Bağlantı beklenenden uzun sürdü. Tekrar deneyerek gönderim durumunu kontrol edin." : error.name === "TypeError" ? "Bağlantı kurulamadı. İnternetinizi kontrol edip tekrar deneyin." : error.message);
  } finally { busy=false; render(); }
}
$("choose").onclick=()=>$("files").click();
$("files").onchange=(e)=> { add(e.target.files); e.target.value=""; };
$("choose").ondragover=(e)=>{e.preventDefault();if(!started)$("choose").classList.add("dragging");};
$("choose").ondragleave=()=>$("choose").classList.remove("dragging");
$("choose").ondrop=(e)=>{e.preventDefault();$("choose").classList.remove("dragging");add(e.dataTransfer.files);};
document.addEventListener("dragover",e=>e.preventDefault());
document.addEventListener("drop",e=>e.preventDefault());
$("send").onclick=send;
function reset() {token=null;selected=[];started=false;uncertain=false;forget();$("receipt").hidden=true;$("upload-panel").hidden=false;$("activity").hidden=true;message();render();$("choose").focus();}
$("again").onclick=reset;
$("restart").onclick=reset;
async function init() {
  try { token=sessionStorage.getItem(key); } catch {}
  if (token && !/^[A-Za-z0-9_-]{43}$/.test(token)) {token=null;forget();}
  if (token) { started=true;uncertain=true; }
  render();
  try {
    limits = await api("/api/v1/config");
    $("files").accept=limits.allowed_extensions.join(",");
    $("limits").textContent=`Dosya başına ${limits.max_file_size_mb} MB · En fazla ${limits.max_files_per_session} dosya`;
  } catch { message("Şu anda bağlantı kurulamıyor. Alıcıya haber verin veya biraz sonra tekrar deneyin."); }
}
init();
