"""Der Tagesguide für „Mein Tag“: zieht aus allem, was die verbundenen Dienste liefern, Schlüsse für heute.

Eingang ist der Schnappschuss aus meintag.py (Finanzen, Gesundheit, Kalender, Notizen …), Ausgang sind wenige
Sätze, eine Agenda und je Bereich eine Ampel. Hier wird nur gerechnet und verglichen – feste Regeln, kein
Sprachmodell: Jede Aussage lässt sich auf die Zahlen zurückführen, aus denen sie stammt, und nichts verlässt Homie.
Fehlen Daten für eine Regel, schweigt sie. In den Texten markiert [[…]] die Stelle, die die Seite hervorhebt.
"""
from __future__ import annotations

import datetime as dt

WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
WOCHENZIEL = 3            # Trainings je Kalenderwoche
VORAUS = 7                # Tage, die die Agenda vorausschaut


def _eur(v: float) -> str:
    return f"{round(abs(v)):,}".replace(",", ".") + " €"


def _zahl(v: float) -> str:
    return f"{round(v):,}".replace(",", ".")


def _dauer(minuten: float) -> str:
    return f"{int(minuten) // 60} h {int(minuten) % 60:02d}"


def _datum(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def _tagwort(tag: dt.date, heute: dt.date) -> str:
    n = (tag - heute).days
    return "heute" if n == 0 else "morgen" if n == 1 else "übermorgen" if n == 2 else WOCHENTAGE[tag.weekday()] if 0 < n < 7 else f"{tag.day}.{tag.month}."


def _liste(namen: list[str], hoechstens: int = 3) -> str:
    kurz = [n if len(n) <= 40 else n[:39].rstrip() + "…" for n in namen[:hoechstens]]
    mehr = len(namen) - len(kurz)
    if mehr > 0:
        return ", ".join(kurz) + f" und {mehr} weitere"
    return ", ".join(kurz[:-1]) + (" und " if len(kurz) > 1 else "") + kurz[-1] if kurz else ""


def _mittel(werte: list[float]) -> float | None:
    return sum(werte) / len(werte) if werte else None


class _Guide:
    def __init__(self, d: dict, jetzt: dt.datetime):
        self.d, self.jetzt, self.heute = d, jetzt, jetzt.date()
        self.hinweise: list[dict] = []
        self.ampeln: list[dict] = []
        self.ruhig: list[str] = []
        self.agenda: list[dict] = []
        self.eintraege = d.get("eintraege") or []

    def sag(self, bereich: str, ton: str, text: str, ziel: str = "") -> None:
        self.hinweise.append({"bereich": bereich, "ton": ton, "text": text, "ziel": ziel})

    def typ(self, name: str) -> list[dict]:
        return [e for e in self.eintraege if e.get("typ") == name]

    # ---------- Termine, Aufgaben, Erinnerungen ----------
    def termine(self) -> None:
        heute, bis = self.heute, self.heute + dt.timedelta(days=VORAUS)
        kal = self.d.get("kalender")
        je_tag: dict[dt.date, list[dict]] = {}
        for t in (kal or {}).get("termine") or []:
            tag = _datum(t.get("beginn"))
            if tag is None or not heute <= tag <= bis:
                continue
            uhr = "" if t.get("ganztags") else str(t.get("beginn"))[11:16]
            je_tag.setdefault(tag, []).append(t)
            self.agenda.append({"tag": tag.isoformat(), "wann": uhr, "titel": t.get("titel") or "(ohne Titel)", "art": "termin", "zusatz": t.get("ort") or ""})
        self.termine_je_tag = je_tag
        if kal is not None:
            for tag, wort in ((heute, "Heute"), (heute + dt.timedelta(days=1), "Morgen")):
                liste = sorted(je_tag.get(tag, []), key=lambda t: str(t.get("beginn")))
                mit_uhr = [t for t in liste if not t.get("ganztags")]
                if tag != heute and mit_uhr and str(mit_uhr[0].get("beginn"))[11:16] < "09:00":
                    self.sag("Heute", "info", f"Morgen geht es früh los: [[{str(mit_uhr[0].get('beginn'))[11:16]} {mit_uhr[0].get('titel') or 'Termin'}]]. Heute nicht zu spät ins Bett.", "agenda")
                if len(mit_uhr) >= 4:
                    self.sag("Heute", "achtung", f"{wort} ist dicht: [[{len(mit_uhr)} Termine]] zwischen {str(mit_uhr[0].get('beginn'))[11:16]} und {str(mit_uhr[-1].get('beginn'))[11:16]} Uhr.", "agenda")
        # eingesprochene Termine, die noch nicht im Kalender stehen
        vor = []
        for e in self.typ("termin"):
            tag = _datum((e.get("daten") or {}).get("datum"))
            if tag and heute <= tag <= heute + dt.timedelta(days=30):
                vor.append((tag, e))
                if tag <= bis:
                    self.agenda.append({"tag": tag.isoformat(), "wann": (e["daten"].get("uhrzeit") or "")[:5], "titel": e.get("text") or "", "art": "vorschlag",
                                        "zusatz": "eingesprochen, noch nicht im Kalender"})
        if vor:
            vor.sort(key=lambda x: x[0])
            self.sag("Offen", "achtung", f"{len(vor)} eingesprochene{'r' if len(vor) == 1 else ''} Termin{'' if len(vor) == 1 else 'e'} "
                     f"{'steht' if len(vor) == 1 else 'stehen'} noch nicht im Kalender: [[{_liste([f'{e.get('text')} ({_tagwort(t, heute)})' for t, e in vor], 2)}]].", "agenda")

    def aufgaben(self) -> None:
        heute = self.heute
        ueber, faellig, offen = [], [], []
        for e in self.typ("aufgabe"):
            f, notiert = _datum((e.get("daten") or {}).get("faellig")), _datum(e.get("tag"))
            if f and f < heute - dt.timedelta(days=14):
                continue                                    # längst vorbei: kein Fall mehr für heute
            if f is None and notiert and notiert < heute - dt.timedelta(days=7):
                continue
            if f and f < heute:
                ueber.append(e)
                self.agenda.append({"tag": heute.isoformat(), "wann": "", "titel": e.get("text") or "", "art": "aufgabe", "zusatz": f"überfällig seit {_tagwort(f, heute)}", "dringend": True})
            elif f and f <= heute + dt.timedelta(days=VORAUS):
                (faellig if f == heute else offen).append(e)
                self.agenda.append({"tag": f.isoformat(), "wann": "", "titel": e.get("text") or "", "art": "aufgabe", "zusatz": "Aufgabe"})
            else:
                offen.append(e)
                self.agenda.append({"tag": "", "wann": "", "titel": e.get("text") or "", "art": "aufgabe", "zusatz": f"bis {_tagwort(f, heute)}" if f else "ohne Datum"})
        self.aufgaben_zahl = len(ueber) + len(faellig) + len(offen)
        if ueber:
            self.sag("Heute", "kritisch", f"[[{len(ueber)} {'Aufgabe ist' if len(ueber) == 1 else 'Aufgaben sind'} überfällig]]: {_liste([e.get('text') or '' for e in ueber])}.", "agenda")
        for e in self.typ("erinnerung"):
            notiert = _datum(e.get("tag"))
            if notiert and notiert >= heute - dt.timedelta(days=7):
                self.agenda.append({"tag": "", "wann": "", "titel": e.get("text") or "", "art": "erinnerung", "zusatz": f"Erinnerung von {_tagwort(notiert, heute)}" if notiert == heute else f"Erinnerung vom {notiert.day}.{notiert.month}."})

    # ---------- Geld ----------
    def geld(self) -> None:
        f = self.d.get("finanzen") or {}
        b, p, v = f.get("budget"), f.get("prognose"), f.get("verlauf")
        heute = self.heute
        if not b:
            return
        frei, je_tag, rest = b.get("frei", 0), b.get("je_tag", 0), b.get("rest_tage", 0)
        ton = "gut"
        if frei < 0:
            ton = "kritisch"
            self.sag("Geld", ton, f"Du liegst diesen Monat [[{_eur(frei)} über deinem Spielraum]]. Jede weitere Ausgabe geht vom Ersparten ab.", "Geld")
        elif p and p.get("frei", 0) < 0:
            ton = "kritisch"
            ueblich = max(p.get("ausgaben", 0) - b.get("ausgegeben", 0), 0) / max(rest, 1)
            self.sag("Geld", ton, f"Läuft der Monat wie üblich weiter, [[fehlen am Ende etwa {_eur(p['frei'])}]]. Es geht auf, wenn du bei höchstens "
                     f"[[{_eur(je_tag)} pro Tag]] bleibst statt der üblichen {_eur(ueblich)}.", "Geld")
        else:
            ton = "achtung" if b.get("ampel") in ("gelb", "rot") else "gut"
            self.sag("Geld", ton, f"Du hast noch [[{_eur(frei)} frei]], das sind [[{_eur(je_tag)} pro Tag]] für {rest} Tage."
                     + (f" Bei üblichem Verlauf bleiben am Monatsende etwa {_eur(p['frei'])} übrig." if p else ""), "Geld")
        self.ampeln.append({"bereich": "Geld", "ton": ton, "wert": ("−" if frei < 0 else "") + _eur(frei), "text": "frei diesen Monat" if frei >= 0 else "über dem Spielraum", "ziel": "Geld"})
        # Tempo gegenüber dem üblichen Monatsverlauf
        if v and v.get("ist") and v.get("ueblich") and len(v["ueblich"]) >= len(v["ist"]):
            ist, ueb = v["ist"][-1], v["ueblich"][len(v["ist"]) - 1]
            if ueb > 50 and abs(ist - ueb) >= max(40, ueb * 0.12):
                mehr = ist > ueb
                self.sag("Veränderung", "achtung" if mehr else "gut", f"Bis heute hast du [[{_eur(ist - ueb)} {'mehr' if mehr else 'weniger'}]] ausgegeben als sonst zu diesem Zeitpunkt im Monat.", "Geld")
        # Kategorie der Kreditkarte, die aus dem Rahmen läuft
        kat = [(k["monat"] - k["schnitt"], k) for k in (f.get("karte") or {}).get("kategorien") or [] if k.get("schnitt", 0) > 0 and k["monat"] > k["schnitt"] * 1.1 and k["monat"] - k["schnitt"] > 10]
        if kat:
            ueber, k = max(kat, key=lambda x: x[0])
            self.sag("Geld", "achtung", f"Bei [[{k['name']}]] bist du mit {_eur(k['monat'])} schon [[{_eur(ueber)} über]] deinem Monatsschnitt"
                     + (f" – und der Monat hat noch {rest} Tage." if rest > 3 else "."), "Geld")
        # Girokonto und feste Posten
        if p and p.get("giro_ende") is not None and p["giro_ende"] < 0:
            self.sag("Geld", "kritisch", f"Das Girokonto rutscht bis Monatsende voraussichtlich [[ins Minus (etwa −{_eur(p['giro_ende'])})]], weil noch {_eur(p.get('offen_fix', 0))} feste Posten abgehen.", "Geld")
        else:
            self.ruhig.append("Girokonto")
        bald = []
        for x in (p or {}).get("posten") or []:
            if not x.get("offen") or not x.get("tag") or x.get("betrag", 0) > 0:
                continue
            try:
                tag = heute.replace(day=min(int(x["tag"]), 28))
            except ValueError:
                continue
            if heute <= tag <= heute + dt.timedelta(days=VORAUS):
                self.agenda.append({"tag": tag.isoformat(), "wann": "", "titel": f"{str(x.get('wer', ''))[:34]} · {_eur(x['offen'])}", "art": "posten", "zusatz": "geht voraussichtlich vom Konto ab"})
                if (tag - heute).days <= 3:
                    bald.append(x)
        giro = next((k for k in f.get("konten") or [] if k.get("art") == "giro" and k.get("saldo") is not None), None)
        summe = sum(abs(x["offen"]) for x in bald)
        if bald and giro and giro["saldo"] - summe < 500:      # nur wenn es auf dem Konto eng wird; die Posten selbst stehen in der Agenda
            self.sag("Geld", "achtung" if giro["saldo"] - summe < 0 else "info", f"In den nächsten drei Tagen gehen etwa [[{_eur(summe)} feste Posten]] ab; auf dem Girokonto bleiben dann rund "
                     f"[[{'−' if giro['saldo'] - summe < 0 else ''}{_eur(giro['saldo'] - summe)}]].", "agenda")
        # Wie frisch sind die Kontodaten?
        staende = [s for s in (_datum(k.get("stand")) for k in f.get("konten") or []) if s]
        if staende and (heute - max(staende)).days >= 7:
            alt = max(staende)
            self.sag("Offen", "achtung", f"Die Kontodaten sind vom [[{alt.day}.{alt.month}.]] – alles zu Geld ist seitdem geschätzt. Ein neuer Kontoauszug macht es wieder genau.", "Geld")
        tipps = f.get("tipps") or []
        if tipps and ton != "kritisch":
            t = tipps[0]
            self.sag("Tipp", "info", f"Größter Hebel zum Sparen: [[{t['name']}]] mit im Schnitt {_eur(t['schnitt'])} im Monat. {t['anteil']} % weniger wären etwa {_eur(t['ersparnis'])}.", "Geld")

    def verrechnung(self) -> None:
        c, ich = self.d.get("cospend"), self.d.get("ich") or ""
        offen = ((self.d.get("finanzen") or {}).get("cospend_offen") or {})
        n = offen.get("anzahl") or 0
        if n:
            self.entscheidungen += n
        if not c or not c.get("saldo"):
            return
        saldo = c["saldo"]
        if ich in saldo and len(saldo) >= 2:
            anderer, wert = next(n for n in saldo if n != ich), saldo[ich]
            if wert <= -20:
                self.sag("Geld", "achtung", f"Du schuldest {anderer} aus der gemeinsamen Abrechnung [[{_eur(wert)}]].", "Geld")
            elif wert >= 20:
                self.sag("Geld", "info", f"{anderer} schuldet dir aus der gemeinsamen Abrechnung [[{_eur(wert)}]].", "Geld")
            else:
                self.ruhig.append("gemeinsame Abrechnung")

    def ki(self) -> None:
        c = self.d.get("claude")
        if not c:
            return
        tage = c.get("tage") or []
        je_tag = sum(t.get("usd", 0) for t in tage) / max(len(tage), 1)
        guthaben = c.get("guthaben")
        if (c.get("heute") or {}).get("usd", 0) >= (c.get("tageslimit") or 9e9):
            self.sag("Offen", "achtung", "Das [[Tageslimit für Claude ist erreicht]] – offene Fragen werden erst morgen beantwortet.", "Notiert")
        elif guthaben is not None and je_tag > 0.001 and guthaben / je_tag < 14:
            self.sag("Offen", "achtung", f"Das Claude-Guthaben reicht bei diesem Tempo nur noch etwa [[{round(guthaben / je_tag)} Tage]].", "")
        else:
            self.ruhig.append("Claude-Guthaben")
        neu = [e for e in self.typ("fuer_claude") if (e.get("daten") or {}).get("status") == "beantwortet" and (_datum(e.get("tag")) or dt.date.min) >= self.heute - dt.timedelta(days=1)]
        if neu:
            self.sag("Heute", "info", f"Claude hat {'eine Frage' if len(neu) == 1 else str(len(neu)) + ' Fragen'} beantwortet: [[{_liste([e.get('text') or '' for e in neu], 2)}]].", "Notiert")
        wartet = [e for e in self.typ("fuer_claude") if (e.get("daten") or {}).get("status") == "braucht Claude am Rechner"]
        if wartet:
            self.sag("Offen", "info", f"{len(wartet)} Anliegen {'braucht' if len(wartet) == 1 else 'brauchen'} Claude am Rechner: {_liste([e.get('text') or '' for e in wartet], 2)}.", "Notiert")

    # ---------- Körper ----------
    def koerper(self) -> None:
        g = self.d.get("gesundheit")
        if not g:
            return
        heute, wtag = self.heute, self.heute.weekday()
        montag, rest = heute - dt.timedelta(days=wtag), 6 - wtag
        alle = sorted((t for t in g.get("training_alle") or g.get("training") or [] if _datum(t.get("tag"))), key=lambda t: t["tag"])
        woche = [t for t in alle if _datum(t["tag"]) >= montag]
        fehlt = max(0, WOCHENZIEL - len(woche))
        heute_trainiert = any(_datum(t["tag"]) == heute for t in woche)
        moeglich = rest + (0 if heute_trainiert else 1)        # Tage, an denen diese Woche noch trainiert werden kann
        letzte = _datum(alle[-1]["tag"]) if alle else None
        nacht, schnitt_schlaf = self._schlaf(g)
        muede = nacht is not None and schnitt_schlaf is not None and nacht <= schnitt_schlaf - 45
        if alle or g.get("tage"):
            if not fehlt:
                wochen = self._serie(alle, montag)
                self.sag("Körper", "gut", f"Wochenziel erreicht: [[{len(woche)} Trainings]]" + (f" – die {wochen}. Woche in Folge." if wochen >= 2 else "."), "Körper")
                ton = "gut"
            elif fehlt > moeglich:
                self.sag("Körper", "kritisch", f"Das Wochenziel ist nicht mehr zu schaffen: [[{len(woche)} von {WOCHENZIEL}]] Trainings, es {'bleibt' if moeglich == 1 else 'bleiben'} nur noch "
                         f"{moeglich} {'Tag' if moeglich == 1 else 'Tage'}. Ein Training jetzt hält trotzdem den Rhythmus.", "Körper")
                ton = "kritisch"
            else:
                frei = self._freie_tage(heute, rest, heute_trainiert)
                eng = fehlt == moeglich
                text = (f"Noch [[{fehlt} {'Training' if fehlt == 1 else 'Trainings'}]] bis Sonntag" + (f" – das geht nur, wenn du [[ab heute jeden Tag]] trainierst." if eng and fehlt > 1 else
                        " – [[heute ist die letzte Gelegenheit]]." if eng else f", {moeglich} Tage Zeit."))
                if frei and not eng:
                    text += f" Im Kalender frei {'ist' if len(frei) == 1 else 'sind'} [[{_liste(frei, 3)}]]."
                if muede and not heute_trainiert:
                    text += " Nach der kurzen Nacht heute eher locker."
                self.sag("Körper", "achtung" if eng or (letzte and (heute - letzte).days >= 4) else "info", text, "Körper")
                ton = "achtung" if eng else "info"
            if fehlt and letzte and (heute - letzte).days >= 5:
                self.sag("Veränderung", "achtung", f"Dein letztes Training ist [[{(heute - letzte).days} Tage]] her.", "Körper")
            self.ampeln.append({"bereich": "Training", "ton": "gut" if ton == "gut" else ton if ton != "info" else "", "wert": f"{len(woche)} von {WOCHENZIEL}", "text": "diese Woche", "ziel": "Körper"})
        # Schlaf
        if nacht is not None:
            if muede:
                self.sag("Körper", "achtung", f"Letzte Nacht [[{_dauer(nacht)}]] Schlaf, das sind {_dauer(schnitt_schlaf - nacht)} weniger als dein Schnitt. Heute früher ins Bett lohnt sich.", "Körper")
            elif schnitt_schlaf is not None and nacht >= schnitt_schlaf + 45:
                self.sag("Körper", "gut", f"Letzte Nacht [[{_dauer(nacht)}]] Schlaf – deutlich mehr als dein Schnitt von {_dauer(schnitt_schlaf)}.", "Körper")
            self.ampeln.append({"bereich": "Schlaf", "ton": "achtung" if muede else "gut" if schnitt_schlaf else "", "wert": _dauer(nacht), "text": "letzte Nacht", "ziel": "Körper"})
        else:
            naechte = [_datum(t["tag"]) for t in g.get("tage") or [] if t.get("schlaf_min")]
            if naechte and (heute - max(naechte)).days >= 3:
                self.sag("Offen", "info", f"Schlaf wird seit [[{(heute - max(naechte)).days} Tagen]] nicht mehr erfasst – das Band nachts tragen, sonst fehlt dieser Teil.", "Körper")
        # Schritte: heute hochgerechnet und der Wochenvergleich
        je = {_datum(t["tag"]): t.get("schritte") for t in g.get("tage") or [] if t.get("schritte")}
        davor7 = [je[t] for t in (heute - dt.timedelta(days=i) for i in range(1, 8)) if t in je]
        davor14 = [je[t] for t in (heute - dt.timedelta(days=i) for i in range(8, 15)) if t in je]
        schnitt = _mittel(davor7)
        jetzt = ((g.get("aktuell") or {}).get("schritte") or {}).get("wert")
        if jetzt is not None and schnitt:
            stunde = self.jetzt.hour + self.jetzt.minute / 60
            anteil = max(0.15, min(1.0, (stunde - 7) / 15))             # wacher Tag grob 7 bis 22 Uhr
            hoch = jetzt / anteil
            if stunde >= 11:
                if hoch < schnitt * 0.75:
                    self.sag("Körper", "achtung", f"Bewegung: Bis heute Abend werden es etwa [[{_zahl(round(hoch, -2))} Schritte]], dein Schnitt liegt bei {_zahl(schnitt)}. "
                             f"Ein Spaziergang von {max(10, round((schnitt - hoch) / 100 / 5) * 5)} Minuten gleicht das aus.", "Körper")
                elif hoch > schnitt * 1.25:
                    self.sag("Körper", "gut", f"Bewegung: Heute läuft es auf etwa [[{_zahl(round(hoch, -2))} Schritte]] hinaus – deutlich über deinem Schnitt von {_zahl(schnitt)}.", "Körper")
            self.ampeln.append({"bereich": "Schritte", "ton": "achtung" if stunde >= 11 and hoch < schnitt * 0.75 else "gut" if stunde >= 11 else "", "wert": _zahl(jetzt), "text": f"heute · Schnitt {_zahl(schnitt)}", "ziel": "Körper"})
        if len(davor7) >= 5 and len(davor14) >= 5:
            a, b = _mittel(davor7), _mittel(davor14)
            if b and abs(a - b) >= max(1000, b * 0.15):
                self.sag("Veränderung", "gut" if a > b else "achtung", f"In den letzten sieben Tagen bist du im Schnitt [[{_zahl(abs(a - b))} Schritte {'mehr' if a > b else 'weniger'}]] pro Tag gegangen als in der Woche davor.", "Körper")
        tv = g.get("training_vorschlaege") or []
        if tv:
            self.entscheidungen += len(tv)

    def _schlaf(self, g: dict) -> tuple[int | None, float | None]:
        """Schlaf der letzten Nacht und der eigene Schnitt (nur bei mindestens fünf Nächten Vergleichsdaten)."""
        je = {_datum(t["tag"]): t["schlaf_min"] for t in g.get("tage") or [] if t.get("schlaf_min")}
        nacht = je.get(self.heute)
        andere = [v for t, v in je.items() if t != self.heute]
        return nacht, _mittel(andere) if len(andere) >= 5 else None

    def _serie(self, alle: list[dict], montag: dt.date) -> int:
        """Wie viele Kalenderwochen in Folge (die laufende eingeschlossen) das Wochenziel erreicht wurde."""
        je: dict[dt.date, int] = {}
        for t in alle:
            tag = _datum(t["tag"])
            je[tag - dt.timedelta(days=tag.weekday())] = je.get(tag - dt.timedelta(days=tag.weekday()), 0) + 1
        n, woche = 0, montag
        while je.get(woche, 0) >= WOCHENZIEL:
            n, woche = n + 1, woche - dt.timedelta(days=7)
        return n

    def _freie_tage(self, heute: dt.date, rest: int, heute_trainiert: bool) -> list[str]:
        """Tage der restlichen Woche ohne Termin mit Uhrzeit – nur wenn überhaupt ein Kalender verbunden ist."""
        if self.d.get("kalender") is None:
            return []
        frei = []
        for i in range(1 if heute_trainiert else 0, rest + 1):
            tag = heute + dt.timedelta(days=i)
            if not any(not t.get("ganztags") for t in self.termine_je_tag.get(tag, [])):
                frei.append(_tagwort(tag, heute))
        alle_tage = rest + (0 if heute_trainiert else 1)
        return frei if len(frei) < alle_tage else []    # „alles frei“ hilft bei der Wahl des Tages nicht
    # ---------- Übriges ----------
    def profil(self) -> None:
        v = (self.d.get("profil") or {}).get("vorschlaege") or []
        if v:
            self.entscheidungen += len(v)

    def kopf(self) -> str:
        """Ein Satz, der den Tag zusammenfasst: erst was ansteht, dann was Aufmerksamkeit braucht."""
        teile = []
        n_t = len(getattr(self, "termine_je_tag", {}).get(self.heute, []))
        if self.d.get("kalender") is not None:
            teile.append("kein Termin" if not n_t else "ein Termin" if n_t == 1 else f"{n_t} Termine")
        a = getattr(self, "aufgaben_zahl", 0)
        if a:
            teile.append("eine Aufgabe offen" if a == 1 else f"{a} Aufgaben offen")
        if self.entscheidungen:
            teile.append("eine Entscheidung wartet" if self.entscheidungen == 1 else f"{self.entscheidungen} Entscheidungen warten")
        satz = ("Heute: " + ", ".join(teile) + ".") if teile else ""
        kritisch = [h for h in self.hinweise if h["ton"] == "kritisch"]
        achtung = [h for h in self.hinweise if h["ton"] == "achtung"]
        if kritisch:
            bereiche = sorted({h["bereich"] for h in kritisch if h["bereich"] in ("Geld", "Körper")})
            satz += " Aufpassen bei " + " und ".join(bereiche) + "." if bereiche else " Etwas ist überfällig."
        elif not achtung and self.hinweise:
            satz += " Sonst ist alles im Rahmen."
        return satz.strip()

    def bauen(self) -> dict:
        self.entscheidungen = 0
        self.termine_je_tag = {}
        for schritt in (self.termine, self.aufgaben, self.geld, self.verrechnung, self.koerper, self.ki, self.profil):
            try:
                schritt()
            except (KeyError, TypeError, ValueError, AttributeError, StopIteration):
                continue          # unerwartete Form einer Quelle: diese eine Regelgruppe schweigt, der Rest bleibt
        reihenfolge = ("Heute", "Geld", "Körper", "Veränderung", "Offen", "Tipp")
        self.hinweise.sort(key=lambda h: (h["ton"] != "kritisch", reihenfolge.index(h["bereich"]) if h["bereich"] in reihenfolge else 9))   # sonst in der Reihenfolge der Regeln
        self.agenda.sort(key=lambda a: (a["tag"] == "", a["tag"], not a.get("dringend"), a["wann"] or "99"))
        return {"datum": self.heute.isoformat(), "wochentag": WOCHENTAGE[self.heute.weekday()], "kopf": self.kopf(), "ampeln": self.ampeln,
                "hinweise": self.hinweise, "agenda": self.agenda, "ruhig": self.ruhig, "entscheidungen": self.entscheidungen}


def erstellen(schnappschuss: dict, jetzt: dt.datetime) -> dict:
    return _Guide(schnappschuss, jetzt).bauen()
