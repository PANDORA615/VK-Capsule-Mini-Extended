"use strict";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let token = sessionStorage.getItem("capsule-token") || "";
let state = {audio: null, device: null, ai: null};
let zone = "top", toastTimer, audioUrl, busyLight = false;
function requestId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return [...crypto.getRandomValues(new Uint8Array(16))].map(n=>n.toString(16).padStart(2,"0")).join("");
}

function toast(message) {
  $("#toast").textContent = message; $("#toast").classList.add("visible");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $("#toast").classList.remove("visible"), 4500);
}
async function api(path, body, method) {
  const headers = token ? {Authorization: "Bearer " + token} : {};
  const options = {headers, method: method || (body === undefined ? "GET" : "POST")};
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    headers["Idempotency-Key"] = requestId();
    options.body = JSON.stringify(body);
  }
  const response = await fetch("/api/v1/" + path, {...options, signal: AbortSignal.timeout(95000)});
  const data = await response.json();
  if (!response.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте введённые данные");
  }
  return data;
}
function act(fn) { return async event => { try { await fn(event); } catch (error) { toast(error.message); } }; }
function tab(name) {
  if (!["home", "setup", "lights", "settings"].includes(name)) name = "home";
  $$(".tab").forEach(el => el.classList.toggle("active", el.id === "tab-" + name));
  $$(".nav-item").forEach(el => {el.classList.toggle("active", el.dataset.tab === name); el.setAttribute("aria-current", el.dataset.tab === name ? "page" : "false");});
  $("#page-label").textContent = {home:"Обзор", setup:"Установка", lights:"Свет", settings:"Настройки"}[name];
  history.replaceState(null, "", "#" + name);
  if (name === "lights") renderEditor();
  window.scrollTo({top:0, behavior:"smooth"});
}
$$('[data-tab]').forEach(el => el.onclick = () => tab(el.dataset.tab));
$$('[data-go]').forEach(el => el.onclick = () => tab(el.dataset.go));
function openZone(name) {zone = name; tab("lights"); renderEditor();}
$$('[data-zone-link]').forEach(el => el.onclick = () => openZone(el.dataset.zoneLink));
$$('[data-zone]').forEach(el => el.onclick = () => {zone = el.dataset.zone; renderEditor();});
$("#top-hotspot").onclick = () => openZone("top");
$("#front-hotspot").onclick = () => openZone("front");

