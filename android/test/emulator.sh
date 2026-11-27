#!/usr/bin/env bash
# Prüft die App in einem laufenden Emulator. Aufruf aus dem Hauptordner des Repositorys.
#
# Fertige App (release) gegen das echte ntfy.sh, auf einem Zufallsthema nur für diesen Lauf:
# Einrichten per Link, Lagebericht des echten Radars, Zustellung eines Alarms, Funkloch,
# Ruhezustand (Doze), abgestürzter Dienst und Neustart des Handys. Testbau (debug) gegen einen
# nachgestellten Server (android/test/fake_ntfy.py auf Port 8765): Anzeige bei einem Blackout und
# Einrichten ohne Netz.
#
# Was die App anzeigt, liest seite.py aus der Seite selbst. Ob das Bild am Handy einer Änderung
# auch folgt, zeigt der Vergleich zweier Bildschirmfotos (Vorschau.java). Am Ende steht die Frage,
# ob die App im Lauf abgestürzt ist, mit einem absichtlichen Absturz des Testbaus als Gegenprobe.
# Ergebnisse (Bilder, Ablauf, Protokolle) landen in $OUT.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT:-$PWD/ergebnis}"
APK_DIR="${APK_DIR:-$PWD/apk}"
PKG=io.github.sebastianeder09.blackoutradar
DBG=$PKG.debug
NTFY=https://ntfy.sh
TOPIC="br-ci-$(openssl rand -hex 8)"
mkdir -p "$OUT"
FAILED=0
RESULTS=()

log() { echo "[$(date -u +%H:%M:%S)] $*" | tee -a "$OUT/ablauf.txt"; }
ok() { log "OK: $*"; RESULTS+=("✅ $*"); }
bad() { log "FEHLER: $*"; RESULTS+=("❌ $*"); FAILED=$((FAILED + 1)); }

quiet_system() {  # Hinweise von Android, dass eine App hängt oder abgestürzt ist, liegen über allem: schließen und vermerken
  local note
  note=$(adb shell dumpsys window windows 2> /dev/null | tr -d '\r' | grep -oE 'Application (Not Responding|Error): [A-Za-z0-9._]+' | head -1)
  [ -z "$note" ] && return 0
  log "Hinweis von Android geschlossen: $note"
  adb shell am broadcast -a android.intent.action.CLOSE_SYSTEM_DIALOGS > /dev/null 2>&1
  sleep 2
}

snap() { adb exec-out screencap -p > "$OUT/$1.png" && log "Bild $1"; }  # Name: Bild, so wie es gerade ist
shot() { sleep "${2:-1}"; quiet_system; snap "$1"; }  # Name [Wartezeit]: Bild der App, ohne fremde Hinweise darüber

publish() {  # Titel Priorität Schlagworte Text
  curl -sS --retry 3 -H "Title: $1" -H "Priority: $2" -H "Tags: $3" -d "$4" "$NTFY/$TOPIC" > /dev/null \
    || log "Senden an ntfy.sh fehlgeschlagen: $1"
}

has_notification() { adb shell dumpsys notification --noredact 2> /dev/null | grep -qF "$1"; }

wait_notification() {  # Text Sekunden -> gibt die Wartezeit in Sekunden aus
  local start
  start=$(date +%s)
  while [ $(($(date +%s) - start)) -lt "$2" ]; do
    if has_notification "$1"; then
      echo $(($(date +%s) - start))
      return 0
    fi
    sleep 1
  done
  return 1
}

page() {  # Paket [Ausdruck] -> Text der Seite, wie die App sie gerade zeigt, oder Ergebnis des Ausdrucks
  python3 "$HERE/seite.py" "$@" 2> "$OUT/seite-fehler.txt"
}

page_has() {  # Paket Text: steht der Text gerade in der Seite der App?
  local text=""
  for _ in 1 2 3 4 5 6 7 8; do
    text=$(page "$1") && grep -qF -- "$2" <<< "$text" && return 0
    sleep 2
  done
  if [ -s "$OUT/seite-fehler.txt" ]; then
    log "Seite von $1 nicht lesbar: $(tr '\n' ' ' < "$OUT/seite-fehler.txt")"
  else
    log "Seite von $1 zeigt nicht \"$2\", sondern: $(head -c 300 <<< "$text" | tr '\n' '|')"
  fi
  return 1
}

