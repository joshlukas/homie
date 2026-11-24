// „Mein Tag“ – zeichnet die Seite aus einem einzigen Abruf (/api/tag). Nichts wird im Browser gespeichert außer der Ansichtswahl.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fmtDay = (iso) => new Date(iso + "T12:00").toLocaleDateString("de-DE", {weekday: "short", day: "2-digit", month: "2-digit"});
const fmtTime = (iso) => new Date(iso).toLocaleString("de-DE", {weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"});
const eur = (n) => n.toLocaleString("de-DE", {style: "currency", currency: "EUR"});
const today = () => new Date().toLocaleDateString("sv-SE");
let days = 7;
try { days = Number(localStorage.getItem("meintag.tage")) || 7; } catch (e) {}

function card(title, color, rows, opts = {}) {
  const body = rows.length ? `<ul>${rows.join("")}</ul>` : `<p class="empty">${esc(opts.empty || "Nichts im gewählten Zeitraum.")}</p>`;
  return `<article class="card${opts.wide ? " wide" : ""}${opts.cls ? " " + opts.cls : ""}" style="--c:${color}"><h2><i></i>${esc(title)}${opts.note ? `<em>${esc(opts.note)}</em>` : ""}</h2>${opts.extra || ""}${body}</article>`;
}
const row = (e, extra = "") => `<li>${esc(e.text)}${extra}${e.daten && e.daten.cospend ? `<div class="antwort">Cospend: ${esc(e.daten.cospend)}</div>` : ""}<small>${fmtTime(e.zeit)}</small></li>`;

function render(d) {
  const E = d.eintraege || [], by = (t) => E.filter((e) => e.typ === t), t0 = today();
  $("#errors").innerHTML = (d.fehler || []).map((f) => `<p class="err">${esc(f)}</p>`).join("");
  const aufnahmen = by("aufnahme"), aufgaben = by("aufgabe"), essen = by("essen"), einkauf = by("einkauf"), sport = by("sport");
  const geld = [...essen, ...einkauf].reduce((s, e) => s + (e.daten.betrag_eur || 0), 0);
  const minuten = sport.reduce((s, e) => s + (e.daten.dauer_min || 0), 0), km = sport.reduce((s, e) => s + (e.daten.distanz_km || 0), 0);
  $("#sub").textContent = `${aufnahmen.length} Aufnahmen und Fotos · ${d.tage === 1 ? "heute" : "letzte " + d.tage + " Tage"}`;
  const nf = (n, digits = 0) => n.toLocaleString("de-DE", {maximumFractionDigits: digits});
  const cards = [];
  const C = d.claude;
  if (C) {
    const usd = (v) => nf(v, 2) + " $", max = Math.max(...C.tage.map((t) => t.usd), 0.01);
    const balken = C.tage.map((t) => `<span title="${fmtDay(t.tag)}: ${nf(t.usd, 2)} $, ${t.aufrufe} Aufrufe" style="flex:1;align-self:flex-end;min-height:2px;height:${Math.round(t.usd / max * 100)}%;background:var(--accent);border-radius:3px 3px 0 0;opacity:${t.tag === C.heute.tag ? 1 : .55}"></span>`).join("");
    const modelle = Object.entries(C.modelle_30_tage || {}).sort((a, b) => b[1].usd - a[1].usd);
    const voll = C.heute.usd >= C.tageslimit;
    cards.push(card("Claude-Guthaben", "var(--accent)", [
      `<li>Guthaben, errechnet<span class="tag">${C.guthaben == null ? "kein Ausgangswert" : usd(C.guthaben)}</span><small>${C.anker ? "Console zeigte " + usd(C.anker.guthaben) + " am " + fmtDay(C.anker.stand.slice(0, 10)) + "; seitdem gezählte Kosten abgezogen" : ""}</small></li>`,
      `<li>Heute ausgegeben<span class="tag${voll ? " late" : ""}">${usd(C.heute.usd)} von ${usd(C.tageslimit)}</span><small>${C.heute.aufrufe} Aufrufe${voll ? " · Tageslimit erreicht, Claude pausiert bis morgen" : ""}</small></li>`,
      `<li>Insgesamt seit Beginn<span class="tag">${usd(C.gesamt.usd)}</span><small>${C.gesamt.aufrufe} Aufrufe</small></li>`,
      ...modelle.map(([m, w]) => `<li>${esc(m)}<span class="tag">${usd(w.usd)}</span><small>${w.aufrufe} Aufrufe in 30 Tagen</small></li>`),
    ], {note: C.aktiv ? "geschätzt aus der Nutzung" : "Claude ist abgeschaltet",
        extra: `<div style="display:flex;gap:3px;height:54px;margin:4px 0 10px" aria-label="Kosten der letzten 14 Tage">${balken}</div>`}));
  }
  const P = d.profil;
  if (P && P.vorschlaege && P.vorschlaege.length) {
    const wort = {ergaenzen: "neu", ersetzen: "ändern", streichen: "streichen"};
    cards.push(card("Über mich – Vorschläge", "var(--pink)", P.vorschlaege.map((v) =>
      `<li><span class="tag">${esc(v.abschnitt)} · ${wort[v.art] || esc(v.art)}</span>
        <div style="margin-top:6px">${v.art === "streichen" ? "<s>" + esc(v.alt) + "</s>" : esc(v.neu)}</div>
        ${v.art === "ersetzen" && v.alt ? `<div class="antwort">bisher: ${esc(v.alt)}</div>` : ""}
        <small>${esc(v.begruendung)}</small>
        <div class="knoepfe"><button data-profil="${v.id}" data-ja="1">Annehmen</button><button data-profil="${v.id}" data-ja="0">Ablehnen</button></div></li>`),
      {wide: true, note: "gilt erst, wenn du annimmst"}));
  }
  const G = d.cospend;
  if (G) {
    const eur = (v) => nf(v, 2) + " €", ichName = d.ich && d.ich in G.saldo ? d.ich : null, ich = ichName ? G.saldo[ichName] : 0,
      anderer = Object.keys(G.saldo).find((n) => n !== ichName) || "die andere Person";
    const kat = Object.entries(G.zeitraum.nach_kategorie), kmax = Math.max(...kat.map((k) => k[1]), 1);
    const mon = Object.entries(G.monate), mmax = Math.max(...mon.map((m) => m[1]), 1);
    cards.push(card("Gemeinsame Ausgaben (Cospend)", "var(--teal)", [
      `<li>Stand zwischen euch<span class="tag${ich < -0.005 ? " late" : ""}">${Math.abs(ich) < 0.005 ? "ausgeglichen" : !ichName ? Object.entries(G.saldo).map(([n, v]) => esc(n) + " " + (v < 0 ? "−" : "+") + eur(Math.abs(v))).join(" · ") : ich < 0 ? "du schuldest " + esc(anderer) + " " + eur(-ich) : esc(anderer) + " schuldet dir " + eur(ich)}</span></li>`,
      `<li>Dieser Monat<span class="tag">${eur(G.monat.summe)}</span><small>${mon.map(([m, v]) => m.slice(5) + "/" + m.slice(2, 4) + ": " + nf(v, 0) + " €").join(" · ")}</small></li>`,
      `<li>Im gewählten Zeitraum<span class="tag">${eur(G.zeitraum.summe)}</span><small>${G.zeitraum.anzahl} Einträge</small>
        ${kat.slice(0, 7).map(([k, v]) => `<div style="display:flex;align-items:center;gap:8px;margin-top:5px;font-size:13px"><span style="flex:0 0 38%;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(k)}</span><span style="flex:1;height:8px;border-radius:4px;background:var(--border)"><span style="display:block;height:8px;border-radius:4px;width:${Math.max(2, Math.round(v / kmax * 100))}%;background:var(--teal)"></span></span><span style="flex:0 0 auto;font-variant-numeric:tabular-nums">${nf(v, 0)} €</span></div>`).join("")}</li>`,
      ...G.letzte.slice(0, 6).map((b) => `<li>${esc(b.was.trim())}<span class="tag">${eur(b.betrag)}</span>${b.sprachnotiz ? '<span class="tag">per Sprachnotiz</span>' : ""}<small>${fmtDay(b.tag)} · ${esc(b.zahler)} zahlt${b.kategorie ? " · " + esc(b.kategorie) : ""}</small></li>`),
    ], {note: G.projekt}));
  }
  const F = d.finanzen;
  if (F && F.konten && F.konten.length) {
    const eur = (v) => nf(v, 2) + " €", eur0 = (v) => nf(Math.round(v), 0) + " €", B = F.budget, V = F.verlauf, PR = F.prognose;
    const farbe = {gruen: "var(--good)", gelb: "var(--warn)", rot: "var(--bad)"};
    const mName = (m) => new Date(m + "-15").toLocaleDateString("de-DE", {month: "short"}).replace(".", "");
    if (B) {
      const wort = {gruen: "im Rahmen", gelb: "etwas schneller als üblich", rot: B.frei < 0 ? "Monat überzogen" : "deutlich schneller als üblich"};
      const aus = B.ausgegeben, raum = B.spielraum, nochK = PR ? Math.max(PR.ausgaben - aus, 0) : 0;
      const kommt = Math.max(0, Math.min(nochK, raum - aus)), rest = Math.max(PR ? PR.frei : B.frei, 0);
      const satz = B.frei < 0 ? `Du liegst diesen Monat <b class="minus">${eur0(-B.frei)}</b> über deinem Spielraum.` : `Du kannst diesen Monat noch <b>${eur0(B.frei)}</b> ausgeben.`;
      const satz2 = !PR ? "" : PR.frei < 0 ? `Läuft der Rest des Monats wie üblich, fehlen am Ende etwa <b class="minus">${eur0(-PR.frei)}</b>.` : `Läuft der Rest des Monats wie üblich, bleiben am Ende etwa <b class="plus">${eur0(PR.frei)}</b> übrig.`;
      const fakten = [
        ["Pro Tag verfügbar", B.frei > 0 ? eur0(B.je_tag) : "0 €", "für die restlichen " + B.rest_tage + " Tage", ""],
        PR && PR.giro_ende != null ? ["Girokonto am Monatsende", "etwa " + eur0(PR.giro_ende), PR.offen_fix > 0 ? "nach " + eur0(PR.offen_fix) + " festen Posten, die noch abgehen" : "alle festen Posten sind gebucht", PR.giro_ende < 0 ? "minus" : ""] : null,
        B.sonder > 0 ? ["Sondereingänge", "+" + eur0(B.sonder), "kommen obendrauf, hier nicht eingerechnet", "plus"] : null].filter(Boolean);
      window.__verlauf = V ? {V, B, PR} : null;
      cards.push(`<article class="card wide held" style="--c:var(--accent)"><h2><i></i>Noch frei diesen Monat<em><span class="punkt" style="background:${farbe[B.ampel]}"></span>${wort[B.ampel]}</em></h2>
        <p class="satz">${satz}</p>${satz2 ? `<p class="satz2">${satz2}</p>` : ""}
        <div class="budget" role="img" aria-label="Vom Spielraum ${eur0(raum)} sind ${eur0(aus)} ausgegeben">
          <i class="b-aus${aus > raum ? " ueber" : ""}" style="flex:${Math.max(aus, 1)}"></i>${kommt > 0 ? `<i class="b-kommt" style="flex:${kommt}"></i>` : ""}${rest > 0 ? `<i class="b-rest" style="flex:${rest}"></i>` : ""}</div>
        <div class="budgetleg"><span><i class="b-aus"></i><b>${eur0(aus)}</b> ausgegeben</span>${PR ? `<span><i class="b-kommt"></i><b>etwa ${eur0(nochK)}</b> kommen erfahrungsgemäß noch</span>` : ""}<span><i class="b-rest"></i><b>${PR ? "etwa " : ""}${eur0(rest)}</b> bleiben übrig</span><span class="rechts">Spielraum im Monat: <b>${eur0(raum)}</b></span></div>
        <div class="minis">${fakten.map(([l, z, t, k]) => `<div class="mini ${k}"><span>${esc(l)}</span><b>${z}</b><small>${esc(t)}</small></div>`).join("")}</div>
        ${V ? `<h3 class="charttitel">Ausgaben im Monatsverlauf<small>aufaddiert vom 1. bis heute, gestrichelt die Prognose</small></h3><div class="chart" id="verlauf"></div>
        <div class="legende"><span><i style="background:linear-gradient(90deg,#7c6cff,#ff5fa2)"></i>dieser Monat</span><span><i class="strich"></i>Prognose bis Monatsende</span><span><i class="punkte"></i>so lief es im Mittel der letzten Monate</span><span><i class="raum"></i>Spielraum</span></div>` : ""}
        <details><summary>So wird gerechnet</summary><p>Spielraum = regelmäßige Einnahmen ${eur(B.einnahmen)} − feste Ausgaben ${eur(B.fix)} = ${eur(raum)}. Davon ab geht, was diesen Monat mit Karte und vom Girokonto variabel ausgegeben wurde. Die Prognose nimmt an, dass der Rest des Monats so verläuft wie im Mittel der letzten Monate.</p></details></article>`);
    } else if (F.hinweis) cards.push(card("Noch frei diesen Monat", "var(--accent)", [`<li>${esc(F.hinweis)}</li>`]));

    cards.push(card("Konten", "var(--sky)", F.konten.map((k) => `<li class="konto"><div><b>${esc(k.name)}</b><small>${esc(k.bank)} · Stand ${fmtDay(k.stand)}</small></div><span class="betrag${k.saldo < 0 ? " minus" : ""}">${k.saldo == null ? "–" : eur(k.saldo)}</span></li>`)));

    const BI = Object.entries(F.bilanz || {});
    if (BI.length) {
      const bmax = Math.max(...BI.flatMap(([m, z]) => [z.ein, z.aus]), 1);
      cards.push(card("Monatsbilanz", "var(--teal)", [], {note: "Einnahmen gegen Ausgaben", empty: " ",
        extra: `<div class="saeulen">${BI.map(([m, z]) => `<div class="saeule${m === F.monat ? " jetzt" : ""}"><div class="paar"><i class="ein" style="height:${Math.max(2, z.ein / bmax * 100)}%" title="Einnahmen ${eur(z.ein)}"></i><i class="aus" style="height:${Math.max(2, z.aus / bmax * 100)}%" title="Ausgaben ${eur(z.aus)}"></i></div><span>${mName(m)}</span><b class="${z.netto < 0 ? "minus" : "plus"}">${z.netto < 0 ? "−" : "+"}${nf(Math.abs(Math.round(z.netto)), 0)}</b></div>`).join("")}</div>
          <div class="legende"><span><i style="background:var(--g-teal)"></i>Einnahmen</span><span><i style="background:var(--g-pink)"></i>Ausgaben</span><span>Zahl darunter: was übrig blieb · ${mName(F.monat)} läuft noch</span></div>`}));
    }

    const KK = F.karte || {};
    if (KK.vorhanden && KK.kategorien && KK.kategorien.length) {
      const kat = [...KK.kategorien].sort((a, b) => b.monat - a.monat), kmax = Math.max(...kat.flatMap((k) => [k.monat, k.schnitt]), 1);
      cards.push(card("Kreditkarte nach Kategorie", "var(--pink)", [], {note: eur0(KK.monat) + " diesen Monat", empty: " ",
        extra: `<div class="kat">${kat.map((k) => { const mehr = k.monat > k.schnitt * 1.1 && k.monat - k.schnitt > 10; return `<div class="katzeile"><span class="katname">${esc(k.name)}</span><span class="spur"><i class="${mehr ? "mehr" : ""}" style="width:${Math.max(1.5, k.monat / kmax * 100)}%"></i><u style="left:${k.schnitt / kmax * 100}%" title="Schnitt ${eur0(k.schnitt)}"></u></span><span class="katwert"><b>${eur0(k.monat)}</b><small>Ø ${eur0(k.schnitt)}</small></span></div>`; }).join("")}</div>
          <div class="legende"><span><i style="background:var(--g-violet)"></i>dieser Monat</span><span><i style="background:var(--g-pink)"></i>über dem Schnitt</span><span><i class="marke"></i>Schnitt der letzten Monate</span></div>`}));
    }

    if (PR && PR.posten && PR.posten.length) {
      cards.push(card("Feste Posten", "var(--warn)", PR.posten.map((x) => `<li class="konto"><div><b>${esc(x.wer.slice(0, 34))}</b><small>${x.offen ? "steht noch aus" + (x.tag ? " · meist um den " + x.tag + "." : "") : "diesen Monat gebucht"}</small></div><span class="betrag ${x.betrag > 0 ? "plus" : ""}">${x.betrag > 0 ? "+" : "−"}${eur0(Math.abs(x.offen || x.betrag))}</span><span class="tag${x.offen ? " late" : " today"}">${x.offen ? "offen" : "✓"}</span></li>`),
        {note: PR.offen_fix > 0 ? "noch " + eur0(PR.offen_fix) + " offen" : "alles gebucht"}));
    }

    if ((F.tipps && F.tipps.length) || (F.abos && F.abos.length)) {
      cards.push(card("Sparpotenzial", "var(--lime)", [
        ...(F.tipps || []).map((t) => `<li class="konto"><div><b>${esc(t.name)}</b><small>Ø ${eur0(t.schnitt)} im Monat bei ${nf(t.kaeufe, 0)} Käufen · ${t.anteil} % weniger</small></div><span class="betrag plus">+${nf(t.ersparnis, 0)} €</span></li>`),
        ...(F.abos && F.abos.length ? [`<li><b>Laufende Abos</b><div class="chips">${F.abos.map((a) => `<span class="tag">${esc(a.wer)} ${nf(a.je_monat, 2)} €</span>`).join("")}</div></li>`] : []),
      ], {note: (F.tipps || []).length ? "zusammen etwa " + nf(F.tipps.reduce((s, t) => s + t.ersparnis, 0), 0) + " € im Monat" : ""}));
    }

    const O = F.cospend_offen;
    if (O && O.liste && O.liste.length) {
      cards.push(card("In Cospend nachtragen?", "var(--teal)", O.liste.map((u) => `<li class="konto"><div><b>${esc(u.name)}</b><small>${fmtDay(u.tag)} · ${esc(u.wer)}</small><div class="knoepfe"><button data-finanz="${u.id}" data-ja="1">Eintragen</button><button data-finanz="${u.id}" data-ja="0">Übergehen</button></div></div><span class="betrag">${eur(u.betrag)}</span></li>`),
        {note: O.anzahl + " Kartenkäufe · " + eur(O.summe)}));
    } else if (O && !O.fehler) cards.push(card("In Cospend nachtragen?", "var(--teal)", [`<li class="konto"><div><b>Alles nachgetragen</b><small>Jeder Kartenkauf für den Haushalt der letzten 35 Tage hat einen Eintrag in der Verrechnungsliste.</small></div><span class="tag today">✓</span></li>`]));
    else if (O && O.fehler) cards.push(card("In Cospend nachtragen?", "var(--teal)", [`<li>Abgleich nicht möglich<small>${esc(O.fehler)}</small></li>`]));

    cards.push(card("Letzte Umsätze", "var(--sky)", F.letzte.slice(0, 8).map((u) => `<li class="konto"><div><b>${esc(u.wer.slice(0, 40))}</b><small>${fmtDay(u.tag)} · ${esc(u.konto)}</small></div><span class="betrag ${u.betrag > 0 ? "plus" : ""}">${u.betrag > 0 ? "+" : "−"}${eur(Math.abs(u.betrag))}</span></li>`)));
  }
  cards.push(card("Aufgaben", "var(--accent)", aufgaben.map((e) => {
    const f = e.daten.faellig;
    return row(e, f ? `<span class="tag${f < t0 ? " late" : ""}">bis ${fmtDay(f)}</span>` : "");
  }), {empty: "Keine Aufgaben erkannt."}));
  const K = d.kalender;
  if (K) {
    const dayOf = (x) => (x.beginn || "").slice(0, 10), tm = (x) => new Date(x).toLocaleTimeString("de-DE", {hour: "2-digit", minute: "2-digit"});
    cards.push(card("Kalender", "var(--sky)", K.termine.map((x) => {
      const when = x.ganztags ? "ganztägig" : tm(x.beginn) + (x.ende ? "–" + tm(x.ende) : "");
      return `<li>${esc(x.titel)}<span class="tag${dayOf(x) === t0 ? " today" : ""}">${dayOf(x) === t0 ? "heute" : fmtDay(dayOf(x))}</span><small>${when}${x.ort ? " · " + esc(x.ort) : ""}${K.kalender.length > 1 ? " · " + esc(x.kalender) : ""}</small></li>`;
    }), {wide: true, cls: "kal", note: `nächste ${K.tage} Tage`, empty: K.kalender.length ? "Keine Termine in den nächsten Tagen." : "In Home Assistant ist noch kein Kalender eingerichtet."}));
  }
  cards.push(card("Termine (Vorschläge)", "var(--sky)", by("termin").sort((a, b) => (a.daten.datum || "").localeCompare(b.daten.datum || "")).map((e) =>
    row(e, `<span class="tag">${e.daten.datum ? fmtDay(e.daten.datum) : "ohne Datum"}${e.daten.uhrzeit ? " · " + esc(e.daten.uhrzeit) : ""}</span>${e.daten.ort ? `<span class="tag">${esc(e.daten.ort)}</span>` : ""}`)),
    {empty: "Keine Termine erkannt.", note: "noch nicht im Kalender"}));
  cards.push(card("Erinnerungen", "var(--warn)", by("erinnerung").map((e) => row(e))));

  // Ausgaben pro Tag als kleine Balken
  const perDay = {};
  [...essen, ...einkauf].forEach((e) => { perDay[e.tag] = (perDay[e.tag] || 0) + (e.daten.betrag_eur || 0); });
  const dayList = [...Array(Math.min(d.tage, 14))].map((_, i) => { const x = new Date(); x.setDate(x.getDate() - i); return x.toLocaleDateString("sv-SE"); }).reverse();
  const max = Math.max(1, ...dayList.map((k) => perDay[k] || 0));
  const bars = d.tage > 1 ? `<div class="barwrap"><div class="bars" role="img" aria-label="Ausgaben pro Tag">${dayList.map((k) =>
    `<div style="height:${Math.round(100 * (perDay[k] || 0) / max)}%" title="${fmtDay(k)}: ${eur(perDay[k] || 0)}"><span>${k.slice(8)}</span></div>`).join("")}</div></div>` : "";
  const money = (e) => (e.daten.betrag_eur != null ? `<span class="tag">${eur(e.daten.betrag_eur)}</span>` : "");
  cards.push(card("Essen und Trinken", "var(--lime)", essen.map((e) => row(e, money(e))), {extra: bars, note: geld ? eur(geld) + " gesamt" : ""}));
  cards.push(card("Einkäufe und Ausgaben", "var(--teal)", einkauf.map((e) => row(e, money(e)))));
  const lab = (x, i, n) => (n <= 14 || (n - 1 - i) % (n <= 31 ? 7 : 14) === 0 ? `<span>${x.tag.slice(8)}.${n > 31 ? x.tag.slice(5, 7) + "." : ""}</span>` : "");
  const g = d.gesundheit;
  let health = "";
  if (g) {
    const a = g.aktuell, alt = (k) => (a[k].stand && new Date(a[k].stand).toLocaleDateString("sv-SE") !== t0 ? " · " + fmtDay(new Date(a[k].stand).toLocaleDateString("sv-SE")) : ""),
      stat = (k, label, f, mitTag) => (a[k] ? `<div class="hstat"><b>${f(a[k].wert)}</b><span>${label}${mitTag ? alt(k) : ""}</span></div>` : "");
    const maxS = Math.max(1, ...g.tage.map((x) => x.schritte || 0));
    health = `<div class="hstats">${stat("schritte", "Schritte heute", (v) => nf(v))}${stat("distanz_m", "km heute", (v) => nf(v / 1000, 1))}${stat("kalorien_aktiv", "kcal aktiv", (v) => nf(v))}${stat("puls", "Puls", (v) => nf(v), true)}${stat("ruhepuls", "Ruhepuls", (v) => nf(v), true)}${stat("sauerstoff", "% Sauerstoff", (v) => nf(v), true)}</div>`
      + `<div class="barwrap"><div class="bars good" role="img" aria-label="Schritte pro Tag">${g.tage.map((x, i) =>
        `<div style="height:${Math.round(100 * (x.schritte || 0) / maxS)}%" title="${fmtDay(x.tag)}: ${nf(x.schritte || 0)} Schritte${x.distanz_m ? ", " + nf(x.distanz_m / 1000, 1) + " km" : ""}">${lab(x, i, g.tage.length)}</div>`).join("")}</div></div>`
      + `<p class="avg">Schnitt ${nf(g.tage.reduce((s, x) => s + (x.schritte || 0), 0) / Math.max(1, g.tage.filter((x) => x.schritte).length))} Schritte an ${g.tage.filter((x) => x.schritte).length} Tagen mit Daten</p>`;
  }
  cards.push(card("Sport und Bewegung", "var(--good)", sport.map((e) => row(e,
    (e.daten.dauer_min ? `<span class="tag">${e.daten.dauer_min} min</span>` : "") + (e.daten.distanz_km ? `<span class="tag">${e.daten.distanz_km} km</span>` : ""))),
    {extra: health, note: g ? "Health Connect" : "", empty: g ? "Kein Training eingesprochen." : "Nichts eingesprochen. Die Werte vom Handy fehlen noch (Zugriffstoken für Home Assistant)."}));

  if (g) {
    const TV = g.training_vorschlaege || [];
    if (TV.length) cards.push(card("Training erkannt?", "var(--good)", TV.map((v) => `<li class="konto"><div><b>${fmtDay(v.tag)} · ${v.von} bis ${v.bis} Uhr</b><small>etwa ${v.dauer_min} Minuten · ${nf(v.schritte)} Schritte · rund ${v.tempo} pro Minute</small><div class="knoepfe"><button data-training="${esc(v.id)}" data-ja="1">Als Training eintragen</button><button data-training="${esc(v.id)}" data-ja="0">War keins</button></div></div></li>`),
      {note: "aus den Schritten des Bands"}));
    window.__tr = {alle: g.training_alle || g.training || [], ab: g.daten_ab, stand: g.export_stand, monat: (window.__tr && window.__tr.monat) || null};
    if (window.__tr.alle.length) cards.push(`<article class="card wide trkarte" style="--c:var(--good)"><h2><i></i>Training${g.export_stand ? `<em>Export bis ${esc(fmtDay(g.export_stand))}</em>` : ""}</h2><div id="trkal"></div></article>`);
    const nights = g.tage.filter((x) => x.schlaf_min), maxN = Math.max(1, ...g.tage.map((x) => x.schlaf_min || 0));
    cards.push(card("Schlaf", "var(--accent)", nights.slice(-7).reverse().map((x) =>
      `<li>${Math.floor(x.schlaf_min / 60)} h ${String(x.schlaf_min % 60).padStart(2, "0")} min<small>${fmtDay(x.tag)}</small></li>`),
      {extra: nights.length > 1 ? `<div class="barwrap"><div class="bars" role="img" aria-label="Schlaf pro Nacht">${g.tage.map((x, i) =>
        `<div style="height:${Math.round(100 * (x.schlaf_min || 0) / maxN)}%" title="${fmtDay(x.tag)}: ${x.schlaf_min ? nf(x.schlaf_min / 60, 1) + " h" : "keine Daten"}">${lab(x, i, g.tage.length)}</div>`).join("")}</div></div>` : "",
       empty: "Keine Schlafdaten im gewählten Zeitraum."}));
  }
  const y = d.yamtrack, img = (b) => (b && /^https:\/\//.test(b) ? `<img src="${esc(b)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : "");
  const medien = by("medien").map((e) => row(e, (e.daten.titel ? `<span class="tag">${esc(e.daten.titel)}</span>` : "") +
    (e.daten.yamtrack ? `<div class="antwort">Yamtrack: ${esc(e.daten.yamtrack)}</div>` : "")));
  cards.push(card("Gesehen, gelesen, gehört (eingesprochen)", "var(--pink)", medien));
  if (y) {
    cards.push(card("Schaue gerade (Yamtrack)", "var(--pink)", y.laufend.map((m) => `<li class="media">${img(m.bild)}<div>${esc(m.titel)}</div></li>`), {empty: "Nichts als laufend markiert."}));
    cards.push(card("Zuletzt gesehen (Yamtrack)", "var(--pink)", [
      ...y.folgen.slice(0, 8).map((m) => ({z: m.zeit, h: `<li class="media">${img(m.bild)}<div>${esc(m.titel)} <span class="tag">S${m.staffel} · F${m.folge}</span><small>${fmtTime(m.zeit.replace(" ", "T") + "Z")}</small></div></li>`})),
      ...y.filme.slice(0, 4).map((m) => ({z: m.zeit, h: `<li class="media">${img(m.bild)}<div>${esc(m.titel)} <span class="tag">Film</span><small>${fmtTime(m.zeit.replace(" ", "T") + "Z")}</small></div></li>`})),
    ].sort((a, b) => b.z.localeCompare(a.z)).slice(0, 10).map((x) => x.h)));
  }
  cards.push(card("Überlegungen", "var(--accent)", by("ueberlegung").map((e) => row(e))));
  cards.push(card("Notizen", "var(--sky)", by("notiz").map((e) => row(e))));
  cards.push(card("Befinden", "var(--warn)", by("befinden").map((e) => row(e))));
  cards.push(card("Für Claude vorgemerkt", "var(--bad)", by("fuer_claude").map((e) => row(e, `<span class="tag">${esc(e.daten.status || "offen")}${e.daten.modell && e.daten.status === "beantwortet" ? " · " + esc(e.daten.modell) : ""}</span>` +
      (e.daten.antwort ? `<div class="antwort">${esc(e.daten.antwort)}</div>` : ""))),
    {empty: "Nichts offen.", note: "Sonnet antwortet, bei Bedarf Opus"}));
  cards.push(card("Fragen und Antworten (lokales Modell)", "var(--teal)", by("frage").map((e) => `<li>${esc(e.text)}<small>→ ${esc(e.daten.antwort)}</small></li>`)));
  cards.push(card("Aufnahmen", "var(--faint)", aufnahmen.map((e) =>
    `<li>${esc(e.text)}<small>${fmtTime(e.zeit)} · ${e.daten.foto ? "Foto" : Math.floor((e.daten.sekunden || 0) / 60) + ":" + String((e.daten.sekunden || 0) % 60).padStart(2, "0") + " min"}${e.daten.privat ? " · privat" : ""}</small><details><summary>${e.daten.foto ? "Bildbeschreibung" : "Wortlaut"}</summary><p>${esc(e.daten.wortlaut)}</p></details></li>`),
    {wide: true, empty: "Noch keine Aufnahme im gewählten Zeitraum."}));
  // ---------- Lage: je Bereich der Ist-Wert und, wo es Sinn ergibt, die Prognose ----------
  const lage = [], eurR = (v) => nf(Math.round(v), 0) + " €", ton = {gruen: "var(--good)", gelb: "var(--warn)", rot: "var(--bad)"};
  const kachel = (titel, wert, zeile, farbe, ziel) => lage.push(`<a class="lage" href="#${ziel || ""}" data-ziel="${ziel || ""}" style="--t:${farbe || "var(--none)"}"><span><i></i>${esc(titel)}</span><b>${wert}</b><small>${zeile}</small></a>`);
  const FF = d.finanzen;
  if (FF && FF.budget) {
    const B = FF.budget, PR = FF.prognose;
    kachel("Noch frei diesen Monat", eurR(B.frei), PR ? `Prognose Monatsende: <u class="${PR.frei < 0 ? "minus" : ""}">${eurR(PR.frei)}</u>` : `${eurR(B.je_tag)} pro Tag`, ton[PR && PR.frei < 0 ? "rot" : B.ampel], "Geld");
    const giro = (FF.konten || []).find((k) => k.art === "giro");
    if (giro && giro.saldo != null) kachel("Girokonto", eurR(giro.saldo), PR && PR.giro_ende != null ? `Monatsende etwa <u>${eurR(PR.giro_ende)}</u> · ${eurR(PR.offen_fix)} feste Posten offen` : "Stand " + fmtDay(giro.stand), PR && PR.giro_ende < 0 ? "var(--bad)" : "var(--good)", "Geld");
    const KK = FF.karte || {};
    if (KK.vorhanden) {
      const ueblich = (KK.kategorien || []).reduce((x, k) => x + k.schnitt, 0), tag = new Date().getDate(), tage = new Date(new Date().getFullYear(), new Date().getMonth() + 1, 0).getDate();
      const hoch = KK.monat / tag * tage;
      kachel("Kreditkarte im Monat", eurR(KK.monat), ueblich ? `hochgerechnet <u>${eurR(hoch)}</u> · üblich ${eurR(ueblich)}` : "", !ueblich ? "var(--none)" : hoch > ueblich || KK.monat > ueblich ? "var(--bad)" : hoch > ueblich * 0.8 ? "var(--warn)" : "var(--good)", "Geld");
    }
  }
  if (d.cospend) {
    const namen = Object.keys(d.cospend.saldo), ichName = d.ich && namen.includes(d.ich) ? d.ich : null,
      anderer = namen.find((n) => n !== ichName) || "", ich = d.cospend.saldo[ichName ?? namen[0]] ?? 0,
      off = FF && FF.cospend_offen ? FF.cospend_offen.anzahl : 0;
    kachel(ichName && anderer ? "Verrechnung mit " + anderer : "Geteilte Ausgaben", Math.abs(ich) < 0.005 ? "ausgeglichen" : eurR(Math.abs(ich)), (Math.abs(ich) < 0.005 ? "" : !ichName ? "offen" : ich < 0 ? "du schuldest" : "du bekommst") + (off ? `${Math.abs(ich) < 0.005 ? "" : " · "}${off} Kartenkäufe nachzutragen` : Math.abs(ich) < 0.005 ? "nichts offen" : ""), ich < -0.005 ? "var(--bad)" : off ? "var(--warn)" : "var(--good)", off ? "Jetzt wichtig" : "Geld");
  }
  if (d.claude && d.claude.guthaben != null) {
    const CC = d.claude, proTag = CC.tage.reduce((x, t) => x + t.usd, 0) / Math.max(1, CC.tage.length), reicht = proTag > 0.001 ? CC.guthaben / proTag : null;
    kachel("Claude-Guthaben", nf(CC.guthaben, 2) + " $", reicht == null ? "kaum Verbrauch" : `reicht bei diesem Tempo etwa <u>${reicht > 365 ? "über ein Jahr" : nf(Math.round(reicht)) + " Tage"}</u>`, reicht != null && reicht < 14 ? "var(--bad)" : reicht != null && reicht < 45 ? "var(--warn)" : "var(--good)", "Geld");
  }
  const GG = d.gesundheit;
  if (GG) {
    // Kalenderwoche von Montag bis Sonntag – unabhängig vom oben gewählten Zeitraum
    const mo = new Date(); mo.setDate(mo.getDate() - ((mo.getDay() + 6) % 7));
    const moIso = mo.toLocaleDateString("sv-SE"), wtag = (new Date().getDay() + 6) % 7, rest = 6 - wtag;
    const trAlle = (GG.training_alle && GG.training_alle.length ? GG.training_alle : GG.training || []).slice().sort((x, y) => y.tag.localeCompare(x.tag));
    const tr = trAlle.filter((x) => x.tag >= moIso), fehlt = Math.max(0, 3 - tr.length);
    const zuletzt = trAlle.length ? "zuletzt " + fmtDay(trAlle[0].tag) : "noch keines eingetragen";
    kachel("Training diese Woche", tr.length + " von 3", (tr.length ? tr.reduce((x, y) => x + (y.dauer_min || 0), 0) + " Minuten · " : "") + (fehlt ? zuletzt + (rest ? ` · noch ${rest} ${rest === 1 ? "Tag" : "Tage"}` : " · letzter Tag der Woche") : "Wochenziel erreicht"),
      !fehlt ? "var(--good)" : fehlt > rest + 1 ? "var(--bad)" : tr.length || wtag < 3 ? "var(--warn)" : "var(--bad)", "Körper und Essen");
    const mit = GG.tage.filter((x) => x.schritte), letzte7 = mit.slice(-7), schnitt = letzte7.length ? letzte7.reduce((x, y) => x + y.schritte, 0) / letzte7.length : 0;
    const heuteS = GG.aktuell.schritte ? GG.aktuell.schritte.wert : null;
    if (heuteS != null) {
      const jetzt = new Date(), anteil = Math.max(0.15, (jetzt.getHours() - 7 + jetzt.getMinutes() / 60) / 15);   // wacher Tag grob 7 bis 22 Uhr
      const hoch = anteil < 1 ? heuteS / anteil : heuteS;
      kachel("Schritte heute", nf(heuteS), `${anteil < 1 ? `bis heute Abend etwa <u>${nf(Math.round(hoch / 100) * 100)}</u> · ` : ""}Schnitt ${nf(Math.round(schnitt))}`, hoch >= schnitt * 0.9 ? "var(--good)" : "var(--warn)", "Körper und Essen");
    }
  }
  const KA = d.kalender, offenA = aufgaben.length, vorschl = d.profil && d.profil.vorschlaege ? d.profil.vorschlaege.length : 0, naechster = KA && KA.termine && KA.termine[0];
  kachel("Zu erledigen", offenA + (offenA === 1 ? " Aufgabe" : " Aufgaben"), (naechster ? `nächster Termin: ${esc(naechster.titel.slice(0, 28))}, ${fmtDay((naechster.beginn || "").slice(0, 10))}` : "kein Termin in den nächsten Tagen") + (vorschl ? ` · ${vorschl} Vorschläge` : ""), offenA || vorschl ? "var(--warn)" : "var(--good)", "Jetzt wichtig");
  $("#tiles").innerHTML = lage.join("");
  // Bild des Tages: nur wenn im Bilder-Ordner etwas liegt; lässt es sich nicht laden, verschwindet der Platz wieder
  const bt = $("#bildtag"), adr = d.bild ? "/api/bild-des-tages?v=" + encodeURIComponent(d.bild) : "";
  if (bt && bt.dataset.v !== adr) {
    bt.dataset.v = adr; bt.hidden = !adr; $("#kopf").classList.toggle("mitbild", !!adr);
    if (adr) { const im = bt.querySelector("img"); im.onerror = () => { bt.hidden = true; $("#kopf").classList.remove("mitbild"); }; im.src = adr; bt.href = adr; }
  }

  // ---------- Darunter: offen nur, was jetzt zählt; alles Weitere eingeklappt, leere Karten entfallen ----------
  const titel = (h) => (h.match(/<h2><i><\/i>([^<]+)/) || [, ""])[1].trim();
  const voll = cards.filter((h) => !h.includes('<p class="empty">'));
  const wichtig = [/^Noch frei/, /^Über mich/, /^Aufgaben/, /^Kalender/, /^Termine/, /^Erinnerungen/, /^Für Claude/, /^Training erkannt/];
  const nachtragen = (h) => /^In Cospend/.test(titel(h)) && h.includes("data-finanz");
  const gruppen = [
    ["Jetzt wichtig", (t, h) => wichtig.some((re) => re.test(t)) || nachtragen(h)],
    ["Geld", (t) => /^(Konten|Monatsbilanz|Kreditkarte|Feste Posten|Sparpotenzial|In Cospend|Letzte Umsätze|Gemeinsame Ausgaben|Claude-Guthaben)/.test(t)],
    ["Körper und Essen", (t) => /^(Sport|Training|Schlaf|Gesundheit|Befinden|Essen)/.test(t)],
    ["Alltag und Medien", (t) => /^(Einkäufe|Gesehen|Schaue|Zuletzt gesehen)/.test(t)],
    ["Gedanken und Notizen", () => true]];
  const topf = gruppen.map(() => []);
  voll.forEach((h) => topf[gruppen.findIndex(([, passt]) => passt(titel(h), h))].push(h));
  topf.forEach((t) => t.sort((x, y) => (titel(y) === "Training") - (titel(x) === "Training")));
  let offen = {};
  try { offen = JSON.parse(localStorage.getItem("meintag.offen") || "{}"); } catch (e) {}
  $("#grid").innerHTML = gruppen.map(([name], i) => !topf[i].length ? "" : i === 0
    ? `<h3 class="gruppe" id="${name}"><span>${name}</span></h3><div class="grid">${topf[i].join("")}</div>`
    : `<details class="mehr" id="${name}"${offen[name] ? " open" : ""}><summary><span>${name}</span><em>${topf[i].map(titel).slice(0, 4).join(" · ")}${topf[i].length > 4 ? " · …" : ""}</em></summary><div class="grid">${topf[i].join("")}</div></details>`).join("");
  verlaufZeichnen(); trainingZeichnen();
  document.querySelectorAll("details.mehr").forEach((x) => x.addEventListener("toggle", () => {
    offen[x.id] = x.open; try { localStorage.setItem("meintag.offen", JSON.stringify(offen)); } catch (e) {}
  }));
}

async function load() {
  document.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.d) === days)));
  try {
    const r = await fetch("/api/tag?tage=" + days, {cache: "no-store"});
    render(await r.json());
  } catch (e) {
    $("#errors").innerHTML = `<p class="err">Daten konnten nicht geladen werden: ${esc(e.message)}</p>`;
  }
}
// Verlaufsgrafik: wird in echter Pixelbreite gezeichnet, damit Schrift auf PC und Handy gleich gut lesbar bleibt
function verlaufZeichnen() {
  const el = document.getElementById("verlauf"), X = window.__verlauf;
  if (!el || !X || !el.clientWidth) return;
  const {V, B, PR} = X, W = Math.max(280, el.clientWidth), schmal = W < 560, H = schmal ? 250 : 330, L = 52, R = schmal ? 14 : 22, T = 34, Bo = 36;
  const z = (v) => Math.round(v).toLocaleString("de-DE") + " €";
  const ueb = V.ueblich.map(((mx) => (v) => (mx = Math.max(mx, v)))(0)), ist = V.ist, ende = PR ? PR.ausgaben : ist[ist.length - 1];
  const roh = Math.max(B.spielraum, ende, ueb[ueb.length - 1]) * 1.14, schritt = roh > 2400 ? 1000 : roh > 1200 ? 500 : 250, ymax = Math.ceil(roh / schritt) * schritt;
  const x = (t) => L + (t - 1) / (V.tage - 1) * (W - L - R), y = (v) => T + (1 - v / ymax) * (H - T - Bo);
  const glatt = (a, t0 = 1) => {
    const P = a.map((v, i) => [x(i + t0), y(v)]), f = (n) => n.toFixed(1);
    if (P.length < 3) return P.map((p, i) => (i ? "L" : "M") + f(p[0]) + " " + f(p[1])).join(" ");
    const d = [], m = [];
    for (let i = 0; i < P.length - 1; i++) d.push((P[i + 1][1] - P[i][1]) / (P[i + 1][0] - P[i][0]));
    m[0] = d[0]; m[P.length - 1] = d[d.length - 1];
    for (let i = 1; i < P.length - 1; i++) m[i] = d[i - 1] * d[i] <= 0 ? 0 : 2 / (1 / d[i - 1] + 1 / d[i]);
    let s = `M${f(P[0][0])} ${f(P[0][1])}`;
    for (let i = 0; i < P.length - 1; i++) { const h = (P[i + 1][0] - P[i][0]) / 3; s += ` C${f(P[i][0] + h)} ${f(P[i][1] + m[i] * h)} ${f(P[i + 1][0] - h)} ${f(P[i + 1][1] - m[i + 1] * h)} ${f(P[i + 1][0])} ${f(P[i + 1][1])}`; }
    return s;
  };
  const hx = x(V.heute), hy = y(ist[ist.length - 1]), ex = x(V.tage), ey = y(ende), y0 = y(0), ys = y(B.spielraum), linie = glatt(ist);
  const blase = (cx, cy, text, cls, lage) => { const w = text.length * 7.4 + 18, bx = lage === "links" ? Math.max(L + 2, cx - w - 14) : Math.max(L + 2, Math.min(W - R - w, cx - w / 2)), by = lage === "links" ? cy - 12 : lage === "unten" ? cy + 14 : cy - 38;
    return `<g class="blase ${cls}"><rect x="${bx}" y="${by}" width="${w}" height="24" rx="12"/><text x="${bx + w / 2}" y="${by + 16}" text-anchor="middle">${text}</text></g>`; };
  let g = "";
  for (let v = 0; v <= ymax; v += schritt) g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="c-gitter${v ? "" : " null"}"/><text x="${L - 10}" y="${y(v) + 4}" text-anchor="end" class="c-achse">${v ? Math.round(v).toLocaleString("de-DE") : "0 €"}</text>`;
  [1, 5, 10, 15, 20, 25, V.tage].filter((t, i, a) => a.indexOf(t) === i && Math.abs(x(t) - x(V.heute)) > 40 && (t === V.tage || x(V.tage) - x(t) > 34)).forEach((t) => { g += `<text x="${x(t)}" y="${H - 10}" text-anchor="${t === 1 ? "start" : t === V.tage ? "end" : "middle"}" class="c-achse">${t}.</text>`; });
  const nah = ex - hx < 120;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Bis heute ${z(ist[ist.length - 1])} ausgegeben, Prognose zum Monatsende ${z(ende)}, Spielraum ${z(B.spielraum)}">
    <defs><linearGradient id="vl" x1="0" x2="1"><stop offset="0" stop-color="#7c6cff"/><stop offset=".6" stop-color="#ff5fa2"/><stop offset="1" stop-color="#ff8a6b"/></linearGradient>
    <linearGradient id="vf" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#b06bff" stop-opacity=".34"/><stop offset=".75" stop-color="#7c6cff" stop-opacity=".05"/><stop offset="1" stop-color="#7c6cff" stop-opacity="0"/></linearGradient>
    <filter id="vg" x="-10%" y="-40%" width="120%" height="180%"><feGaussianBlur stdDeviation="7"/></filter></defs>
    ${g}
    <line x1="${L}" x2="${W - R}" y1="${ys}" y2="${ys}" class="c-raum"/><text x="${L + 8}" y="${ys - 8}" class="c-raumtext">Spielraum ${z(B.spielraum)}</text>
    <path d="${glatt(ueb)}" class="c-ueb"/>
    <path d="${linie} L${hx.toFixed(1)} ${y0} L${x(1).toFixed(1)} ${y0} Z" fill="url(#vf)"/>
    <path d="${linie}" fill="none" stroke="url(#vl)" stroke-width="9" stroke-linecap="round" opacity=".5" filter="url(#vg)"/>
    <path d="${linie}" fill="none" stroke="url(#vl)" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
    <line x1="${hx}" x2="${hx}" y1="${hy + 10}" y2="${y0}" class="c-heute"/><text x="${hx}" y="${H - 10}" text-anchor="middle" class="c-achse hell">heute</text>
    ${PR ? `<path d="M${hx} ${hy} L${ex} ${ey}" class="c-prog"/><circle cx="${ex}" cy="${ey}" r="5.5" class="c-progpunkt"/>${blase(ex, ey, "≈ " + z(ende), "vor", !nah && ey - ys < 62 && ey - ys > -30 ? "unten" : "oben")}` : ""}
    <circle cx="${hx}" cy="${hy}" r="13" fill="#fff" opacity=".12"/><circle cx="${hx}" cy="${hy}" r="6.5" fill="#fff"/>
    ${blase(hx, hy, z(ist[ist.length - 1]), "ist", nah ? "links" : "oben")}
  </svg>`;
}
// Trainingskalender: ein Monat als Raster, darüber die Zahlen fürs Jahr, darunter das Jahr in zwölf Säulen
function trainingZeichnen() {
  const el = document.getElementById("trkal"), T = window.__tr;
  if (!el || !T) return;
  const nf = (v, n = 0) => Number(v).toLocaleString("de-DE", {minimumFractionDigits: n, maximumFractionDigits: n});
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const heute = new Date(), hIso = iso(heute), jahr = heute.getFullYear();
  if (!T.monat) T.monat = hIso.slice(0, 7);
  const [mj, mm] = T.monat.split("-").map(Number);
  const jeTag = {};
  T.alle.forEach((x) => (jeTag[x.tag] = jeTag[x.tag] || []).push(x));
  const imJahr = T.alle.filter((x) => x.tag.startsWith(jahr + "-")), imMonat = T.alle.filter((x) => x.tag.startsWith(T.monat));
  const minJahr = imJahr.reduce((a, x) => a + (x.dauer_min || 0), 0);
  const letzter = T.alle.length ? T.alle.reduce((a, x) => x.tag > a ? x.tag : a, "") : null;
  const seit = letzter ? Math.round((new Date(hIso) - new Date(letzter)) / 864e5) : null;
  const mo = new Date(heute); mo.setDate(heute.getDate() - ((heute.getDay() + 6) % 7));
  const woche = T.alle.filter((x) => x.tag >= iso(mo)).length;
  const mName = new Date(mj, mm - 1, 1).toLocaleDateString("de-DE", {month: "long", year: "numeric"});
  const abHinweis = T.ab && T.ab.startsWith(jahr + "-") && T.ab > jahr + "-01-07" ? `Daten liegen erst ab ${fmtDay(T.ab)} vor` : "bis heute";
  // Raster: Wochen von Montag bis Sonntag, rechts die Summe der Woche gegen das Ziel von drei
  const erster = new Date(mj, mm - 1, 1), start = new Date(erster); start.setDate(1 - ((erster.getDay() + 6) % 7));
  let zellen = "";
  for (let w = 0; w < 6; w++) {
    const tage = [...Array(7)].map((_, i) => { const d = new Date(start); d.setDate(start.getDate() + w * 7 + i); return d; });
    if (w && tage[0].getMonth() !== mm - 1) break;
    let n = 0;
    zellen += tage.map((d) => {
      const k = iso(d), tr = jeTag[k], innen = d.getMonth() === mm - 1;
      if (tr) n += tr.length;
      const min = tr ? tr.reduce((a, x) => a + (x.dauer_min || 0), 0) : 0;
      return `<div class="trtag${innen ? "" : " aussen"}${tr ? " hat" : ""}${k === hIso ? " heute" : ""}${k > hIso ? " zukunft" : ""}"${tr ? ` title="${esc(tr.map((x) => x.art + (x.titel ? " · " + x.titel : "") + (x.dauer_min ? " · " + x.dauer_min + " min" : "")).join("\n"))}"` : ""}><b>${d.getDate()}</b>${tr ? `<small>${min ? min + " min" : "✓"}</small>` : ""}</div>`;
    }).join("") + `<div class="trwoche${n >= 3 ? " voll" : n ? " teil" : ""}">${tage[0] > heute ? "" : n + "×"}</div>`;
  }
  const monate = [...Array(12)].map((_, i) => { const k = `${mj}-${String(i + 1).padStart(2, "0")}`; return {k, n: T.alle.filter((x) => x.tag.startsWith(k)).length, name: new Date(mj, i, 1).toLocaleDateString("de-DE", {month: "short"}).replace(".", "")}; });
  const maxM = Math.max(1, ...monate.map((m) => m.n));
  const jahre = [...new Set(T.alle.map((x) => x.tag.slice(0, 4)).concat(String(jahr)))].sort();
  el.innerHTML = `
    <div class="trzahlen">
      <div class="gross"><b>${imJahr.length}</b><span>Trainings in ${jahr}<small>${abHinweis}</small></span></div>
      <div><b>${T.alle.filter((x) => x.tag.startsWith(hIso.slice(0, 7))).length}</b><span>diesen Monat</span></div>
      <div><b>${woche} von 3</b><span>diese Woche</span></div>
      <div><b>${nf(minJahr / 60, 0)} h</b><span>Trainingszeit ${jahr}</span></div>
      <div><b>${seit == null ? "–" : seit === 0 ? "heute" : seit === 1 ? "gestern" : "vor " + seit + " Tagen"}</b><span>letztes Training</span></div>
    </div>
    <div class="trflex">
      <div class="trmonat">
        <div class="trkopf"><button data-trm="-1" aria-label="Monat zurück">‹</button><strong>${mName}<small>${imMonat.length} ${imMonat.length === 1 ? "Training" : "Trainings"}</small></strong><button data-trm="1" aria-label="Monat vor"${T.monat >= hIso.slice(0, 7) ? " disabled" : ""}>›</button></div>
        <div class="trraster"><span>Mo</span><span>Di</span><span>Mi</span><span>Do</span><span>Fr</span><span>Sa</span><span>So</span><span title="Trainings in der Woche, Ziel sind drei">Wo.</span>${zellen}</div>
        <p class="trleg"><span><i class="hat"></i>Training</span><span><i class="heute"></i>heute</span><span><i class="voll"></i>Wochenziel 3 erreicht</span></p>
      </div>
      <div class="trjahr">
        <div class="trjkopf">${jahre.map((j) => `<button data-trj="${j}"${Number(j) === mj ? ' aria-pressed="true"' : ""}>${j}</button>`).join("")}<span>Trainings je Monat</span></div>
        <div class="trsaeulen">${monate.map((m) => `<button data-trk="${m.k}" class="${m.k === T.monat ? "an" : ""}${m.k > hIso.slice(0, 7) ? " zukunft" : ""}" aria-label="${m.name}: ${m.n} Trainings"><em>${m.n || ""}</em><i style="height:${Math.round(m.n / maxM * 100)}%"></i><span>${m.name}</span></button>`).join("")}</div>
        <ul class="trliste">${imMonat.slice().sort((a, b) => b.beginn.localeCompare(a.beginn)).map((x) => `<li><b>${new Date(x.tag).toLocaleDateString("de-DE", {weekday: "short", day: "numeric", month: "numeric"})}</b><span>${esc(x.art)}${x.titel ? " · " + esc(x.titel) : ""}</span><span class="tag">${x.dauer_min ? x.dauer_min + " min" : "ohne Dauer"}</span></li>`).join("") || '<li class="leer">Kein Training in diesem Monat.</li>'}</ul>
      </div>
    </div>`;
}
document.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-trm],[data-trk],[data-trj]"), T = window.__tr;
  if (!b || !T) return;
  if (b.dataset.trk) T.monat = b.dataset.trk;
  else if (b.dataset.trj) T.monat = b.dataset.trj + "-" + (Number(b.dataset.trj) === new Date().getFullYear() ? String(new Date().getMonth() + 1).padStart(2, "0") : "12");
  else { const [j, m] = T.monat.split("-").map(Number), d = new Date(j, m - 1 + Number(b.dataset.trm), 1); T.monat = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; }
  trainingZeichnen();
});
let verlaufT; addEventListener("resize", () => { clearTimeout(verlaufT); verlaufT = setTimeout(verlaufZeichnen, 150); });
document.addEventListener("toggle", (e) => { if (e.target.matches && e.target.matches("details")) verlaufZeichnen(); }, true);
document.addEventListener("click", (ev) => {
  const k = ev.target.closest("a.lage");
  if (!k) return;
  ev.preventDefault();
  const z = document.getElementById(k.dataset.ziel);
  if (!z) return;
  if (z.tagName === "DETAILS") z.open = true;
  z.scrollIntoView({behavior: "smooth", block: "start"});
});
document.addEventListener("click", async (ev) => {
  const tb = ev.target.closest("button[data-training]");
  if (tb) {
    tb.parentElement.querySelectorAll("button").forEach((x) => (x.disabled = true));
    try {
      const r = await fetch("/api/tag/entscheid/training", {method: "POST", headers: {"Content-Type": "application/json", "X-Homie-CSRF": document.body.dataset.csrf},
        body: JSON.stringify({id: tb.dataset.training, annehmen: tb.dataset.ja === "1"})});
      const j = await r.json();
      if (!j.ok) throw new Error(j.fehler || "abgelehnt");
    } catch (e) {
      $("#errors").innerHTML = `<p class="err">Training konnte nicht verarbeitet werden: ${esc(e.message)}</p>`;
    }
    return load();
  }
  const fb = ev.target.closest("button[data-finanz]");
  if (fb) {
    fb.parentElement.querySelectorAll("button").forEach((x) => (x.disabled = true));
    try {
      const r = await fetch("/api/tag/entscheid/finanzen", {method: "POST", headers: {"Content-Type": "application/json", "X-Homie-CSRF": document.body.dataset.csrf},
        body: JSON.stringify({id: fb.dataset.finanz, annehmen: fb.dataset.ja === "1"})});
      const j = await r.json();
      if (!j.ok) throw new Error(j.fehler || "abgelehnt");
    } catch (e) {
      $("#errors").innerHTML = `<p class="err">Kauf konnte nicht verarbeitet werden: ${esc(e.message)}</p>`;
    }
    return load();
  }
  const b = ev.target.closest("button[data-profil]");
  if (!b) return;
  b.parentElement.querySelectorAll("button").forEach((x) => (x.disabled = true));
  try {
    const r = await fetch("/api/tag/entscheid/profil", {method: "POST", headers: {"Content-Type": "application/json", "X-Homie-CSRF": document.body.dataset.csrf},
      body: JSON.stringify({id: Number(b.dataset.profil), annehmen: b.dataset.ja === "1"})});
    const j = await r.json();
    if (!j.ok) throw new Error(j.fehler || "abgelehnt");
  } catch (e) {
    $("#errors").innerHTML = `<p class="err">Vorschlag konnte nicht gespeichert werden: ${esc(e.message)}</p>`;
  }
  load();
});
document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
  days = Number(b.dataset.d);
  try { localStorage.setItem("meintag.tage", days); } catch (e) {}
  load();
}));
load();
setInterval(load, 60000);
