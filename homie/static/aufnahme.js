// Aufnahmeknopf: nimmt im Browser auf und gibt die Aufnahme an Homie ab. Es wird nichts im Browser gespeichert.
(() => {
  const kasten = document.getElementById("rekorder");
  const knopf = document.getElementById("aufnehmen");
  const text = document.getElementById("aufnehmen-text");
  const stand = document.getElementById("aufnahme-stand");
  if (!kasten || !knopf) return;
  if (!window.isSecureContext || !navigator.mediaDevices || !window.MediaRecorder) {
    document.getElementById("aufnahme-unsicher").hidden = false;
    stand.hidden = true;
    return;
  }
  knopf.disabled = false;
  let rekorder = null, teile = [], beginn = 0, uhr = null;

  const dauer = () => {
    const s = Math.floor((Date.now() - beginn) / 1000);
    stand.textContent = `Aufnahme läuft … ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };

  async function abgeben() {
    const ton = new Blob(teile, { type: rekorder.mimeType || "audio/webm" });
    knopf.disabled = true;
    stand.textContent = "Wird abgegeben …";
    try {
      const antwort = await fetch("/m/aufnahme/senden", {
        method: "POST", body: ton,
        headers: { "Content-Type": ton.type, "X-Homie-CSRF": kasten.dataset.csrf, "X-Aufnahme-Zeit": String(beginn / 1000) },
      });
      const daten = await antwort.json().catch(() => ({}));
      stand.textContent = antwort.ok ? "Abgegeben. Der Eintrag erscheint hier, sobald der Assistent ihn verarbeitet hat."
                                     : (daten.fehler || "Das hat nicht geklappt.");
    } catch (e) {
      stand.textContent = "Homie ist gerade nicht erreichbar. Die Aufnahme wurde nicht abgegeben.";
    }
    knopf.disabled = false;
  }

  knopf.addEventListener("click", async () => {
    if (rekorder && rekorder.state === "recording") { rekorder.stop(); return; }
    let strom;
    try {
      strom = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      stand.textContent = "Kein Zugriff auf das Mikrofon. Bitte im Browser erlauben.";
      return;
    }
    teile = [];
    rekorder = new MediaRecorder(strom);
    rekorder.addEventListener("dataavailable", (e) => { if (e.data.size) teile.push(e.data); });
    rekorder.addEventListener("stop", () => {
      clearInterval(uhr);
      strom.getTracks().forEach((t) => t.stop());
      knopf.setAttribute("aria-pressed", "false");
      text.textContent = "Aufnehmen";
      abgeben();
    });
    beginn = Date.now();
    rekorder.start();
    knopf.setAttribute("aria-pressed", "true");
    text.textContent = "Stopp und abgeben";
    dauer();
    uhr = setInterval(dauer, 1000);
  });
})();