wait_page() {  # Paket Text Sekunden -> gibt die Wartezeit in Sekunden aus, sobald der Text in der Seite steht
  local start text
  start=$(date +%s)
  while [ $(($(date +%s) - start)) -lt "$3" ]; do
    if text=$(page "$1") && grep -qF -- "$2" <<< "$text"; then
      echo $(($(date +%s) - start))
      return 0
    fi
    sleep 2
  done
  return 1
}

setup_debug() {  # richtet den Testbau am nachgestellten Server ein -> Antwort der App, siehe DebugReceiver
  adb shell am broadcast -n "$DBG/$PKG.DebugReceiver" --es ziel http://10.0.2.2:8765/testthema --es status http://10.0.2.2:8765 \
    2> /dev/null | tr -d '\r' | sed -n 's/.*data="\(.*\)".*/\1/p'
}

layout() {  # Paket Name: Kopfzeile oben, Leiste unten, nichts ragt seitlich hinaus (aufbau.js)
  local verdict
  verdict=$(page "$1" "$(cat "$HERE/aufbau.js")")
  log "Aufbau $2: ${verdict:-nicht lesbar}"
  [[ "$verdict" == ok* ]]
}

changed() {  # Bild1 Bild2 Von Bis: hat sich das Bild zwischen den beiden Höhen (Prozent von oben) geändert?
  local verdict code
  verdict=$(java -Djava.awt.headless=true "$HERE/Vorschau.java" vergleichen "$OUT/$1.png" "$OUT/$2.png" "$3" "$4" 2> "$OUT/vergleich-fehler.txt")
  code=$?
  log "Vergleich $1 mit $2: ${verdict:-nicht möglich, $(head -c 300 "$OUT/vergleich-fehler.txt" | tr '\n' ' ')}"
  return $code
}

# Zwei Stellen, an denen Android Abstürze und Hänger festhält:
# 1. Die Liste der Prozessenden mit ihrem Grund. Sie reicht nur bis zum letzten Neustart sicher zurück,
#    deshalb fragt der Test sie vor dem Neustart und am Schluss ab.
# 2. Die Fehlerberichte (dropbox) mit dem Wortlaut des Fehlers. Sie bleiben über Neustarts erhalten.
exits() {  # Paket: eine Zeile je Prozessende, z. B. "reason=2 (SIGNALED) subreason=0 (UNKNOWN) status=9"
  # Android 12 schreibt jede Angabe in eine eigene Zeile. "subreason=" zählt dort nicht als Grund.
  adb shell dumpsys activity exit-info "$1" 2> /dev/null | tr -d '\r' | grep -oE '(^|[[:space:]])reason=[0-9].*' | sed 's/^[[:space:]]*//'
}

note_exits() {  # Datei: Prozessenden der fertigen App und des Testbaus bis jetzt festhalten
  { exits "$PKG" | sed 's/^/fertige App: /'; exits "$DBG" | sed 's/^/Testbau: /'; } > "$OUT/$1"
}

# Absturz (Java), Absturz (nativ), Hänger, Start misslungen. Am Zeilenanfang oder nach dem Namen der App,
# damit ein harmloser Untergrund wie "subreason=4 (TRIM EMPTY)" nicht als Absturz zählt.
BAD_EXIT='(^|: )reason=(4|5|6|7) '

reports() {  # Paket Datei: Fehlerberichte von Android zu Abstürzen und Hängern dieses Pakets
  local tag
  for tag in data_app_crash data_app_native_crash data_app_anr; do
    adb shell dumpsys dropbox --print "$tag" 2> /dev/null | tr -d '\r'
  done > "$OUT/$2"
  grep -F -A 25 "Process: $1" "$OUT/$2"
}

service_running() { adb shell dumpsys activity services "$1/.ListenerService" 2> /dev/null | grep -q "ServiceRecord"; }

wait_boot() {
  adb wait-for-device
  local start
  start=$(date +%s)
  until [ "$(adb shell getprop sys.boot_completed 2> /dev/null | tr -d '\r')" = "1" ]; do
    [ $(($(date +%s) - start)) -gt 300 ] && return 1
    sleep 2
  done
  adb shell input keyevent KEYCODE_WAKEUP > /dev/null 2>&1
  adb shell wm dismiss-keyguard > /dev/null 2>&1
  return 0
}

