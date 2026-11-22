"use strict";
// Aufnahme – nimmt im Browser auf, sichert alle paar Sekunden im Gerät und gibt die Aufnahme an Homie ab.
// Was nicht gleich ankommt, bleibt im Gerät und wird nachgesendet.
const $ = id => document.getElementById(id);
const knopf = $("knopf"), lage = $("lage"), zeitEl = $("zeit");
let rec = null, strom = null, beginn = 0, ticker = 0, laufendId = null, teile = [], audioCtx = null, wach = null, sendet = false;

function melde(text, art) { lage.textContent = text; lage.className = art || ""; }

// ---------- Zwischenspeicher im Handy (IndexedDB) ----------
function dbOeffnen() {
  return new Promise((ja, nein) => {
    const r = indexedDB.open("sprachnotiz", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("aufnahmen", {keyPath: "id"});
    r.onsuccess = () => ja(r.result); r.onerror = () => nein(r.error);
  });
}
async function speicher(modus, fn) {
  const d = await dbOeffnen();
  return new Promise((ja, nein) => {
    const t = d.transaction("aufnahmen", modus); const q = fn(t.objectStore("aufnahmen"));
    t.oncomplete = () => { d.close(); ja(q && q.result); }; t.onerror = t.onabort = () => { d.close(); nein(t.error); };
  });
}
const ablegen = satz => speicher("readwrite", s => s.put(satz));
const loeschen = id => speicher("readwrite", s => s.delete(id));
const alle = () => speicher("readonly", s => s.getAll());

// ---------- Display anlassen, solange die Seite offen ist ----------
async function wachHalten() {
  if (!("wakeLock" in navigator) || document.visibilityState !== "visible") return;
  try {
    wach = await navigator.wakeLock.request("screen");
    $("wach").textContent = "Display bleibt an, solange diese Seite offen ist.";
    wach.addEventListener("release", () => { wach = null; });
  } catch (_) { $("wach").textContent = "Display-an wird von diesem Browser gerade nicht erlaubt."; }
}

// ---------- Aufnahme ----------
function format() {
  for (const f of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"])
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(f)) return f;
  return "";
}
function uhr() {
  const s = Math.floor((Date.now() - beginn) / 1000);
  zeitEl.textContent = Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}
function pegelStart() {
  try {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const an = audioCtx.createAnalyser(); an.fftSize = 512;
    audioCtx.createMediaStreamSource(strom).connect(an);
    const buf = new Uint8Array(an.fftSize);
    const lauf = () => {
      if (!rec) { knopf.style.setProperty("--pegel", 0); return; }
      an.getByteTimeDomainData(buf);
      let max = 0; for (const v of buf) max = Math.max(max, Math.abs(v - 128));
      knopf.style.setProperty("--pegel", Math.min(1, max / 60).toFixed(2));
      requestAnimationFrame(lauf);
    };
    lauf();
  } catch (_) {}
}
async function starten() {
  if (rec) return;
  if (!navigator.mediaDevices || !window.MediaRecorder) return melde("Dieser Browser kann nicht aufnehmen.", "schlecht");
  knopf.disabled = true;
  try {
    strom = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
  } catch (e) {
    knopf.disabled = false;
    return melde(e.name === "NotAllowedError" ? "Mikrofon ist nicht erlaubt. Bitte in den Seiteneinstellungen freigeben."
                                              : "Mikrofon nicht verfügbar: " + e.name, "schlecht");
  }
  const typ = format();
  rec = new MediaRecorder(strom, typ ? {mimeType: typ, audioBitsPerSecond: 48000} : {});
  beginn = Date.now(); laufendId = beginn; teile = [];
  rec.ondataavailable = e => {
    if (!e.data || !e.data.size) return;
    teile.push(e.data);
    // alle paar Sekunden sichern: Auch wenn die Seite abstürzt, bleibt die Aufnahme bis hierhin erhalten
    ablegen({id: laufendId, zeit: laufendId / 1000, typ: rec ? rec.mimeType : typ, teile: teile.slice(), fertig: false}).catch(() => {});
  };
  rec.onstop = fertig;
  rec.start(4000);
  knopf.disabled = false; knopf.classList.add("laeuft"); knopf.textContent = "Stopp";
  melde("Aufnahme läuft …");
  ticker = setInterval(uhr, 250); uhr(); pegelStart(); wachHalten();
}
function stoppen() { if (rec && rec.state !== "inactive") { knopf.disabled = true; rec.stop(); } }
async function fertig() {
  const typ = rec.mimeType || format() || "audio/webm", id = laufendId, dauer = (Date.now() - beginn) / 1000, stuecke = teile;
  clearInterval(ticker); strom.getTracks().forEach(t => t.stop());
  if (audioCtx) { audioCtx.close().catch(() => {}); audioCtx = null; }
  rec = null; strom = null; laufendId = null; teile = [];
  knopf.disabled = false; knopf.classList.remove("laeuft"); knopf.textContent = "Aufnehmen";
  if (dauer < 1 || !stuecke.length) { await loeschen(id).catch(() => {}); zeitEl.textContent = "0:00"; return melde("Verworfen – kürzer als eine Sekunde."); }
  try { await ablegen({id, zeit: id / 1000, typ, teile: stuecke, fertig: true}); }
  catch (e) { return melde("Konnte die Aufnahme nicht im Handy sichern: " + e, "schlecht"); }
  melde("Gesichert. Sende …");
  senden();
}

// ---------- Senden und Nachsenden ----------
async function senden() {
  if (sendet) return; sendet = true;
  let gesendet = 0, offen = 0, grund = "";
  try {
    for (const a of (await alle()).sort((x, y) => x.id - y.id)) {
      if (a.id === laufendId) continue;
      const blob = new Blob(a.teile, {type: a.typ});
      if (blob.size < 2000) { await loeschen(a.id); continue; }
      try {
        const r = await fetch("/m/aufnahme/senden", {method: "POST", body: blob, signal: AbortSignal.timeout(150000),
          headers: {"Content-Type": a.typ.split(";")[0], "X-Aufnahme-Zeit": String(Math.round(a.zeit)), "X-Homie-CSRF": document.body.dataset.csrf}});
        const j = await r.json().catch(() => null);
        if (r.ok && j && j.ok) { await loeschen(a.id); gesendet++; }
        else if (!j || r.redirected) { offen++; grund = "bitte in Homie neu anmelden"; }      // Anmeldung abgelaufen: Aufnahme bleibt im Gerät
        else { offen++; grund = j.fehler || ("Antwort " + r.status); }
      } catch (_) { offen++; grund = "keine Verbindung zum Heimnetz"; }
    }
  } finally { sendet = false; }
  $("wartend").hidden = $("nachsenden").hidden = !offen;
  if (offen) $("wartend").textContent = offen + (offen === 1 ? " Aufnahme wartet" : " Aufnahmen warten") + " im Handy (" + grund + ").";
  if (!rec) {
    if (gesendet && !offen) melde(gesendet === 1 ? "Gesendet. Die Auswertung erscheint in ein bis zwei Minuten in „Mein Tag“."
                                                 : gesendet + " Aufnahmen gesendet.", "gut");
    else if (offen && (gesendet || lage.textContent.startsWith("Gesichert"))) melde("Im Handy gesichert. Wird nachgesendet, sobald du im Heimnetz oder VPN bist.", "warn");
  }
}

knopf.addEventListener("click", () => rec ? stoppen() : starten());
$("nachsenden").addEventListener("click", senden);
addEventListener("online", senden);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") { wachHalten(); senden(); } });
setInterval(() => { if (document.visibilityState === "visible" && !rec) senden(); }, 30000);
if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
wachHalten();
senden();
// Über das Startbildschirm-Symbol geöffnet: sofort aufnehmen, wenn das Mikrofon schon erlaubt ist
if (new URLSearchParams(location.search).get("start") === "1" && navigator.permissions) {
  navigator.permissions.query({name: "microphone"}).then(p => { if (p.state === "granted") starten(); }).catch(() => {});
}
