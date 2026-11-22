#!/usr/bin/env bash
# Prüft vor einem Push, dass nichts Privates im Repository steht:
# Heimnetz-Adressen, Schlüssel/Tokens und – freiwillig – eigene Wörter (Namen, Domains).
#
#   scripts/privat-pruefung.sh [DATEI_MIT_EIGENEN_WOERTERN]
#
# Die Wörterdatei (ein Wort je Zeile) liegt außerhalb des Repositorys. Geprüft werden alle Dateien,
# die Git kennt oder aufnehmen würde, sowie die Texte aller bisherigen Commits.
set -u
cd "$(git rev-parse --show-toplevel)" || exit 2
fund=0

suche() { # $1 = Beschreibung, $2 = Muster (erweiterter regulärer Ausdruck), $3 = grep-Zusatz
  local treffer
  treffer=$( { git ls-files -co --exclude-standard -z | xargs -0 -r grep -nIE ${3:-} -e "$2" --; \
               git log --all --format='Commit %h: %an <%ae> %s %b' 2>/dev/null | grep -E ${3:-} -e "$2"; } \
             | grep -v -e '^scripts/privat-pruefung.sh:' -e '<noreply@anthropic.com>' )
  if [ -n "$treffer" ]; then echo "✗ $1:"; echo "$treffer" | sed 's/^/    /'; fund=1; else echo "✓ $1: nichts"; fi
}

# 192.0.2.x ist der Dokumentationsbereich und ausdrücklich erlaubt.
suche "Heimnetz-Adressen" '(^|[^0-9.])(10\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|192\.168\.[0-9]{1,3}\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01])\.[0-9]{1,3}\.[0-9]{1,3})([^0-9]|$)'
suche "Schlüssel und Tokens" '(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|xox[abp]-[A-Za-z0-9-]{10,})'
suche "Fest eingetragene Zugänge" '(passwor[dt]|token|secret|api[_-]?key)[A-Za-z_]*["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"'][^"'"'"'$ {<]{8,}["'"'"']' -i
suche "E-Mail-Adressen" '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.(com|de|net|org|space|io)\b'
if [ -n "${1:-}" ] && [ -r "$1" ]; then
  muster=$(grep -v '^[[:space:]]*$' "$1" | paste -sd'|')
  [ -n "$muster" ] && suche "Eigene Wörter" "($muster)" -i
fi
[ $fund -eq 0 ] && echo "Bestanden." || echo "Bitte prüfen, bevor etwas hochgeladen wird."
exit $fund