SDK=$(adb shell getprop ro.build.version.sdk | tr -d '\r')
log "Android API $SDK, Testthema $TOPIC"
adb shell settings put global window_animation_scale 0
adb shell settings put global transition_animation_scale 0
adb shell settings put global animator_duration_scale 0

adb install -r "$APK_DIR/blackout-radar.apk" > /dev/null && ok "Fertige App installiert" || bad "Fertige App ließ sich nicht installieren"
adb install -r "$APK_DIR/blackout-radar-test.apk" > /dev/null || bad "Testbau ließ sich nicht installieren"
for p in $PKG $DBG; do
  [ "$SDK" -ge 33 ] && adb shell pm grant "$p" android.permission.POST_NOTIFICATIONS
  adb shell dumpsys deviceidle whitelist +"$p" > /dev/null
done

log "Bildschirm: $(adb shell wm size | tr -d '\r' | tr '\n' ' ')$(adb shell wm density | tr -d '\r' | tr '\n' ' ')"

# ------------------------------------------------------------ Testbau: Blackout
adb shell am start -W -n "$DBG/$PKG.MainActivity" > /dev/null
page_has "$DBG" "Alarme auf dieses Handy holen" && ok "Testbau: Einrichten wird angezeigt" || bad "Testbau: Einrichten fehlt"
shot 00-einrichten
# Kurz nach dem Start hat der Emulator manchmal noch kein Netz. Die Anzeige bei einem Blackout braucht den
# nachgestellten Server, deshalb richtet der Test ein, bis der Server geantwortet hat, und vermerkt jede Antwort.
# Was die App tut, wenn beim Einrichten kein Netz da ist, prüft weiter unten ein eigener Schritt.
answer=""
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  answer=$(setup_debug)
  log "Testbau einrichten, Versuch $attempt: ${answer:-keine Antwort}"
  [[ "$answer" == *"ohne-netz=false, lagebericht=true"* ]] && break
  sleep 3
done
[[ "$answer" == *"ohne-netz=false, lagebericht=true"* ]] && ok "Testbau: am nachgestellten Server eingerichtet" \
  || bad "Testbau: nachgestellter Server aus dem Emulator nicht erreichbar"
sleep 4
adb shell am start -n "$DBG/$PKG.MainActivity" --es tab lage > /dev/null
page_has "$DBG" "Laufender Stromausfall" && ok "Testbau: Lagebericht mit laufendem Blackout angezeigt" || bad "Testbau: Lagebericht fehlt"
shot 10-blackout-lage
layout "$DBG" "Testbau" && ok "Testbau: Kopfzeile und Leiste sitzen richtig" || bad "Testbau: Aufbau der Seite stimmt nicht"
adb shell am start -n "$DBG/$PKG.MainActivity" --es tab meldungen > /dev/null
page_has "$DBG" "Die App behält die letzten 300 Meldungen" && ok "Testbau: Liste der Meldungen angezeigt" || bad "Testbau: Liste der Meldungen fehlt"
shot 11-blackout-meldungen
# Eine Meldung kommt, während die Liste offen ist und niemand das Handy berührt. Bis zum Bild fragt
# auch der Test die Seite nicht, damit die Anzeige wirklich von selbst nachziehen muss.
curl -sS -H "Title: Testbau live" -H "Priority: 4" -H "Tags: warning" -d "Zustellung im Testbau" http://127.0.0.1:8765/testthema > /dev/null
if t=$(wait_notification "Testbau live" 40); then ok "Testbau: neue Meldung nach $t s als Benachrichtigung"; else bad "Testbau: neue Meldung nicht als Benachrichtigung"; fi
shot 14-blackout-neue-meldung 7  # erst wenn der Hinweis von Android am oberen Rand wieder weg ist
changed 11-blackout-meldungen 14-blackout-neue-meldung 30 90 \
  && ok "Testbau: Bild der offenen Liste zieht von selbst nach" || bad "Testbau: Bild der offenen Liste bleibt stehen"