function renderAudio() {
  if(!state.audio) return;
  const a=state.audio;
  $("#volume").max=a.max_volume;
  if(document.activeElement!==$("#volume"))$("#volume").value=a.volume;
  $("#volume-value").textContent=a.volume+"%";
  $("#reply-audio").volume=a.volume/100;
}
function applyLights() {
  if (!state.device) return;
  const zones = state.device.lights.zones;
  for (const name of ["front","top"]) {
    const value = zones[name];
    $("#" + name + "-state").textContent = value.enabled ? value.brightness + "%" : "Выключено";
  }
  $("#light-summary").textContent = [zones.front,zones.top].filter(z => z.enabled).length + " из 2 зон включены";
}
function renderEditor() {
  if (!state.device) return;
  const value = state.device.lights.zones[zone];
  $$("[data-zone]").forEach(el => el.classList.toggle("selected", el.dataset.zone === zone));
  $("#zone-title").textContent = zone === "top" ? "Верхняя подсветка" : "Передние индикаторы";
  $("#light-enabled").checked = value.enabled; $("#light-color").value = value.color;
  $("#brightness").value = value.brightness; $("#brightness-value").textContent = value.brightness + "%";
  $("#effect").value = value.effect;
}
async function saveLight() {
  if (!state.device || busyLight) return;
  busyLight = true; const selected = zone;
  const value = {enabled:$("#light-enabled").checked, color:$("#light-color").value,
    brightness:Number($("#brightness").value), effect:$("#effect").value};
  $("#light-save-status").textContent = "Сохранение…";
  try {
    const result = await api("lights/" + selected, value); state.device.lights = result;
    applyLights(); if (zone === selected) renderEditor(); $("#light-save-status").textContent = "Сохранено";
  } catch (error) {
    $("#light-save-status").textContent = "Не сохранено: " + error.message; throw error;
  } finally { busyLight = false; }
}
for (const id of ["#light-enabled", "#light-color", "#brightness", "#effect"]) $(id).onchange = act(saveLight);
$("#brightness").oninput = () => $("#brightness-value").textContent = $("#brightness").value + "%";
$$('[data-color]').forEach(el => el.onclick = act(async () => {$("#light-color").value = el.dataset.color; await saveLight();}));
const physical = document.createElement("article"); physical.className = "card physical-bridge";
physical.innerHTML = '<h2>Подключить настоящую Капсулу</h2><p class="muted">Если на вашей колонке уже установлен совместимый агент, укажите его сервер в .env и проверьте подключение.</p><button class="secondary" id="check-bridges">Проверить серверы колонки</button><p id="bridge-status" class="muted" aria-live="polite">Проверка подключения выполняется по нажатию.</p><div class="bridge-actions"><button class="secondary" id="send-top" hidden>Отправить верхний свет на колонку</button><button class="secondary" id="send-clock" hidden>Применить яркость переднего дисплея</button></div>';
$("#tab-lights").append(physical);
$("#check-bridges").onclick = act(async()=>{
  const [front,top]=await Promise.all([api("bridge/status"),api("integrations/capsula/status")]);
  $("#send-top").hidden=!(top.connected && top.night_light_supported);
  $("#send-clock").hidden=!front.reachable;
  $("#bridge-status").textContent = "Передний дисплей: " + (front.reachable ? "сервер доступен" : front.configured ? "сервер не отвечает" : "не настроен") + ". Верхний свет: " + (top.connected ? top.night_light_supported ? "агент готов" : "агент без поддержки ночника" : top.configured ? "нет подключения" : "не настроен") + ". Аппаратная проверка ещё не выполнена.";
});
$("#send-top").onclick = act(async()=>{
  await api("integrations/capsula/light",state.device.lights.zones.top);
  toast("Агент подтвердил команду. Проверьте свет на колонке.");
});
$("#send-clock").onclick = act(async()=>{
  const front=state.device.lights.zones.front;
  await api("bridge/clock",{enabled:front.enabled,brightness:front.brightness});
  toast("Настройка дисплея принята сервером; проверьте колонку.");
});
$("#stop-answer").onclick = () => {
  $("#reply-audio").pause();$("#reply-audio").removeAttribute("src");
  answerEpoch++; requestController?.abort();
  $("#command-reply").textContent="Ответ остановлен";
};
$("#volume").oninput = () => $("#volume-value").textContent = $("#volume").value + "%";
$("#volume").onchange = act(async () => {state.audio=await api("audio/volume",{value:Number($("#volume").value)});renderAudio();});
let requestController=null,answerEpoch=0;
async function answerAudio(reply) {
  if(reply.playback==="stop")$("#reply-audio").pause();
  if (!reply.audio) return;
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  const bytes = Uint8Array.from(atob(reply.audio), c => c.charCodeAt(0));
  audioUrl = URL.createObjectURL(new Blob([bytes],{type:"audio/wav"}));
  $("#reply-audio").src = audioUrl;
  try {await $("#reply-audio").play();} catch {toast("Разрешите воспроизведение звука в браузере");}
}
$("#command-form").onsubmit = act(async event => {
  event.preventDefault();const button=event.target.querySelector("button");button.disabled=true;
  requestController?.abort();requestController=new AbortController();const epoch=++answerEpoch;
  $("#command-reply").textContent="Думаю…";
  try {
    const response=await fetch("/api/v1/commands",{method:"POST",headers:{"Content-Type":"application/json",...(token?{Authorization:"Bearer "+token}:{})},body:JSON.stringify({text:$("#command").value}),signal:AbortSignal.any([requestController.signal,AbortSignal.timeout(95000)])});
    const reply=await response.json();if(!response.ok)throw new Error(reply.detail||"Ошибка ответа");
    if(epoch!==answerEpoch)return;
    $("#command-reply").textContent=reply.text;await answerAudio(reply);await refresh();
  } catch(error) {if(error.name!=="AbortError")throw error;}
  finally {button.disabled=false;}
});
async function savePreferences() {
  const value = {microphone_muted:$("#mic-muted").checked,wake_word:$("#wake-word").value.trim()};
  state.device.preferences = await api("preferences", value); toast("Настройки сохранены");
}
$("#mic-muted").onchange = $("#save-wake").onclick = act(savePreferences);
$("#ai-mode").onchange = act(async () => {await api("assistant/mode",{mode:$("#ai-mode").value}); await refresh();});
$("#save-token").onclick = act(async () => {
  token = $("#owner-token").value.trim(); sessionStorage.setItem("capsule-token",token);
  await refresh(); renderEditor(); toast("Подключено");
});
async function refresh() {
  try {
    [state.audio,state.device,state.ai] = await Promise.all([api("audio/status"),api("device"),api("assistant/status")]);
    document.body.classList.remove("disconnected"); $(".sidebar-bottom").classList.remove("disconnected");
    $("#connection").textContent = "Сервер подключён";
    const simulated = state.device.mode === "simulation";
    $("#mode-badge").textContent = simulated ? "Режим симуляции" : "Сервер подключён";
    $("#assistant-status").textContent = state.ai.active_model || "Модель не активна";
    $("#mic-muted").checked = state.device.preferences.microphone_muted;
      if (document.activeElement !== $("#wake-word")) $("#wake-word").value = state.device.preferences.wake_word;
    if (document.activeElement !== $("#ai-mode")) $("#ai-mode").value = state.ai.mode;
    $("#ai-details").replaceChildren();
    const labels = {PRIMARY_LIVE:"Gemini Live",FALLBACK_FLASH_LITE:"Flash-Lite + Piper",OFFLINE_COMMANDS_ONLY:"Только локальные команды"};
    for (const text of ["Состояние: " + labels[state.ai.state],"Модель: " + (state.ai.active_model || "не активна"),"Причина: " + state.ai.reason,"Квота: нет достоверных данных"]){const p=document.createElement("p");p.textContent=text;$("#ai-details").append(p);}
    $("#device-details").textContent = "Профиль платы: не определён · Индикаторы: виртуальные · STT: " + (state.device.voice.stt_configured ? "настроен" : "не настроен") + " · TTS: " + (state.device.voice.tts_configured ? "настроен" : "не настроен");
    $("#ssh-status").textContent=state.device.ssh.configured ? "SSH настроен для учётной записи "+state.device.ssh.user+". Фактический доступ не проверен." : "SSH не настроен. Укажите адрес и учётную запись в .env.";
    renderAudio(); applyLights();
  } catch(error) {
    document.body.classList.add("disconnected");$(".sidebar-bottom").classList.add("disconnected");
    $("#connection").textContent="Нет подключения";$("#mode-badge").textContent="Сервер недоступен";
    throw error;
  }
}
$$(".record-command").forEach(recordButton=>recordButton.onclick=act(async () => {
  if (!state.device?.voice.stt_configured) throw new Error("Сначала настройте VOSK_MODEL_PATH на сервере");
  if (state.device.preferences.microphone_muted) throw new Error("Микрофон выключен в приложении");
  if (!navigator.mediaDevices) throw new Error("Запись требует HTTPS или localhost");
  const epoch=++answerEpoch;$$(".record-command").forEach(b=>b.disabled=true);
  let stream,context,source,processor;
  try {
    stream = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true},video:false});
    context = new AudioContext();source=context.createMediaStreamSource(stream);
    processor=context.createScriptProcessor(4096,1,1);const chunks=[];
    processor.onaudioprocess = e => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    source.connect(processor);processor.connect(context.destination);
    $("#voice-note").textContent="Слушаю одну фразу, 8 секунд…";
    await new Promise(resolve=>setTimeout(resolve,8000));
    processor.disconnect();source.disconnect();stream.getTracks().forEach(t=>t.stop());
    const input=new Float32Array(chunks.reduce((n,c)=>n+c.length,0));let offset=0;
    chunks.forEach(c=>{input.set(c,offset);offset+=c.length;});
    const ratio=context.sampleRate/16000;const view=new DataView(new ArrayBuffer(Math.floor(input.length/ratio)*2));
    for(let i=0;i<view.byteLength/2;i++){let sum=0,count=0;for(let j=Math.floor(i*ratio);j<Math.floor((i+1)*ratio)&&j<input.length;j++){sum+=input[j];count++;}view.setInt16(i*2,Math.max(-1,Math.min(1,sum/Math.max(1,count)))*32767,true);}
    $("#voice-note").textContent="Распознаю команду…";
    const response=await fetch("/api/v1/voice/transcribe",{method:"POST",headers:{"Content-Type":"application/octet-stream",...(token?{Authorization:"Bearer "+token}:{})},body:view.buffer,signal:AbortSignal.timeout(95000)});
    const reply=await response.json();if(!response.ok)throw new Error(reply.detail||"Ошибка голосовой команды");
    $("#voice-note").textContent=(reply.transcript ? "Вы: "+reply.transcript+". " : "")+reply.text;
    if(epoch!==answerEpoch)return;
    $("#command-reply").textContent=reply.text;await answerAudio(reply);await refresh();
  } finally {processor?.disconnect();source?.disconnect();stream?.getTracks().forEach(t=>t.stop());if(context)await context.close(); $$(".record-command").forEach(b=>b.disabled=false);}
}));
$("#today").textContent=new Date().toLocaleDateString("ru-RU",{day:"numeric",month:"long",weekday:"long"});
tab(location.hash.slice(1)||"home");
(async()=>{try{await refresh();renderEditor();}catch(error){toast(error.message);}})();
setInterval(()=>refresh().catch(()=>{}),2500);

$("#check-device").onclick=act(async()=>{
 const status=await api("integrations/capsula/status");
 $("#agent-status").textContent=status.connected ? "Агент подключён. Возможности: "+status.capabilities.join(", ") : status.configured ? "Агент недоступен" : "Укажите адрес сервера, ID устройства и пароль панели в .env";
});
$$("[data-device-action]").forEach(button=>button.onclick=act(async()=>{
 button.disabled=true;
 try{const result=await api("device/control",{action:button.dataset.deviceAction});$("#device-control-result").textContent="Агент подтвердил команду. "+JSON.stringify(result.data);}
 finally{button.disabled=false;}
}));
