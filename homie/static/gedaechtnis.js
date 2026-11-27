"use strict";
// Gedächtnis – stellt Fragen an das eigene Gedächtnis und gibt getippte Notizen ab.
// Die Fragen dieser Sitzung bleiben nur in diesem Browser-Tab stehen (sessionStorage); Homie speichert nichts.
const $ = (id) => document.getElementById(id);
const csrf = $("frageform").dataset.csrf;
const MERK = "homie-gedaechtnis";
let verlauf = [];
try { verlauf = JSON.parse(sessionStorage.getItem(MERK) || "[]"); } catch (_) { verlauf = []; }

function el(art, klasse, text) {
  const e = document.createElement(art);
  if (klasse) e.className = klasse;
  if (text != null) e.textContent = text;
  return e;
}
function merken() {
  verlauf = verlauf.slice(0, 20);
  try { sessionStorage.setItem(MERK, JSON.stringify(verlauf)); } catch (_) {}
}
async function senden(pfad, inhalt, art) {
  let r;
  try {
    r = await fetch(pfad, {method: "POST", body: inhalt, signal: AbortSignal.timeout(160000), headers: {"Content-Type": art, "X-Homie-CSRF": csrf}});
  } catch (_) { throw new Error("Keine Verbindung zu Homie. Bist du im Heimnetz oder VPN?"); }
  const j = await r.json().catch(() => null);
  if (!j || r.redirected) throw new Error("Bitte in Homie neu anmelden (Seite neu laden).");
  if (!r.ok || !j.ok) throw new Error(j.fehler || "Fehler " + r.status);
  return j;
}

function karte(e) {
  const a = el("article", "glas antwort" + (e.fehler ? " fehler" : ""));
  a.append(el("p", "gefragt", e.frage));
  if (e.laeuft) { a.append(el("p", "wartet", e.laeuft)); return a; }
  if (e.fehler) { a.append(el("p", "text", e.fehler)); return a; }
  a.append(el("p", "text", e.antwort || "Dazu habe ich nichts gefunden."));
  const claude = e.weg === "claude";
  const woher = el("p", "woher");
  woher.append(el("span", "chip " + (claude ? "claude" : "lokal"), claude ? "Über Claude beantwortet" : "Lokal beantwortet"));
  const neben = [];
  if (!claude && e.gefunden && !e.sicher) neben.push("nicht ganz sicher");
  if (e.hinweis) neben.push(e.hinweis);
  if (e.sekunden != null) neben.push(e.sekunden + " s");
  if (neben.length) woher.append(el("span", "neben", neben.join(" · ")));
  a.append(woher);
  if (e.quellen && e.quellen.length) {
    const d = el("details", "fundstellen");
    d.append(el("summary", "", e.quellen.length === 1 ? "1 Fundstelle" : e.quellen.length + " Fundstellen"));
    const ul = el("ul");
    for (const q of e.quellen) {
      const li = el("li"), kopf = el("div", "fkopf");
      kopf.append(el("span", "chip", q.art));
      kopf.append(el("b", "", q.titel || q.art));
      if (q.datum) kopf.append(el("span", "datum", q.datum));
      li.append(kopf);
      if (q.ausschnitt) li.append(el("p", "ausschnitt", q.ausschnitt));
      if (q.link) { const l = el("a", "", "Dokument öffnen"); l.href = q.link; l.target = "_blank"; l.rel = "noopener noreferrer"; li.append(l); }
      ul.append(li);
    }
    d.append(ul); a.append(d);
  }
  if (!claude) {
    const z = el("div", "nachfragen"), k = el("button", "leise", "Claude fragen");
    k.type = "button";
    k.addEventListener("click", () => fragen(e.frage, true, e));
    z.append(k, el("small", "", "Stellt dieselbe Frage noch einmal an Claude. Die Frage und die Fundstellen verlassen dabei dein Heimnetz."));
    a.append(z);
  }
  return a;
}
function zeigen() {
  $("antworten").replaceChildren(...verlauf.map(karte));
  $("leeren-zeile").hidden = !verlauf.some((e) => !e.laeuft);
}

let beschaeftigt = false;
async function fragen(frage, claude, ersetzt) {
  if (beschaeftigt) return;
  beschaeftigt = true; $("fragen").disabled = true;
  const eintrag = {frage, laeuft: claude ? "Claude wird gefragt …" : "Ich suche und denke nach – das dauert ein paar Sekunden …"};
  const stelle = ersetzt ? verlauf.indexOf(ersetzt) : -1;
  if (stelle >= 0) verlauf[stelle] = eintrag; else verlauf.unshift(eintrag);
  zeigen();
  let ergebnis;
  try {
    const j = await senden("/m/gedaechtnis/frage", JSON.stringify({frage, claude}), "application/json");
    ergebnis = {frage, antwort: j.antwort, gefunden: j.gefunden, sicher: j.sicher, weg: j.weg, hinweis: j.hinweis, sekunden: j.sekunden, quellen: j.quellen};
  } catch (f) {
    // Schlägt die Nachfrage bei Claude fehl, bleibt die lokale Antwort stehen
    ergebnis = ersetzt && claude ? ersetzt : {frage, fehler: f.message};
    if (ersetzt && claude) $("fragelage").textContent = "Claude nicht erreicht: " + f.message;
  }
  verlauf[verlauf.indexOf(eintrag)] = ergebnis;
  merken(); zeigen();
  beschaeftigt = false; $("fragen").disabled = false;
}

$("frageform").addEventListener("submit", (e) => {
  e.preventDefault();
  const frage = $("frage").value.trim();
  if (frage.length < 3 || beschaeftigt) return;
  $("fragelage").textContent = "";
  $("frage").value = "";
  fragen(frage, false, null);
});
$("leeren").addEventListener("click", () => { verlauf = verlauf.filter((e) => e.laeuft); merken(); zeigen(); });

$("notizform").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("notiz").value.trim(), lage = $("notizlage"), knopf = $("notizsenden");
  if (text.length < 3) { lage.textContent = "Bitte erst etwas schreiben."; lage.className = "lage warn"; return; }
  // Der Assistent nimmt höchstens 20.000 Bytes an; das Feld zählt Zeichen (ein Umlaut sind zwei Bytes).
  if (new TextEncoder().encode(text).length > 20000) {
    lage.textContent = "Die Notiz ist zu lang (höchstens etwa 20.000 Zeichen; Umlaute zählen doppelt). Bitte kürzen oder teilen.";
    lage.className = "lage warn"; return;
  }
  knopf.disabled = true; lage.textContent = "Sende …"; lage.className = "lage";
  try {
    await senden("/m/gedaechtnis/notiz", text, "text/plain; charset=utf-8");
    $("notiz").value = "";
    lage.textContent = "Gespeichert. Die Notiz wird in etwa zwei Minuten ausgewertet und steht dann in „Mein Tag“; im Gedächtnis ist sie bis zu zehn Minuten später.";
    lage.className = "lage gut";
  } catch (f) { lage.textContent = "Nicht gespeichert: " + f.message; lage.className = "lage schlecht"; }
  knopf.disabled = false;
});

verlauf = verlauf.filter((e) => !e.laeuft);
zeigen();