page_has "$DBG" "Testbau live" && ok "Testbau: neue Meldung steht in der offenen Liste" || bad "Testbau: neue Meldung fehlt in der offenen Liste"
adb shell am start -n "$DBG/$PKG.MainActivity" --es tab app > /dev/null
page_has "$DBG" "Meldungen kommen sofort an" && ok "Testbau: Verbindung wird als bestehend angezeigt" || bad "Testbau: Anzeige der Verbindung stimmt nicht"
shot 12-blackout-app
adb shell cmd uimode night yes > /dev/null
adb shell am start -n "$DBG/$PKG.MainActivity" --es tab lage > /dev/null
sleep 2
[ "$(page "$DBG" "document.documentElement.getAttribute('data-theme')")" = "dark" ] \
  && ok "Testbau: dunkle Darstellung folgt dem Handy" || bad "Testbau: dunkle Darstellung nicht übernommen"
shot 13-blackout-lage-dunkel
adb shell cmd uimode night no > /dev/null
adb shell am force-stop "$DBG"

# ------------------------------------------------- Fertige App gegen ntfy.sh
publish "CI Vorab" 3 zap "Diese Meldung lag schon vor dem Einrichten auf dem Thema."
sleep 3
adb shell am start -W -a android.intent.action.VIEW -d "blackoutradar://abo/$TOPIC" -p "$PKG" > /dev/null
page_has "$PKG" "Meldung der letzten 12 Stunden" && ok "Einrichten per Link: Thema übernommen, vorhandene Meldung gefunden" \
  || bad "Einrichten per Link: Ergebnis nicht wie erwartet"
shot 01-eingerichtet
page "$PKG" "document.querySelector('.result .btn.primary').click()" > /dev/null  # Knopf "Weiter"
shot 02-lage 4  # bis zum Bild fragt der Test die Seite nicht weiter
changed 01-eingerichtet 02-lage 15 90 && ok "Bild folgt dem Wechsel zur Lage von selbst" || bad "Bild bleibt nach dem Wechsel zur Lage stehen"
page_has "$PKG" "Lagebericht des Blackout-Radars" && ok "Lagebericht des echten Radars geladen und angezeigt" \
  || bad "Lagebericht des echten Radars fehlt"
layout "$PKG" "fertige App" && ok "Kopfzeile und Leiste sitzen richtig" || bad "Aufbau der Seite stimmt nicht"

for _ in $(seq 1 30); do service_running "$PKG" && break; sleep 1; done
service_running "$PKG" && ok "Hintergrunddienst läuft" || bad "Hintergrunddienst läuft nicht"
sleep 5

publish "CI Alarm live" 5 rotating_light "Probe aus dem Emulator-Test: so kommt ein Alarm an."
if t=$(wait_notification "CI Alarm live" 60); then ok "Alarm über ntfy.sh nach $t s angekommen"; else bad "Alarm über ntfy.sh nicht angekommen"; fi
adb shell dumpsys notification --noredact > "$OUT/benachrichtigungen-alarm.txt"
grep -q "channel=alarm_laut" "$OUT/benachrichtigungen-alarm.txt" && ok "Alarm läuft über den lauten Alarm-Kanal" || bad "Alarm nicht im lauten Alarm-Kanal"
quiet_system  # nicht erst beim Bild: Das Schließen würde die aufgezogene Leiste wieder einklappen
adb shell cmd statusbar expand-notifications > /dev/null 2>&1
sleep 2
snap 03-benachrichtigung
adb shell cmd statusbar collapse > /dev/null 2>&1

# Funkloch: Meldung kommt, während das Handy kein Netz hat
adb shell svc wifi disable
adb shell svc data disable
sleep 8
publish "CI Funkloch" 4 warning "Diese Meldung kam, während das Handy kein Netz hatte."
sleep 10
if has_notification "CI Funkloch"; then
  bad "Funkloch nicht wirksam: Meldung kam trotz abgeschaltetem Netz"
fi
adb shell svc wifi enable
adb shell svc data enable
if t=$(wait_notification "CI Funkloch" 150); then ok "Nach dem Funkloch nachgeholt, $t s nach Rückkehr des Netzes"; else bad "Nach dem Funkloch nicht nachgeholt"; fi

# Ruhezustand: Bildschirm aus, Gerät im tiefen Doze
adb shell dumpsys battery unplug
adb shell input keyevent KEYCODE_SLEEP
sleep 2
adb shell dumpsys deviceidle force-idle > /dev/null
log "Doze: $(adb shell dumpsys deviceidle get deep | tr -d '\r')"
sleep 5
publish "CI Ruhezustand" 5 rotating_light "Diese Meldung kam im Ruhezustand des Handys."
if t=$(wait_notification "CI Ruhezustand" 120); then ok "Im Ruhezustand (Doze) nach $t s angekommen"; else bad "Im Ruhezustand nicht angekommen"; fi
adb shell dumpsys deviceidle unforce > /dev/null
adb shell dumpsys battery reset
adb shell input keyevent KEYCODE_WAKEUP
adb shell wm dismiss-keyguard > /dev/null 2>&1

