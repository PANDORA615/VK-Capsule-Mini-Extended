"use strict";
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let token = sessionStorage.getItem("capsule-token") || "";
let state = {radio: null, device: null, ai: null, stations: [], favorites: []};
let zone = "top", toastTimer, audioUrl, networkAvailable = true, busyLight = false;
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
    if (data.candidates?.length) renderStations("#all-stations", data.candidates);
    throw new Error(typeof data.detail === "string" ? data.detail : "Проверьте введённые данные");
  }
  return data;
}
function act(fn) { return async event => { try { await fn(event); } catch (error) { toast(error.message); } }; }
function tab(name) {
  if (!["home", "radio", "lights", "settings"].includes(name)) name = "home";
  $$(".tab").forEach(el => el.classList.toggle("active", el.id === "tab-" + name));
  $$(".nav-item").forEach(el => {el.classList.toggle("active", el.dataset.tab === name); el.setAttribute("aria-current", el.dataset.tab === name ? "page" : "false");});
  $("#page-label").textContent = {home:"Обзор", radio:"Радио", lights:"Свет", settings:"Настройки"}[name];
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

function stationLogo(station) {
  return ({dacha:"Дача", russkoe:"РР", avto:"АВТО", retro:"Ретро"})[station.id] || station.name.slice(0,2).toUpperCase();
}
function renderStations(target, stations) {
  const container = $(target); container.replaceChildren();
  for (const station of stations) {
    const card = document.createElement("article"); card.className = "station-card";
    const button = document.createElement("button"); button.className = "station-button";
    button.setAttribute("aria-label", "Включить " + station.name);
    const logo = document.createElement("span"); logo.className = "station-logo"; logo.textContent = stationLogo(station);
    const info = document.createElement("span"); info.className = "station-info";
    const title = document.createElement("strong"); title.textContent = station.name;
    const note = document.createElement("small"); note.textContent = station.source === "simulation" ? "Демо-станция" : "Интернет-радио";
    info.append(title, note); button.append(logo,info); card.append(button);
    button.onclick = act(async () => {await api("radio/play", {station:station.id}); await refresh();});
    const fav = document.createElement("button"); fav.className = "favorite-button";
    const saved = state.favorites.some(s => s.id === station.id);
    fav.classList.toggle("saved", saved); fav.setAttribute("aria-label", (saved ? "Убрать из избранного: " : "В избранное: ") + station.name);
    fav.innerHTML = '<svg><use href="#i-star"/></svg>';
    fav.onclick = act(async () => {
      if (saved) await api("radio/favorites/" + encodeURIComponent(station.id), undefined, "DELETE");
      else await api("radio/favorites", {station:station.id});
      await loadStations(); toast(saved ? "Удалено из избранного" : "Добавлено в избранное");
    }); card.append(fav); container.append(card);
  }
}
async function loadStations() {
  [state.stations, state.favorites] = await Promise.all([api("radio/stations"),api("radio/favorites")]);
  renderStations("#home-stations", state.stations.slice(0,4)); renderStations("#all-stations",state.stations);
  renderStations("#favorites",state.favorites);
}
const stateText = {IDLE:"Радио выключено",CONNECTING:"Подключаемся…",PLAYING:"В эфире",BUFFERING:"Буферизация…",PAUSED:"На паузе",RECONNECTING:"Восстанавливаем связь…",ERROR:"Поток недоступен"};
function renderRadio() {
  const r = state.radio; if (!r) return;
  $("#now-name").textContent = r.station?.name || "Пора включить любимое";
  $("#now-state").textContent = (r.simulation ? "Симуляция · " : "") + stateText[r.state];
  $(".now-card").classList.toggle("playing",r.state === "PLAYING");
  $("#volume").max = r.max_volume;
  if (document.activeElement !== $("#volume")) $("#volume").value = r.volume;
  $("#volume-value").textContent = r.volume + "%";
  const active = ["PLAYING", "BUFFERING", "CONNECTING", "RECONNECTING"].includes(r.state);
  $("#main-play").innerHTML = active ? '<span aria-hidden="true">Ⅱ</span>' : '<svg><use href="#i-play"/></svg>';
  $("#main-play").setAttribute("aria-label", active ? "Пауза" : "Включить радио");
}
function applyLights() {
  if (!state.device) return;
  const zones = state.device.lights.zones;
  for (const name of ["front","top"]) {
    const value = zones[name];
    document.documentElement.style.setProperty("--" + name, value.color);
    document.documentElement.style.setProperty("--" + name + "-opacity", value.enabled ? value.brightness / 100 : 0);
    const el = $(name === "top" ? ".top-light" : ".front-light");
    el.classList.remove("effect-breathe", "effect-pulse");
    if (value.effect !== "steady") el.classList.add("effect-" + value.effect);
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
  $("#light-halo").style.setProperty("--halo",value.color);
  $("#light-halo").style.opacity = value.enabled ? Math.max(.1,value.brightness / 100) : .1;
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
const presets = {cozy:{color:"#ffb66e",brightness:45,effect:"steady"},night:{color:"#b49aff",brightness:20,effect:"breathe"},bright:{color:"#88e7cb",brightness:85,effect:"steady"}};
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
$$('[data-preset]').forEach(el => el.onclick = act(async () => {
  const value = {...presets[el.dataset.preset],enabled:true};
  await api("lights/top",value); await api("lights/front",{...value,effect:"steady"});
  await refresh(); renderEditor(); toast("Световое настроение сохранено");
}));
async function togglePlay() {
  const r = state.radio;
  if (["PLAYING","BUFFERING"].includes(r?.state)) await api("radio/pause",{});
  else if (["CONNECTING","RECONNECTING"].includes(r?.state)) await api("radio/stop",{});
  else if (r?.last_id || r?.state === "PAUSED") await api("radio/resume",{});
  else if (state.stations.length) await api("radio/play",{station:state.stations[0].id});
  else {tab("radio"); toast("Найдите или добавьте радиостанцию");}
  await refresh();
}
$("#main-play").onclick = $("#touch-play").onclick = act(togglePlay);
$("#previous").onclick = act(async () => {await api("radio/previous",{}); await refresh();});
$("#next").onclick = act(async () => {await api("radio/next",{}); await refresh();});
$("#stop").onclick = act(async () => {await api("radio/stop",{}); await refresh();});
$("#volume").oninput = () => $("#volume-value").textContent = $("#volume").value + "%";
$("#volume").onchange = act(async () => {await api("audio/volume",{value:Number($("#volume").value)}); await refresh();});
for (const [id,delta] of [["#touch-plus",10],["#touch-minus",-10]]) $(id).onclick = act(async () => {
  await api("audio/volume",{value:Math.max(0,Math.min(100,(state.radio?.volume || 0) + delta))}); await refresh();
});
$("#search-form").onsubmit = act(async event => {
  event.preventDefault(); const result = await api("radio/stations?query=" + encodeURIComponent($("#station-query").value));
  renderStations("#all-stations",result); $("#catalog-note").textContent = result.length ? "Выберите станцию" : "Не найдено. Каталог может быть недоступен; попробуйте свой URL.";
});
$("#add-station-form").onsubmit = act(async event => {
  event.preventDefault(); await api("radio/stations",{id:requestId(),name:$("#custom-name").value,urls:[$("#custom-url").value],source:"owner"});
  await loadStations(); event.target.reset(); toast("Станция сохранена. Воспроизведение проверяется при запуске.");
});
async function answerAudio(reply) {
  if (!reply.audio) return;
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  const bytes = Uint8Array.from(atob(reply.audio), c => c.charCodeAt(0));
  audioUrl = URL.createObjectURL(new Blob([bytes],{type:"audio/wav"}));
  $("#reply-audio").src = audioUrl;
  try {await $("#reply-audio").play();} catch {toast("Разрешите воспроизведение звука в браузере");}
}
$("#command-form").onsubmit = act(async event => {
  event.preventDefault(); const button = event.target.querySelector("button"); button.disabled = true;
  $("#command-reply").textContent = "Выполняю…";
  try {const reply = await api("commands",{text:$("#command").value});
    $("#command-reply").textContent = reply.text; await answerAudio(reply); await refresh();
    if (reply.candidates?.length) {tab("radio");renderStations("#all-stations",reply.candidates);}
  } finally {button.disabled = false;}
});
async function savePreferences() {
  const value = {resume_after_reboot:$("#auto-resume").checked,microphone_muted:$("#mic-muted").checked,wake_word:$("#wake-word").value.trim()};
  state.device.preferences = await api("preferences", value); toast("Настройки сохранены");
}
$("#auto-resume").onchange = $("#mic-muted").onchange = $("#save-wake").onclick = act(savePreferences);
$("#ai-mode").onchange = act(async () => {await api("assistant/mode",{mode:$("#ai-mode").value}); await refresh();});
$("#save-token").onclick = act(async () => {
  token = $("#owner-token").value.trim(); sessionStorage.setItem("capsule-token",token);
  await refresh(); await loadStations(); renderEditor(); toast("Подключено");
});
$("#sim-network").onclick = act(async () => {
  networkAvailable = !networkAvailable; await api("simulation/network",{available:networkAvailable});
  $("#sim-network").textContent = networkAvailable ? "Проверить обрыв сети" : "Восстановить сеть в симуляции";
  toast(networkAvailable ? "Сеть восстановлена" : "Симуляция потери сети для радио");
});
async function refresh() {
  try {
    [state.radio,state.device,state.ai] = await Promise.all([api("radio/status"),api("device"),api("assistant/status")]);
    document.body.classList.remove("disconnected"); $(".sidebar-bottom").classList.remove("disconnected");
    $("#connection").textContent = "Сервер подключён";
    const simulated = state.device.mode === "simulation";
    $("#mode-badge").textContent = simulated ? "Режим симуляции" : "Linux · mpv";
    $("#device-state").textContent = "Виртуальные индикаторы";
    $("#catalog-note").textContent = simulated ? "Демонстрационные станции: звук не воспроизводится. Для настоящего радио включите host-режим." : "Звук играет на Linux-сервере с mpv. Сначала найдите станцию или добавьте свой URL.";
    $("#assistant-status").textContent = state.ai.active_model || "Локальные команды доступны";
    $("#auto-resume").checked = state.device.preferences.resume_after_reboot;
    $("#mic-muted").checked = state.device.preferences.microphone_muted;
    if (document.activeElement !== $("#wake-word")) $("#wake-word").value = state.device.preferences.wake_word;
    if (document.activeElement !== $("#ai-mode")) $("#ai-mode").value = state.ai.mode;
    $("#sim-network").hidden = !simulated;
    $("#ai-details").replaceChildren();
    const labels = {PRIMARY_LIVE:"Gemini Live",FALLBACK_FLASH_LITE:"Flash-Lite + Piper",OFFLINE_COMMANDS_ONLY:"Только локальные команды"};
    for (const text of ["Состояние: " + labels[state.ai.state],"Модель: " + (state.ai.active_model || "не активна"),"Причина: " + state.ai.reason,"Квота: нет достоверных данных"]){const p=document.createElement("p");p.textContent=text;$("#ai-details").append(p);}
    $("#device-details").textContent = "Профиль платы: не определён · Индикаторы: виртуальные · STT: " + (state.device.voice.stt_configured ? "настроен" : "не настроен") + " · TTS: " + (state.device.voice.tts_configured ? "настроен" : "не настроен");
    renderRadio(); applyLights();
  } catch(error) {
    document.body.classList.add("disconnected");$(".sidebar-bottom").classList.add("disconnected");
    $("#connection").textContent="Нет подключения";$("#mode-badge").textContent="Сервер недоступен";
    throw error;
  }
}
$("#record-command").onclick = act(async () => {
  if (!state.device?.voice.stt_configured) throw new Error("Сначала настройте VOSK_MODEL_PATH на сервере");
  if (state.device.preferences.microphone_muted) throw new Error("Микрофон выключен в приложении");
  if (!navigator.mediaDevices) throw new Error("Запись требует HTTPS или localhost");
  const button=$("#record-command");button.disabled=true;
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
    await answerAudio(reply);await refresh();
  } finally {processor?.disconnect();source?.disconnect();stream?.getTracks().forEach(t=>t.stop());if(context)await context.close();button.disabled=false;}
});
$("#today").textContent=new Date().toLocaleDateString("ru-RU",{day:"numeric",month:"long",weekday:"long"});
function clock(){const value=new Date().toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit"});$("#clock").textContent=value;$(".front-preview").textContent=value;}
clock();setInterval(clock,10000);
tab(location.hash.slice(1)||"home");
(async()=>{try{await refresh();await loadStations();renderEditor();}catch(error){toast(error.message);}})();
setInterval(()=>refresh().catch(()=>{}),2500);
