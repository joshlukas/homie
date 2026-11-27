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

// Zeichnet die ganze Seite aus der Antwort von /api/tag (d). Die Kurznamen darin folgen der Antwort:
//   G  = d.guide (Hinweise, Agenda, Ampeln aus homie/guide.py)   F  = d.finanzen     B  = F.budget (Monatsverlauf)
//   KK = F.karte (Ausgaben nach Kategorie)                         O  = F.cospend_offen (was in die gemeinsame Abrechnung könnte)
//   P  = d.profil (Vorschläge fürs Profil)                         BF = d.cospend.betrag_fragen (Betrag unklar)
//   g  = d.gesundheit   TV = g.training_vorschlaege (erkannte Trainings)   y = d.yamtrack (Gesehenes)   L = jeweilige Liste
// Alles, was vom Assistenten kommt, geht durch esc(), bevor es ins HTML kommt – auch Kennungen in data-Attributen.
function render(d) {
  const t0 = today(), nf = (n, digits = 0) => n.toLocaleString("de-DE", {maximumFractionDigits: digits});
  $("#errors").innerHTML = (d.fehler || []).map((f) => `<p class="err">${esc(f)}</p>`).join("");
  // Der Guide rechnet immer mit einem Monat; der Rückblick unten zeigt nur den gewählten Zeitraum.
  const ab = new Date(); ab.setDate(ab.getDate() - (d.tage - 1));
  const abIso = ab.toLocaleDateString("sv-SE"), E = (d.eintraege || []).filter((e) => (e.tag || "") >= abIso), by = (t) => E.filter((e) => e.typ === t);
  const stark = (s) => esc(s).replace(/\[\[(.+?)\]\]/g, "<b>$1</b>");
  const farbe = {kritisch: "var(--bad)", achtung: "var(--warn)", gut: "var(--good)", info: "var(--sky)", "": "var(--none)"};
  const G = {hinweise: [], agenda: [], ampeln: [], ruhig: [], kopf: "", ...(d.guide || {})};
  // Jeder Teil der Seite wird für sich gezeichnet: Fehlt einem Teil etwas, zeigt nur er einen Hinweis – der Rest bleibt stehen.
  const panne = "Dieser Teil kann gerade nicht angezeigt werden. Der Rest der Seite ist davon nicht betroffen.";
  const teil = (name, ziel, fn) => {
    try { fn(); } catch (e) {
      console.error("Mein Tag, Teil „" + name + "“:", e);
      if (Array.isArray(ziel)) ziel.push(card(name, "var(--bad)", [], {empty: panne}));
      else if (ziel) $(ziel).innerHTML = `<h2><i></i>${esc(name)}</h2><p class="empty">${panne}</p>`;
      else $("#errors").insertAdjacentHTML("beforeend", `<p class="err">${esc(name)}: ${panne}</p>`);
    }
  };

  // ---------- Kopf: Datum, ein Satz zum Tag, je Bereich eine Ampel ----------
  teil("Kopf", null, () => {
  $("#sub").textContent = new Date().toLocaleDateString("de-DE", {weekday: "long", day: "numeric", month: "long"});
  $("#gsatz").textContent = G.kopf || "Noch nichts verbunden, aus dem sich der Tag ablesen ließe.";
  $("#ampeln").innerHTML = G.ampeln.map((a) => `<a class="ampel" href="#${esc(a.ziel)}" data-ziel="${esc(a.ziel)}" style="--t:${farbe[a.ton] || farbe[""]}"><span><i></i>${esc(a.bereich)}</span><b>${esc(a.wert)}</b><small>${esc(a.text)}</small></a>`).join("");
  const bt = $("#bildtag"), adr = d.bild ? "/api/bild-des-tages?v=" + encodeURIComponent(d.bild) : "";
  if (bt && bt.dataset.v !== adr) {
    bt.dataset.v = adr; bt.hidden = !adr; $("#guide").classList.toggle("mitbild", !!adr);
    if (adr) { const im = bt.querySelector("img"); im.onerror = () => { bt.hidden = true; $("#guide").classList.remove("mitbild"); }; im.src = adr; bt.href = adr; }
  }
  });

  // ---------- Was heute zählt: Schlüsse statt Einzelwerte ----------
  teil("Was heute zählt", "#hinweise", () => {
  const satz = (h) => `<li style="--t:${farbe[h.ton] || farbe.info}"${h.ziel ? ` data-ziel="${esc(h.ziel)}" tabindex="0" role="link"` : ""}><i></i><span><em>${esc(h.bereich)}</em>${stark(h.text)}</span></li>`;
  const oben = G.hinweise.slice(0, 7), mehr = G.hinweise.slice(7);
  $("#hinweise").innerHTML = `<h2><i></i>Was heute zählt</h2>` + (oben.length ? `<ul class="saetze">${oben.map(satz).join("")}</ul>` : `<p class="empty">Keine Auffälligkeiten.</p>`)
    + (mehr.length ? `<details class="rest"><summary>${mehr.length} weitere ${mehr.length === 1 ? "Hinweis" : "Hinweise"}</summary><ul class="saetze">${mehr.map(satz).join("")}</ul></details>` : "")
    + (G.ruhig.length ? `<p class="ruhig">Geprüft und unauffällig: ${esc(G.ruhig.join(", "))}.</p>` : "");
  });

  // ---------- Agenda: Termine, Aufgaben, Erinnerungen und fällige Posten in einer Liste ----------
  const morgen = new Date(); morgen.setDate(morgen.getDate() + 1);
  const tagName = (iso) => !iso ? "Ohne festen Tag" : iso === t0 ? "Heute" : iso === morgen.toLocaleDateString("sv-SE") ? "Morgen" : new Date(iso + "T12:00").toLocaleDateString("de-DE", {weekday: "long", day: "numeric", month: "numeric"});
  teil("Die nächsten Tage", "#agenda", () => {
  const punkt = {termin: "var(--sky)", aufgabe: "var(--accent)", vorschlag: "var(--warn)", erinnerung: "var(--pink)", posten: "var(--teal)"};
  const jeTag = [];
  G.agenda.forEach((a) => { const l = jeTag[jeTag.length - 1]; if (l && l.tag === a.tag) l.punkte.push(a); else jeTag.push({tag: a.tag, punkte: [a]}); });
  const aTag = (g) => `<h3 class="atag${g.tag === t0 ? " heute" : ""}">${esc(tagName(g.tag))}</h3><ul class="apunkte">${g.punkte.map((a) =>
    `<li class="${a.dringend ? "dringend" : ""}" style="--t:${punkt[a.art] || "var(--none)"}"><time>${esc(a.wann || "")}</time><i></i><span>${esc(a.titel)}${a.zusatz ? `<small>${esc(a.zusatz)}</small>` : ""}</span></li>`).join("")}</ul>`;
  // sichtbar bleiben etwa acht Punkte; ganze Tage wandern dahinter, damit die Karte kurz bleibt
  let zahl = 0; const vorn = [], hinten = [];
  jeTag.forEach((g) => { (zahl && zahl + g.punkte.length > 8 ? hinten : vorn).push(g); zahl += g.punkte.length; });
  const spaeter = hinten.reduce((s, g) => s + g.punkte.length, 0);
  $("#agenda").innerHTML = `<h2><i></i>Die nächsten Tage</h2>` + (jeTag.length ? vorn.map(aTag).join("") + (hinten.length ? `<details class="rest"><summary>${spaeter} weitere ${spaeter === 1 ? "Punkt" : "Punkte"}</summary>${hinten.map(aTag).join("")}</details>` : "")
    : `<p class="empty">Nichts in den nächsten sieben Tagen.</p>`);
  });

  // ---------- Zu entscheiden: alles, was auf ein Ja oder Nein wartet ----------
  const ent = [], eur = (v) => v.toLocaleString("de-DE", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " €", eur0 = (v) => nf(Math.round(v), 0) + " €";
  const P = d.profil, F = d.finanzen, g = d.gesundheit;
  teil("Über mich – Vorschläge", ent, () => {
  if (P && P.vorschlaege && P.vorschlaege.length) {
    // Was der Knopf bewirkt, steht bei jedem Vorschlag dabei – „Annehmen“ allein sagt es nicht.
    const kopf = {ergaenzen: (a) => `Neuer Satz für „${a}“`, ersetzen: (a) => `Satz in „${a}“ ändern`, streichen: (a) => `Satz aus „${a}“ streichen`};
    const ja = {ergaenzen: "Ins Profil aufnehmen", ersetzen: "So ändern", streichen: "Streichen"};
    ent.push(card("Über mich – Vorschläge", "var(--pink)", P.vorschlaege.map((v) =>
      `<li><span class="tag">${esc((kopf[v.art] || kopf.ergaenzen)(v.abschnitt))}</span>
        <div style="margin-top:6px">${v.art === "streichen" ? "<s>" + esc(v.alt) + "</s>" : "„" + esc(v.neu) + "“"}</div>
        ${v.art === "ersetzen" && v.alt ? `<div class="antwort">bisher: ${esc(v.alt)}</div>` : ""}
        <small>Warum: ${esc(v.begruendung)}</small>
        <div class="knoepfe"><button data-profil="${esc(v.id)}" data-ja="1">${ja[v.art] || ja.ergaenzen}</button><button data-profil="${esc(v.id)}" data-ja="0">Nicht übernehmen</button></div></li>`),
      {note: "wartet auf dich", extra: `<p class="erklaer">Dein Notiz-Assistent führt ein kurzes Profil über dich und liest es bei jeder Sprachnotiz mit, damit er Namen, Begriffe und Gewohnheiten richtig versteht. Hier schlägt er Sätze dafür vor. Nimmst du einen an, steht er ab sofort im Profil. Lehnst du ab, verschwindet der Vorschlag und kommt nicht wieder.</p>`}));
  }
  });
  // Betrag einer Sprachnotiz passt nicht zum bisherigen Preis: vermutlich verhört, also nachfragen statt buchen.
  teil("Welcher Betrag stimmt?", ent, () => {
  const BF = (d.cospend && d.cospend.betrag_fragen) || [];
  if (BF.length) ent.push(card("Welcher Betrag stimmt?", "var(--warn)", BF.map((f) => `<li class="konto"><div><b>${esc(f.titel)}</b>
      <small>Notiz vom ${fmtDay(f.zeit.slice(0, 10))}: verstanden wurden ${eur(f.gesagt)}, bisher waren es ${eur(f.ueblich)}.</small>
      <div class="knoepfe"><button data-betrag="${esc(f.id)}" data-ja="1">${eur(f.ueblich)} eintragen</button><button data-betrag="${esc(f.id)}" data-ja="0">${eur(f.gesagt)} stimmt</button></div></div></li>`),
    {note: "noch nicht gebucht", extra: `<p class="erklaer">Der Betrag weicht stark von früheren Einträgen ab, vielleicht hat sich die Spracherkennung verhört. Gebucht wird erst der Betrag, den du hier wählst.</p>`}));
  });
  teil("Training erkannt?", ent, () => {
  const TV = (g && g.training_vorschlaege) || [];
  if (TV.length) ent.push(card("Training erkannt?", "var(--good)", TV.map((v) => `<li class="konto"><div><b>${esc(fmtDay(v.tag))} · ${esc(v.von)} bis ${esc(v.bis)} Uhr</b><small>etwa ${esc(v.dauer_min)} Minuten · ${nf(v.schritte)} Schritte</small><div class="knoepfe"><button data-training="${esc(v.id)}" data-ja="1">Als Training eintragen</button><button data-training="${esc(v.id)}" data-ja="0">War keins</button></div></div></li>`),
    {note: "aus den Schritten des Bands"}));
  });
  teil("In die gemeinsame Abrechnung?", ent, () => {
  const O = F && F.cospend_offen;
  if (O && O.liste && O.liste.length) ent.push(card("In die gemeinsame Abrechnung?", "var(--teal)", O.liste.map((u) => `<li class="konto"><div><b>${esc(u.name)}</b><small>${fmtDay(u.tag)} · ${esc(u.wer)}</small><div class="knoepfe"><button data-finanz="${esc(u.id)}" data-ja="1">Eintragen</button><button data-finanz="${esc(u.id)}" data-ja="0">Übergehen</button></div></div><span class="betrag">${eur(u.betrag)}</span></li>`),
    {note: O.anzahl + " Kartenkäufe · " + eur(O.summe)}));
  else if (O && O.fehler) ent.push(card("In die gemeinsame Abrechnung?", "var(--teal)", [`<li>Abgleich nicht möglich<small>${esc(O.fehler)}</small></li>`]));
  });
  $("#entscheiden").innerHTML = ent.length ? `<h3 class="gruppe"><span>Zu entscheiden</span></h3><div class="grid">${ent.join("")}</div>` : "";

  // ---------- Details, eingeklappt: nur was die Seiten Finanzen, Gesundheit und Assistent nicht schon zeigen ----------
  const geldK = [], koerperK = [], notiertK = [];
  // Ausgaben, die als einmalig benannt wurden: schon herausgerechnet, hier nur genannt. Fehlt das Feld, steht nichts da.
  const einmalig = (B) => {
    const L = (Array.isArray(B.einmalig_liste) ? B.einmalig_liste : []).filter((e) => e && typeof e.betrag === "number");
    if (!L.length) return "";
    const summe = typeof B.einmalig === "number" ? Math.abs(B.einmalig) : L.reduce((s, e) => s + Math.abs(e.betrag), 0);
    const posten = L.slice(0, 10).map((e) => { const neben = [e.wer, e.tag ? fmtDay(e.tag) : ""].filter(Boolean).join(", ");
      return (L.length > 1 ? eur0(Math.abs(e.betrag)) + " " : "") + esc(e.grund || e.wer || "") + (e.grund && neben ? ` (${esc(neben)})` : !e.grund && e.tag ? ` (${esc(fmtDay(e.tag))})` : ""); });
    return `<p class="einmalig">Einmalig, nicht mitgezählt: <b>${eur0(summe)}</b> · ${posten.join(" · ")}</p>`;
  };
  teil("Monatsverlauf", geldK, () => {
  if (F && F.konten && F.konten.length) {
    const B = F.budget, V = F.verlauf, PR = F.prognose, ampel = {gruen: "var(--good)", gelb: "var(--warn)", rot: "var(--bad)"};
    if (B) {
      const wort = {gruen: "im Rahmen", gelb: "etwas schneller als üblich", rot: B.frei < 0 ? "Monat überzogen" : "deutlich schneller als üblich"};
      const aus = B.ausgegeben, raum = B.spielraum, nochK = PR ? Math.max(PR.ausgaben - aus, 0) : 0;
      const kommt = Math.max(0, Math.min(nochK, raum - aus)), rest = Math.max(PR ? PR.frei : B.frei, 0);
      window.__verlauf = V ? {V, B, PR} : null;
      geldK.push(`<article class="card wide held" style="--c:var(--accent)"><h2><i></i>Monatsverlauf<em><span class="punkt" style="background:${ampel[B.ampel]}"></span>${wort[B.ampel]}</em></h2>
        <div class="budget" role="img" aria-label="Vom Spielraum ${eur0(raum)} sind ${eur0(aus)} ausgegeben">
          <i class="b-aus${aus > raum ? " ueber" : ""}" style="flex:${Math.max(aus, 1)}"></i>${kommt > 0 ? `<i class="b-kommt" style="flex:${kommt}"></i>` : ""}${rest > 0 ? `<i class="b-rest" style="flex:${rest}"></i>` : ""}</div>
        <div class="budgetleg"><span><i class="b-aus"></i><b>${eur0(aus)}</b> ausgegeben</span>${PR ? `<span><i class="b-kommt"></i><b>etwa ${eur0(nochK)}</b> kommen erfahrungsgemäß noch</span>` : ""}<span><i class="b-rest"></i><b>${PR ? "etwa " : ""}${eur0(rest)}</b> bleiben übrig</span><span class="rechts">Spielraum im Monat: <b>${eur0(raum)}</b></span></div>
        ${einmalig(B)}
        ${V ? `<div class="chart" id="verlauf"></div>
        <div class="legende"><span><i style="background:linear-gradient(90deg,#7c6cff,#ff5fa2)"></i>dieser Monat</span><span><i class="strich"></i>Prognose bis Monatsende</span><span><i class="punkte"></i>so lief es im Mittel der letzten Monate</span><span><i class="raum"></i>Spielraum</span></div>` : ""}
        <details><summary>So wird gerechnet</summary><p>Spielraum = regelmäßige Einnahmen ${eur(B.einnahmen)} − feste Ausgaben ${eur(B.fix)} = ${eur(raum)}. Davon ab geht, was diesen Monat mit Karte und vom Girokonto variabel ausgegeben wurde. Die Prognose nimmt an, dass der Rest des Monats so verläuft wie im Mittel der letzten Monate.</p></details></article>`);
    } else if (F.hinweis) geldK.push(card("Monatsverlauf", "var(--accent)", [`<li>${esc(F.hinweis)}</li>`]));
    const KK = F.karte || {};
    if (KK.vorhanden && KK.kategorien && KK.kategorien.length) {
      const kat = [...KK.kategorien].sort((a, b) => b.monat - a.monat), kmax = Math.max(...kat.flatMap((k) => [k.monat, k.schnitt]), 1);
      geldK.push(card("Kreditkarte nach Kategorie", "var(--pink)", [], {note: eur0(KK.monat) + " diesen Monat", empty: " ",
        extra: `<div class="kat">${kat.map((k) => { const mehr = k.monat > k.schnitt * 1.1 && k.monat - k.schnitt > 10; return `<div class="katzeile"><span class="katname">${esc(k.name)}</span><span class="spur"><i class="${mehr ? "mehr" : ""}" style="width:${Math.max(1.5, k.monat / kmax * 100)}%"></i><u style="left:${k.schnitt / kmax * 100}%" title="Schnitt ${eur0(k.schnitt)}"></u></span><span class="katwert"><b>${eur0(k.monat)}</b><small>Ø ${eur0(k.schnitt)}</small></span></div>`; }).join("")}</div>
          <div class="legende"><span><i style="background:var(--g-violet)"></i>dieser Monat</span><span><i style="background:var(--g-pink)"></i>über dem Schnitt</span><span><i class="marke"></i>Schnitt der letzten Monate</span></div>`}));
    }
    if (F.tipps && F.tipps.length) {
      geldK.push(card("Sparpotenzial", "var(--lime)", F.tipps.map((t) => `<li class="konto"><div><b>${esc(t.name)}</b><small>Ø ${eur0(t.schnitt)} im Monat bei ${nf(t.kaeufe, 0)} Käufen · ${t.anteil} % weniger</small></div><span class="betrag plus">+${nf(t.ersparnis, 0)} €</span></li>`),
        {note: "zusammen etwa " + nf(F.tipps.reduce((s, t) => s + t.ersparnis, 0), 0) + " € im Monat"}));
    }
  }
  });
  teil("Training", koerperK, () => {
  if (g) {
    window.__tr = {alle: g.training_alle || g.training || [], ab: g.daten_ab, stand: g.export_stand, monat: (window.__tr && window.__tr.monat) || null};
    if (window.__tr.alle.length) koerperK.push(`<article class="card wide trkarte" style="--c:var(--good)"><h2><i></i>Training${g.export_stand ? `<em>Export bis ${esc(fmtDay(g.export_stand))}</em>` : ""}</h2><div id="trkal"></div></article>`);
  }
  });
  // Notiert: ein Verlauf statt einer Karte je Art
  const artName = {essen: "Essen", einkauf: "Einkauf", sport: "Sport", medien: "Medien", ueberlegung: "Gedanke", notiz: "Notiz", befinden: "Befinden", erinnerung: "Erinnerung", frage: "Frage", fuer_claude: "An Claude", aufgabe: "Aufgabe", termin: "Termin"};
  const artFarbe = {essen: "var(--lime)", einkauf: "var(--teal)", sport: "var(--good)", medien: "var(--pink)", ueberlegung: "var(--accent)", notiz: "var(--sky)", befinden: "var(--warn)", erinnerung: "var(--warn)", frage: "var(--teal)", fuer_claude: "var(--bad)", aufgabe: "var(--accent)", termin: "var(--sky)"};
  const feed = E.filter((e) => artName[e.typ]).sort((a, b) => (b.zeit || "").localeCompare(a.zeit || ""));
  const zusatz = (e) => { const x = e.daten || {}, t = [];
    if (x.betrag_eur != null) t.push(eur(x.betrag_eur));
    if (x.dauer_min) t.push(x.dauer_min + " min");
    if (x.distanz_km) t.push(x.distanz_km + " km");
    if (x.faellig) t.push("bis " + fmtDay(x.faellig));
    if (x.datum && e.typ === "termin") t.push(fmtDay(x.datum) + (x.uhrzeit ? " " + x.uhrzeit : ""));
    if (e.typ === "fuer_claude") t.push(x.status || "offen");
    const lang = x.antwort ? `<details class="rest"><summary>Antwort${x.modell ? " von " + esc(x.modell) : ""}</summary><p>${esc(x.antwort)}</p></details>` : "";
    const hinweis = [x.cospend ? "Cospend: " + x.cospend : "", x.yamtrack ? "Yamtrack: " + x.yamtrack : ""].filter(Boolean).map((s) => `<small>${esc(s)}</small>`).join("");
    return t.map((s) => `<span class="tag">${esc(s)}</span>`).join("") + hinweis + lang; };
  teil("Notiert", notiertK, () => {
  if (feed.length) {
    const tage = [];
    feed.forEach((e) => { const l = tage[tage.length - 1]; if (l && l.tag === e.tag) l.e.push(e); else tage.push({tag: e.tag, e: [e]}); });
    const geld = feed.filter((e) => e.typ === "essen" || e.typ === "einkauf").reduce((s, e) => s + ((e.daten || {}).betrag_eur || 0), 0);
    notiertK.push(`<article class="card wide" style="--c:var(--accent)"><h2><i></i>Notiert<em>${feed.length} Einträge${geld ? " · " + eur(geld) + " eingesprochene Ausgaben" : ""}</em></h2>${tage.map((t) =>
      `<h3 class="atag">${esc(tagName(t.tag))}</h3><ul class="feed">${t.e.map((e) => `<li style="--t:${artFarbe[e.typ]}"><em>${artName[e.typ]}</em><span>${esc(e.text)}${zusatz(e)}</span></li>`).join("")}</ul>`).join("")}</article>`);
  }
  });
  const y = d.yamtrack, img = (b) => (b && /^https:\/\//.test(b) ? `<img src="${esc(b)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : "");
  teil("Gesehen", notiertK, () => {
  if (y && (y.serien.length || y.zuletzt.length || y.filme.length)) {
    // Zeiten aus Yamtrack sind Weltzeit ohne Kennung
    const wann = (z) => (z ? fmtDay(new Date(z.replace(" ", "T") + "Z").toLocaleDateString("sv-SE")) : "");
    const kachel = (m, zeile) => `<li>${img(m.bild) || "<i></i>"}<b>${esc(m.titel)}</b><span>${zeile}</span><small>${wann(m.zeit)}</small></li>`;
    const stand = {
      laeuft: (s) => (s.staffel ? `Staffel ${s.staffel} · ${s.folgen} ${s.folgen === 1 ? "Folge" : "Folgen"} gesehen` : "läuft"),
      wartet: (s) => `Staffel ${s.staffel} vorgemerkt${s.staffeln_fertig ? " · " + s.staffeln_fertig + (s.staffeln_fertig === 1 ? " Staffel" : " Staffeln") + " gesehen" : ""}`,
      pausiert: (s) => (s.staffel ? `pausiert bei Staffel ${s.staffel}${s.folgen ? " · " + s.folgen + (s.folgen === 1 ? " Folge" : " Folgen") + " gesehen" : ""}` : "pausiert")};
    const spalte = (titel, art) => {
      const L = y.serien.filter((s) => s.art === art);
      return L.length ? `<div><h3>${titel}</h3><ul class="serien">${L.map((s) => `<li>${img(s.bild) || "<i></i>"}<div><b>${esc(s.titel)}</b><small>${stand[art](s)}${s.zuletzt && art !== "wartet" ? " · zuletzt " + wann(s.zuletzt) : ""}</small></div></li>`).join("")}</ul></div>` : "";
    };
    notiertK.push(`<article class="card wide gesehen" style="--c:var(--pink)"><h2><i></i>Gesehen<em>Stand aus Yamtrack</em></h2>
      ${y.zuletzt.length ? `<h3>Zuletzt geschaut</h3><ul class="kacheln">${y.zuletzt.slice(0, 6).map((m) => kachel(m, `Staffel ${m.staffel} · Folge ${m.folge}`)).join("")}</ul>` : ""}
      <div class="spalten">${spalte("Gerade dran", "laeuft")}${spalte("Wartet auf die nächste Staffel", "wartet")}${spalte("Pausiert", "pausiert")}</div>
      ${y.filme.length ? `<h3>Filme</h3><ul class="kacheln klein">${y.filme.slice(0, 6).map((m) => kachel(m, m.wertung ? `Wertung ${String(m.wertung).replace(".", ",")} von 10` : "Film")).join("")}</ul>` : ""}
    </article>`);
  }
  });
  const aufnahmen = by("aufnahme");
  teil("Aufnahmen im Wortlaut", notiertK, () => {
  if (aufnahmen.length) notiertK.push(card("Aufnahmen im Wortlaut", "var(--faint)", aufnahmen.map((e) =>
    `<li>${esc(e.text)}<small>${fmtTime(e.zeit)} · ${e.daten.foto ? "Foto" : Math.floor((e.daten.sekunden || 0) / 60) + ":" + String((e.daten.sekunden || 0) % 60).padStart(2, "0") + " min"}${e.daten.privat ? " · privat" : ""}</small><details><summary>${e.daten.foto ? "Bildbeschreibung" : "Wortlaut"}</summary><p>${esc(e.daten.wortlaut)}</p></details></li>`),
    {wide: true}));
  });

  const gruppen = [
    ["Geld", geldK, "Monatsverlauf · Kreditkarte · Sparpotenzial", `Konten, Buchungen, feste Posten und geteilte Ausgaben stehen auf der Seite <a href="/m/finanzen">Finanzen</a>, die KI-Kosten unter <a href="/m/assistent">Assistent</a>.`],
    ["Körper", koerperK, "Trainingskalender", `Schritte, Schlaf und Messwerte im Verlauf stehen auf der Seite <a href="/m/gesundheit">Gesundheit</a>.`],
    ["Notiert", notiertK, `${feed.length} Einträge · ${aufnahmen.length} Aufnahmen · ${d.tage === 1 ? "heute" : "letzte " + d.tage + " Tage"}`, ""]];
  let offen = {};
  try { offen = JSON.parse(localStorage.getItem("meintag.offen") || "{}"); } catch (e) {}
  $("#grid").innerHTML = gruppen.map(([name, karten, kurz, verweis]) => !karten.length ? "" :
    `<details class="mehr" id="${name}"${offen[name] ? " open" : ""}><summary><span>${name}</span><em>${esc(kurz)}</em></summary><div class="grid">${karten.join("")}</div>${verweis ? `<p class="verweis">${verweis}</p>` : ""}</details>`).join("");
  teil("Grafiken", null, () => { verlaufZeichnen(); trainingZeichnen(); });
  document.querySelectorAll("details.mehr").forEach((x) => x.addEventListener("toggle", () => {
    offen[x.id] = x.open; try { localStorage.setItem("meintag.offen", JSON.stringify(offen)); } catch (e) {}
  }));
}

async function load() {
  document.querySelectorAll(".seg button").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.d) === days)));
  try {
    const r = await fetch("/api/tag?tage=" + days, {cache: "no-store"});
    if (r.redirected || !(r.headers.get("Content-Type") || "").includes("json")) { location.reload(); return; }      // Anmeldung abgelaufen
    render(await r.json());
  } catch (e) {
    console.error(e);
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
  const k = ev.target.closest("[data-ziel]");
  if (!k || ev.target.closest("button, summary, a:not([data-ziel])")) return;
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
  const bb = ev.target.closest("button[data-betrag]");
  if (bb) {
    bb.parentElement.querySelectorAll("button").forEach((x) => (x.disabled = true));
    try {
      const r = await fetch("/api/tag/entscheid/betrag", {method: "POST", headers: {"Content-Type": "application/json", "X-Homie-CSRF": document.body.dataset.csrf},
        body: JSON.stringify({id: Number(bb.dataset.betrag), annehmen: bb.dataset.ja === "1"})});
      const j = await r.json();
      if (!j.ok) throw new Error(j.fehler || "abgelehnt");
    } catch (e) {
      $("#errors").innerHTML = `<p class="err">Betrag konnte nicht gebucht werden: ${esc(e.message)}</p>`;
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