# Absturz: Android beendet den Prozess hart
if adb root > /dev/null 2>&1 && wait_boot; then
  sleep 3
  pid=$(adb shell pidof "$PKG" | tr -d '\r')
  if [ -n "$pid" ]; then
    adb shell kill -9 "$pid"
    log "Prozess $pid hart beendet"
    sleep 5
    publish "CI Nach Absturz" 4 warning "Diese Meldung kam, nachdem Android die App beendet hatte."
    if t=$(wait_notification "CI Nach Absturz" 240); then ok "Nach hartem Beenden wieder verbunden, Meldung nach $t s"; else bad "Nach hartem Beenden keine Meldung"; fi
  else
    bad "Prozess der App nicht gefunden"
  fi
  adb unroot > /dev/null 2>&1
  wait_boot
else
  log "adb root nicht möglich, Absturz-Test übersprungen"
fi

# Neustart des Handys
note_exits enden-vor-neustart.txt
adb reboot
if wait_boot; then
  sleep 25
  service_running "$PKG" && ok "Dienst nach dem Neustart von selbst wieder gestartet" || bad "Dienst nach dem Neustart nicht gestartet"
  publish "CI Nach Neustart" 4 warning "Diese Meldung kam nach einem Neustart des Handys."
  if t=$(wait_notification "CI Nach Neustart" 180); then ok "Nach dem Neustart Meldung nach $t s"; else bad "Nach dem Neustart keine Meldung"; fi
else
  bad "Emulator kam nach dem Neustart nicht hoch"
fi

# Nach dem Neustart: Die Liste muss alles enthalten, was in diesem Lauf kam (auch von vor dem Neustart).
adb shell am start -W -n "$PKG/.MainActivity" --es tab meldungen > /dev/null
missing=""
for title in "CI Vorab" "CI Alarm live" "CI Funkloch" "CI Ruhezustand" "CI Nach Neustart"; do
  page_has "$PKG" "$title" || missing="$missing \"$title\""
done
[ -z "$missing" ] && ok "Liste der Meldungen vollständig, auch nach dem Neustart" || bad "In der Liste der Meldungen fehlt:$missing"
shot 04-meldungen
adb shell am start -n "$PKG/.MainActivity" --es tab app > /dev/null
page_has "$PKG" "Meldungen kommen sofort an" && ok "Verbindung wird als bestehend angezeigt" || bad "Anzeige der Verbindung stimmt nicht"
shot 05-app
# Weitergeben an ein weiteres Handy: Karte mit dem Knopf, dann zeigt Android seine Auswahl mit der fertigen Nachricht.
page_has "$PKG" "App und Thema weitergeben" && ok "Knopf zum Weitergeben an weitere Handys vorhanden" || bad "Knopf zum Weitergeben fehlt"
page "$PKG" "[...document.querySelectorAll('h3')].find(h => h.textContent === 'Weitere Handys').scrollIntoView({ block: 'center' })" > /dev/null
shot 05b-weitere-handys
page "$PKG" "Native.share()" > /dev/null
sleep 3
adb shell dumpsys activity activities 2> /dev/null | grep -q "ChooserActivity" \
  && ok "Weitergeben öffnet die Auswahl von Android" || bad "Weitergeben öffnet die Auswahl von Android nicht"
snap 06-weitergeben
adb shell input keyevent KEYCODE_BACK
adb shell am start -n "$PKG/.MainActivity" --es tab lage > /dev/null
shot 07-lage 3

