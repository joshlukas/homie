"use strict";
// Foto oder Datei abgeben – für die Aufnahme- und die Finanzseite. Fotos gehen an den Notiz-Assistenten, der sie liest und
// einordnet (Kassenbon, Rechnung, Zettel); Kontoauszüge (CSV, Excel) gehen in die Finanzauswertung. Homie behält nichts.
(() => {
  const feld = document.getElementById("hochladen");
  if (!feld) return;
  const stand = document.getElementById(feld.dataset.meldung), csrf = document.body.dataset.csrf || feld.dataset.csrf;
  const melde = (text, art) => { if (stand) { stand.textContent = text; stand.className = (stand.dataset.klasse || "") + (art ? " " + art : ""); stand.hidden = false; } };

  // Handyfotos sind oft über 5 MB groß: vor dem Senden auf höchstens 2400 Punkte Kantenlänge verkleinern.
  async function verkleinern(datei) {
    try {
      const bild = await createImageBitmap(datei, {imageOrientation: "from-image"});
      const f = Math.min(1, 2400 / Math.max(bild.width, bild.height));
      if (f === 1 && datei.size < 3000000 && /^image\/(jpeg|png|webp)$/.test(datei.type)) return datei;
      const c = document.createElement("canvas"); c.width = Math.round(bild.width * f); c.height = Math.round(bild.height * f);
      c.getContext("2d").drawImage(bild, 0, 0, c.width, c.height);
      return await new Promise((ja) => c.toBlob((b) => ja(b || datei), "image/jpeg", 0.88));
    } catch (_) { return datei; }
  }

  async function abgeben(datei) {
    const name = (datei.name || "").toLowerCase(), auszug = /\.(csv|xlsx)$/.test(name) || /csv|spreadsheet|excel/.test(datei.type);
    if (!auszug && !datei.type.startsWith("image/")) return melde("„" + (datei.name || "Datei") + "“: Angenommen werden Fotos sowie Kontoauszüge als CSV oder Excel.", "schlecht");
    melde(auszug ? "Lese den Kontoauszug ein …" : "Sende das Foto …");
    try {
      const koerper = auszug ? datei : await verkleinern(datei);
      const typ = auszug ? "application/octet-stream" : (/^image\/(jpeg|png|webp)$/.test(koerper.type) ? koerper.type : "image/jpeg");
      const r = await fetch(auszug ? "/m/finanzen/import" : "/m/aufnahme/senden", {method: "POST", body: koerper, signal: AbortSignal.timeout(150000),
        headers: {"Content-Type": typ, "X-Aufnahme-Zeit": String(Math.round((datei.lastModified || Date.now()) / 1000)), "X-Homie-CSRF": csrf}});
      const j = await r.json().catch(() => null);
      if (!j) return melde("Bitte in Homie neu anmelden und noch einmal versuchen.", "schlecht");
      if (!r.ok || !j.ok) return melde(j.fehler || ("Antwort " + r.status), "schlecht");
      if (auszug) melde(`${j.konto || "Konto"}: ${j.zeilen} Umsätze gelesen, ${j.neu} davon neu.` + (feld.dataset.neuladen ? " Die Seite lädt gleich neu." : ""), "gut");
      else melde("Foto gesendet. Der Assistent liest es und ordnet es ein – in ein bis zwei Minuten steht es in „Mein Tag“.", "gut");
      if (auszug && feld.dataset.neuladen) setTimeout(() => location.reload(), 2500);
    } catch (_) { melde("Keine Verbindung zum Heimnetz – bitte noch einmal versuchen.", "schlecht"); }
  }

  document.querySelectorAll("[data-waehlen]").forEach((knopf) => knopf.addEventListener("click", () => {
    feld.accept = knopf.dataset.waehlen === "foto" ? "image/*" : "image/*,.csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    if (knopf.dataset.waehlen === "foto") feld.setAttribute("capture", "environment"); else feld.removeAttribute("capture");
    feld.value = ""; feld.click();
  }));
  feld.addEventListener("change", async () => { for (const d of feld.files) await abgeben(d); feld.value = ""; });
})();
