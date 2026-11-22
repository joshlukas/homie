// Dokumente – der Dokumentstream. Ein Abruf holt die Liste aller Dokumente; gezeichnet wird nur, was gerade in der Nähe ist.
// Im Browser wird nichts gespeichert außer der gewählten Ansicht.
(() => {
  const $ = (s) => document.querySelector(s);
  const rolle = $("#rolle"), lineal = $("#lineal"), zeiger = $("#zeiger"), wand = $("#wand"), buehne = $("#buehne");
  const meldung = $("#meldung"), suche = $("#suche"), filter = $("#filter"), aktivLeiste = $("#aktiv"), leser = $("#leser");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const MON = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
  const MONAT = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
  const NAH = 2, FERN = 8;          // so viele Dokumente um das aktuelle sind gezeichnet bzw. bleiben es
  const GRUPPEN = [["jahr", "Jahr"], ["art", "Art"], ["von", "Absender"], ["tag", "Schlagwort"]];

  let A = [], S = [], archiv = "", aktiv = 0, ziel = 0, zielBis = 0, gezeichnet = new Set();
  let ansicht = "strom", frage = "", F = {}, voll = new Map(), suchlauf = 0, wandBis = 0, wandWaechter = null;
  try { ansicht = localStorage.getItem("dokumente.ansicht") === "raster" ? "raster" : "strom"; } catch (e) {}

  const tagText = (d) => {
    if (!d) return "ohne Datum";
    const [j, m, t] = d.split("-").map(Number);
    return `${t}. ${MONAT[m - 1] || ""} ${j}`;
  };
  const neuSeit = (d) => d.neu && (Date.now() - new Date(d.neu + "T12:00").getTime()) < 7 * 864e5;
  const bild = (d) => `/m/dokumente/vorschau/${d.id}`;
  const pdf = (d, laden) => `/m/dokumente/pdf/${d.id}${laden ? "?laden=1" : ""}`;

  // ---------- Laden ----------
  async function start() {
    let j;
    try { j = await (await fetch("/api/dokumente", {cache: "no-store"})).json(); } catch (e) { j = {fehler: "Homie ist gerade nicht erreichbar."}; }
    if (j.fehler || !j.dokumente || !j.dokumente.length) {
      meldung.textContent = j.fehler || "Im Archiv liegen noch keine Dokumente.";
      $("#sub").textContent = "";
      return;
    }
    archiv = j.archiv || "";
    A = j.dokumente;
    for (const d of A) d._t = [d.titel, d.von, d.art, d.tags.join(" "), d.datum, tagText(d.datum)].join(" ").toLowerCase();
    filterBauen();
    const merk = location.hash.startsWith("#d") ? Number(location.hash.slice(2)) : 0;
    anwenden(merk);
    ansichtSetzen(ansicht, false);
    rolle.addEventListener("scroll", () => requestAnimationFrame(stand), {passive: true});
    addEventListener("resize", () => { linealBauen(); stand(); }, {passive: true});
  }

  // ---------- Filter und Suche ----------
  function passt(d, worte) {
    if (F.jahr && d.datum.slice(0, 4) !== F.jahr) return false;
    if (F.art && d.art !== F.art) return false;
    if (F.von && d.von !== F.von) return false;
    if (F.tag && !d.tags.includes(F.tag)) return false;
    if (F.eingang && !d.eingang) return false;
    return !worte.length || worte.every((w) => d._t.includes(w)) || voll.has(d.id);
  }

  function anwenden(behalte) {
    const worte = frage.toLowerCase().split(/\s+/).filter(Boolean);
    const vorher = behalte || (S[aktiv] && S[aktiv].id);
    S = A.filter((d) => passt(d, worte));
    const zahl = S.length === A.length ? `${A.length} Dokumente` : `${S.length} von ${A.length} Dokumenten`;
    const spanne = S.length ? ` · ${tagText(S[S.length - 1].datum).replace(/^\d+\. /, "")} bis ${tagText(S[0].datum).replace(/^\d+\. /, "")}` : "";
    $("#sub").textContent = zahl + spanne;
    aktivZeichnen();
    meldung.hidden = S.length > 0;
    if (!S.length) { meldung.textContent = "Dazu gibt es keine Dokumente."; buehne.hidden = wand.hidden = true; return; }
    gezeichnet.clear();
    rolle.innerHTML = S.map((_, i) => `<section class="dok" data-i="${i}"></section>`).join("");
    waechter.disconnect();
    for (const s of rolle.children) waechter.observe(s);
    linealBauen();
    wandBauen();
    ansichtSetzen(ansicht, false);
    const i = Math.max(0, S.findIndex((d) => d.id === vorher));
    aktiv = -1;
    gehe(i, false);
    stand();
  }

  function filterBauen() {
    const zaehle = (werte) => { const m = new Map(); for (const w of werte) if (w) m.set(w, (m.get(w) || 0) + 1); return m; };
    const listen = {
      jahr: [...zaehle(A.map((d) => d.datum.slice(0, 4)))].sort((a, b) => b[0].localeCompare(a[0])),
      art: [...zaehle(A.map((d) => d.art))].sort((a, b) => b[1] - a[1]),
      von: [...zaehle(A.map((d) => d.von))].sort((a, b) => b[1] - a[1]).slice(0, 60),
      tag: [...zaehle(A.flatMap((d) => d.tags))].sort((a, b) => b[1] - a[1]).slice(0, 60),
    };
    const eingang = A.filter((d) => d.eingang).length;
    filter.innerHTML = (eingang ? `<h2>Schnell</h2><div><button type="button" class="wahl" data-f="eingang" data-w="1" aria-pressed="false">Posteingang <small>${eingang}</small></button></div>` : "")
      + GRUPPEN.filter(([k]) => listen[k].length).map(([k, titel]) => `<h2>${titel}</h2><div>` + listen[k].map(([w, n]) =>
        `<button type="button" class="wahl" data-f="${k}" data-w="${esc(w)}" aria-pressed="false">${esc(w)} <small>${n}</small></button>`).join("") + "</div>").join("");
  }

  function waehle(k, w) {
    F[k] = F[k] === w ? null : w;
    anwenden();
  }

  function aktivZeichnen() {
    const an = Object.entries(F).filter(([, w]) => w);
    aktivLeiste.hidden = !an.length && !frage;
    aktivLeiste.innerHTML = an.map(([k, w]) => `<button type="button" class="wahl" data-f="${k}" data-w="${esc(w)}" title="Filter entfernen">${k === "eingang" ? "Posteingang" : esc(w)} <small>✕</small></button>`).join("")
      + (frage ? `<button type="button" class="wahl" data-leeren="1" title="Suche leeren">„${esc(frage)}“ <small>✕</small></button>` : "");
    for (const b of filter.querySelectorAll(".wahl")) b.setAttribute("aria-pressed", String(F[b.dataset.f] === b.dataset.w));
    const n = an.length;
    $("#filterknopf").innerHTML = "Filter" + (n ? ` <b>${n}</b>` : "");
  }

  let wartet = 0;
  suche.addEventListener("input", () => {
    frage = suche.value.trim();
    voll = new Map();
    anwenden();
    clearTimeout(wartet);
    if (frage.length < 3) return;
    const lauf = ++suchlauf;     // Volltext des Archivs: kommt kurz nach dem Tippen dazu
    wartet = setTimeout(async () => {
      try {
        const j = await (await fetch("/api/dokumente/suche?q=" + encodeURIComponent(frage))).json();
        if (lauf !== suchlauf || !j.treffer) return;
        voll = new Map(j.treffer.map((t) => [t.id, t.auszug]));
        anwenden();
      } catch (e) {}
    }, 280);
  });

  // ---------- Stream ----------
  const marke = (text) => {
    const worte = frage.toLowerCase().split(/\s+/).filter((w) => w.length > 1);
    let aus = esc(text);
    for (const w of worte) aus = aus.replace(new RegExp("(" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")(?![^<]*>)", "gi"), "<mark>$1</mark>");
    return aus;
  };

  function zeichne(i) {
    const s = rolle.children[i], d = S[i];
    if (!s || !d || gezeichnet.has(i)) return;
    gezeichnet.add(i);
    const zeile = [tagText(d.datum), d.von && `<span class="tag" data-f="von" data-w="${esc(d.von)}">${marke(d.von)}</span>`,
      d.art && `<span class="tag" data-f="art" data-w="${esc(d.art)}">${marke(d.art)}</span>`, d.seiten > 1 && `${d.seiten} Seiten`].filter(Boolean).join(" · ");
    const marken = [neuSeit(d) && `<span class="tag neu">neu</span>`, d.eingang && `<span class="tag eingang" data-f="eingang" data-w="1">Posteingang</span>`,
      ...d.tags.map((t) => `<span class="tag" data-f="tag" data-w="${esc(t)}">${marke(t)}</span>`)].filter(Boolean).join("");
    s.innerHTML = `<div class="blatt" data-lesen="${i}" title="Lesen"><img alt="Erste Seite: ${esc(d.titel)}" decoding="async"></div>
      <div class="fuss"><div><b>${marke(d.titel)}</b><small>${zeile}</small>${marken ? `<small>${marken}</small>` : ""}
      ${voll.get(d.id) ? `<small class="auszug">… ${marke(voll.get(d.id))} …</small>` : ""}</div>
      <div class="knoepfe"><button type="button" class="knopf stark" data-lesen="${i}">${d.seiten > 1 ? "Alle Seiten lesen" : "Lesen"}</button>
      <a class="knopf" href="${pdf(d, true)}" download>Laden</a></div></div>`;
    const img = s.querySelector("img");
    img.onload = () => img.classList.add("da");
    img.onerror = () => img.replaceWith(Object.assign(document.createElement("span"), {className: "leer", textContent: "Keine Vorschau"}));
    img.src = bild(d);
  }

  const waechter = new IntersectionObserver((es) => {
    for (const e of es) if (e.isIntersecting) zeichne(Number(e.target.dataset.i));
  }, {root: rolle, rootMargin: "150% 0px"});

  function linealBauen() {
    lineal.querySelectorAll("i,span").forEach((x) => x.remove());
    const h = lineal.clientHeight, n = S.length;
    let letzterMonat = "", letztesJahr = "", yMonat = -99, yJahr = -99, html = "";
    S.forEach((d, i) => {
      const y = n > 1 ? 30 + i / (n - 1) * (h - 60) : h / 2, jahr = d.datum.slice(0, 4), monat = d.datum.slice(0, 7);
      if (jahr !== letztesJahr) { letztesJahr = jahr; if (y - yJahr > 16) { html += `<i class="jahr" style="top:${y}px"></i><span class="jahr" style="top:${y}px">${jahr || "?"}</span>`; yJahr = y; yMonat = y + 8; } }
      if (monat !== letzterMonat) { letzterMonat = monat; if (y - yMonat > 13 && y - yJahr > 13) { html += `<i style="top:${y}px"></i><span style="top:${y}px">${MON[Number(monat.slice(5)) - 1] || ""}</span>`; yMonat = y; } }
    });
    lineal.insertAdjacentHTML("afterbegin", html);
  }

  function stand() {
    if (!S.length || buehne.hidden) return;
    const jetzt = Math.max(0, Math.min(S.length - 1, Math.round(rolle.scrollTop / rolle.clientHeight)));
    if (jetzt === aktiv) return;
    rolle.children[aktiv]?.classList.remove("vorn");
    aktiv = jetzt;
    const d = S[aktiv], h = lineal.clientHeight, y = S.length > 1 ? 30 + aktiv / (S.length - 1) * (h - 60) : h / 2;
    for (let i = aktiv - NAH; i <= aktiv + NAH; i++) zeichne(i);
    rolle.children[aktiv].classList.add("vorn");
    zeiger.hidden = false;
    zeiger.style.transform = `translateY(calc(${y}px - 50%))`;
    zeiger.innerHTML = `${d.datum ? MON[Number(d.datum.slice(5, 7)) - 1] + " " + d.datum.slice(0, 4) : "?"}<small>${aktiv + 1} / ${S.length}</small>`;
    lineal.setAttribute("aria-valuetext", tagText(d.datum));
    $("#hoch").disabled = aktiv === 0;
    $("#runter").disabled = aktiv === S.length - 1;
    clearTimeout(stand.t);
    stand.t = setTimeout(() => {
      history.replaceState(null, "", "#d" + d.id);
      for (const k of [...gezeichnet]) if (Math.abs(k - aktiv) > FERN) { rolle.children[k].innerHTML = ""; gezeichnet.delete(k); }   // weit Entferntes wieder freigeben
    }, 260);
  }

  function gehe(i, weich = true) {
    i = Math.max(0, Math.min(S.length - 1, i));
    ziel = i; zielBis = Date.now() + 700;       // schnelle Tastenfolgen zählen vom Ziel aus weiter, nicht von der laufenden Bewegung
    for (let k = i - 1; k <= i + 1; k++) zeichne(k);
    // weite Sprünge (Anfang, Ende, Lineal) ohne Fahrt – sonst rauscht alles dazwischen durchs Bild
    rolle.scrollTo({top: i * rolle.clientHeight, behavior: weich && Math.abs(i - Math.max(0, aktiv)) <= 3 ? "smooth" : "auto"});
  }
  const von = () => (Date.now() < zielBis ? ziel : Math.max(0, aktiv));

  function linealZu(e) {
    const r = lineal.getBoundingClientRect(), f = Math.max(0, Math.min(1, (e.clientY - r.top - 30) / (r.height - 60)));
    gehe(Math.round(f * (S.length - 1)), false);
  }
  lineal.addEventListener("pointerdown", (e) => { lineal.setPointerCapture(e.pointerId); linealZu(e); });
  lineal.addEventListener("pointermove", (e) => { if (e.buttons || e.pointerType === "touch") linealZu(e); });

  // ---------- Raster: Monat für Monat, in Portionen nachgeladen ----------
  function wandBauen() {
    wand.innerHTML = "";
    wandBis = 0;
    wandWaechter?.disconnect();
    wandMehr();
  }
  function wandMehr() {
    const bis = Math.min(S.length, wandBis + 120);
    let html = "", monat = wandBis ? S[wandBis - 1].datum.slice(0, 7) : "";
    for (let i = wandBis; i < bis; i++) {
      const d = S[i], m = d.datum.slice(0, 7);
      if (m !== monat) { monat = m; html += `<h2>${m ? MONAT[Number(m.slice(5)) - 1] + " " + m.slice(0, 4) : "Ohne Datum"}</h2>`; }
      html += `<button type="button" class="kachel" data-i="${i}"><img src="${bild(d)}" alt="" loading="lazy" decoding="async"><b>${marke(d.titel)}</b>
        <small>${esc([d.von, d.art].filter(Boolean).join(" · ") || tagText(d.datum))}</small></button>`;
    }
    wand.insertAdjacentHTML("beforeend", html);
    wandBis = bis;
    if (bis < S.length) {
      wandWaechter = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { wandWaechter.disconnect(); wandMehr(); } }, {root: wand, rootMargin: "800px 0px"});
      wandWaechter.observe(wand.lastElementChild);
    }
  }

  function ansichtSetzen(neu, merken = true) {
    ansicht = neu;
    if (merken) try { localStorage.setItem("dokumente.ansicht", neu); } catch (e) {}
    for (const b of document.querySelectorAll("[data-ansicht]")) b.setAttribute("aria-pressed", String(b.dataset.ansicht === neu));
    if (!S.length) return;
    buehne.hidden = neu !== "strom";
    wand.hidden = neu !== "raster";
    if (neu === "strom") { linealBauen(); const i = Math.max(0, aktiv); aktiv = -1; rolle.scrollTo({top: i * rolle.clientHeight}); stand(); rolle.focus({preventScroll: true}); }
    else wand.querySelector(`[data-i="${Math.max(0, aktiv)}"]`)?.scrollIntoView({block: "center"});
  }

  // ---------- Leser ----------
  function lesen(i) {
    const d = S[i];
    if (!d) return;
    if (navigator.pdfViewerEnabled === false) { window.open(pdf(d), "_blank", "noopener"); return; }   // z. B. am Handy: dort öffnet das System das PDF
    $("#lesertitel").textContent = d.titel;
    $("#leserzeile").textContent = [tagText(d.datum), d.von, d.art, d.seiten > 1 && d.seiten + " Seiten"].filter(Boolean).join(" · ");
    $("#leserladen").href = pdf(d, true);
    $("#leserarchiv").href = archiv ? `${archiv}/documents/${d.id}/details` : "#";
    $("#leserarchiv").hidden = !archiv;
    $("#leserblatt").src = pdf(d) + "#view=FitH";
    leser.showModal();
  }
  leser.addEventListener("close", () => { $("#leserblatt").src = "about:blank"; rolle.focus({preventScroll: true}); });
  leser.addEventListener("click", (e) => { if (e.target === leser) leser.close(); });
  $("#leserzu").addEventListener("click", () => leser.close());

  // ---------- Bedienung ----------
  document.addEventListener("click", (e) => {
    const l = e.target.closest("[data-lesen]");
    if (l) return lesen(Number(l.dataset.lesen));
    const w = e.target.closest("[data-f]");
    if (w) return waehle(w.dataset.f, w.dataset.w);
    if (e.target.closest("[data-leeren]")) { suche.value = ""; suche.dispatchEvent(new Event("input")); return; }
    const k = e.target.closest(".kachel");
    if (k) { aktiv = Number(k.dataset.i); ansichtSetzen("strom"); return; }
    const a = e.target.closest("[data-ansicht]");
    if (a) return ansichtSetzen(a.dataset.ansicht);
  });
  $("#hoch").addEventListener("click", () => gehe(von() - 1));
  $("#runter").addEventListener("click", () => gehe(von() + 1));
  const filterKlappen = (auf) => {
    filter.hidden = auf === undefined ? !filter.hidden : !auf;
    $("#filterknopf").setAttribute("aria-expanded", String(!filter.hidden));
    requestAnimationFrame(() => { linealBauen(); if (ansicht === "strom" && S.length) { const i = Math.max(0, aktiv); aktiv = -1; rolle.scrollTo({top: i * rolle.clientHeight}); stand(); } });
  };
  $("#filterknopf").addEventListener("click", () => filterKlappen());

  addEventListener("keydown", (e) => {
    if (leser.open || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target === suche) {
      if (e.key === "Escape") { if (suche.value) { suche.value = ""; suche.dispatchEvent(new Event("input")); } else suche.blur(); }
      if (e.key === "Enter" || e.key === "ArrowDown") { e.preventDefault(); suche.blur(); rolle.focus({preventScroll: true}); }
      return;
    }
    if (e.key === "/") { e.preventDefault(); suche.focus(); suche.select(); return; }
    if (e.key === "?") { $("#hilfe").hidden = !$("#hilfe").hidden; return; }
    if (e.key === "Escape") { $("#hilfe").hidden = true; if (!filter.hidden) filterKlappen(false); return; }
    if (e.key === "g" || e.key === "G") return ansichtSetzen(ansicht === "strom" ? "raster" : "strom");
    if (e.key === "f" || e.key === "F") return filterKlappen();
    if (ansicht !== "strom" || !S.length) return;
    const weiter = {ArrowDown: 1, PageDown: 1, " ": 1, j: 1, ArrowUp: -1, PageUp: -1, k: -1}[e.key];
    if (weiter) { e.preventDefault(); gehe(von() + weiter); }
    else if (e.key === "Home") gehe(0);
    else if (e.key === "End") gehe(S.length - 1);
    else if (e.key === "Enter" || e.key === "o") lesen(Math.max(0, aktiv));
  });

  document.querySelector(".menue [aria-current]")?.scrollIntoView({inline: "center", block: "nearest"});
  start();
})();