# ------------------------------------------------- Testbau: Einrichten ohne Netz
# Die App merkt sich das Thema, verbindet sich, sobald das Netz da ist, und holt dann nach, was der Server von
# vorher noch hat. Diese älteren Meldungen kommen still in die Liste, sie läuten nicht. Der Schritt steht am
# Schluss, damit das Ab- und Einschalten des Netzes keine andere Prüfung stört.
old_title=$(curl -sS "http://127.0.0.1:8765/testthema/json?poll=1&since=all" | python3 -c 'import json, sys; print(json.loads(sys.stdin.readline())["title"].split(":")[0])')
adb shell am start -W -n "$DBG/$PKG.MainActivity" --es tab meldungen > /dev/null
adb shell svc wifi disable
adb shell svc data disable
sleep 8
answer=$(setup_debug)
log "Testbau ohne Netz einrichten: ${answer:-keine Antwort}"
[[ "$answer" == *"ok=true"*"ohne-netz=true"* ]] && ok "Testbau: Einrichten ohne Netz wird gespeichert" || bad "Testbau: Einrichten ohne Netz nicht wie erwartet"
page_has "$DBG" "Noch keine Meldungen" && ok "Testbau: Liste ohne Netz zunächst leer" || bad "Testbau: Liste nach dem Einrichten ohne Netz nicht leer"
adb shell svc wifi enable
adb shell svc data enable
if [ -n "$old_title" ] && t=$(wait_page "$DBG" "$old_title" 150); then
  ok "Testbau: ältere Meldungen nachgeholt, $t s nach Rückkehr des Netzes"
else
  bad "Testbau: ältere Meldungen nach dem Einrichten ohne Netz nicht nachgeholt (gesucht: \"$old_title\")"
fi
has_notification "$old_title" && bad "Testbau: nachgeholte ältere Meldung hat geläutet" || ok "Testbau: nachgeholte ältere Meldungen bleiben still"
shot 15-nachgeholt

adb logcat -d > "$OUT/logcat.txt" 2>&1
adb shell dumpsys notification --noredact > "$OUT/benachrichtigungen.txt" 2>&1
adb shell dumpsys activity services "$PKG" > "$OUT/dienste.txt" 2>&1
rm -f "$OUT/seite-fehler.txt" "$OUT/vergleich-fehler.txt"

# Ist die fertige App oder der Testbau im Lauf abgestürzt oder hängen geblieben?
note_exits enden-am-schluss.txt
log "Prozessenden im Lauf: $(sort -u "$OUT/enden-vor-neustart.txt" "$OUT/enden-am-schluss.txt" | tr '\n' ';')"
died=$(sort -u "$OUT/enden-vor-neustart.txt" "$OUT/enden-am-schluss.txt" | grep -E "$BAD_EXIT")
found=$(reports "$PKG" fehlerberichte.txt)
if [ -n "$died" ] || [ -n "$found" ]; then
  bad "Die App ist im Lauf abgestürzt oder hängen geblieben"
  [ -n "$died" ] && echo "$died"
  [ -n "$found" ] && head -60 <<< "$found"
else
  ok "Kein Absturz und kein Hänger der App im ganzen Lauf"
fi
# Gegenprobe: Ein absichtlicher Absturz des Testbaus muss an denselben Stellen auftauchen,
# sonst wäre die Prüfung darüber nichts wert.
adb shell am start -W -n "$DBG/$PKG.MainActivity" > /dev/null
sleep 2
before=$(adb shell pidof "$DBG" | tr -d '\r')
adb shell am broadcast -n "$DBG/$PKG.DebugReceiver" --ez absturz true > /dev/null 2>&1
listed=nein
for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 2
  exits "$DBG" | grep -qE "$BAD_EXIT" && listed=ja && break
done
reports "$DBG" gegenprobe.txt > /dev/null && reported=ja || reported=nein
log "Gegenprobe: Prozess vorher ${before:-keiner}, danach $(adb shell pidof "$DBG" | tr -d '\r' | grep . || echo keiner)." \
  "In den Prozessenden: $listed ($(exits "$DBG" | grep -E "$BAD_EXIT" | head -1))." \
  "In den Fehlerberichten: $reported ($(adb shell dumpsys dropbox data_app_crash 2> /dev/null | tr -d '\r' | grep -c 'data_app_crash (') Berichte über Abstürze insgesamt)."
[ "$listed" = ja ] && ok "Gegenprobe: ein absichtlicher Absturz wird erkannt" \
  || bad "Gegenprobe: absichtlicher Absturz nicht erkannt, die Absturzprüfung ist nicht verlässlich"

{
  echo "## Emulator-Test, Android API $SDK"
  echo
  printf -- '- %s\n' "${RESULTS[@]}"
} | tee "$OUT/ergebnis.md" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

log "Fehler: $FAILED"
[ "$FAILED" -eq 0 ]
