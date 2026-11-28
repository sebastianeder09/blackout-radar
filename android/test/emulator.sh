#!/usr/bin/env bash
# Prüft die App in einem laufenden Emulator. Aufruf aus dem Hauptordner des Repositorys.
#
# Fertige App (release) gegen das echte ntfy.sh, auf einem Zufallsthema nur für diesen Lauf:
# Einrichten per Link, Lagebericht des echten Radars, Zustellung eines Alarms, Funkloch,
# Ruhezustand (Doze), abgestürzter Dienst und Neustart des Handys. Testbau (debug) gegen einen
# nachgestellten Server (android/test/fake_ntfy.py auf Port 8765): Einrichten aus der kopierten
# Nachricht eines anderen Handys, Anzeige bei einem Blackout, der Notweg über den Lagebericht
# (Radar wird eine Meldung nicht los, falsches Thema, ntfy fällt aus) und Einrichten ohne Netz.
# Zum Schluss geben beide die App als Datei samt Thema weiter (thema_datei.py rechnet am Rechner
# nach, was in der Datei stehen muss), und beide werden aus dieser Datei frisch installiert:
# Beim ersten Öffnen müssen sie verbunden sein, ohne dass jemand etwas eingibt.
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

debug_app() {  # Angaben für den DebugReceiver des Testbaus -> Antwort der App (data="…"), siehe DebugReceiver
  adb shell am broadcast -n "$DBG/$PKG.DebugReceiver" "$@" 2> /dev/null | tr -d '\r' | sed -n 's/.*data="\(.*\)".*/\1/p'
}

setup_debug() {  # richtet den Testbau am nachgestellten Server ein -> Antwort der App
  debug_app --es ziel http://10.0.2.2:8765/testthema --es status http://10.0.2.2:8765
}

reconcile() {  # Der Testbau gleicht den Lagebericht jetzt ab -> Zahl der Meldungen, die über den Notweg kamen
  local answer
  answer=$(debug_app --ez abgleich true)
  if [[ "$answer" =~ abgleich=([0-9]+)$ ]]; then echo "${BASH_REMATCH[1]}"; else echo "keine Zahl (${answer:-keine Antwort})"; fi
}

radar() {  # Pfad JSON: spricht mit dem nachgestellten Radar und seinem ntfy (fake_ntfy.py) -> Antwort
  curl -sS -H "Content-Type: application/json" -d "$2" "http://127.0.0.1:8765/$1"
}

cards() {  # Titel [Text]: Zahl der Karten mit diesem Titel (und diesem Text) in der Liste der Meldungen des Testbaus
  page "$DBG" "[...document.querySelectorAll('.msg')].filter(c => c.querySelector('h4').textContent.includes('$1') && c.textContent.includes('${2:-}')).length"
}

notifications() {  # Titel: Zahl der Benachrichtigungen mit diesem Titel
  adb shell dumpsys notification --noredact 2> /dev/null | grep -c "android.title=.*$1"
}

channel_of() {  # Titel -> Kanal, über den die Benachrichtigung mit diesem Titel läuft
  adb shell dumpsys notification --noredact 2> /dev/null | python3 -c '
import re, sys
for block in sys.stdin.read().split("NotificationRecord(")[1:]:
    if sys.argv[1] in block:
        found = re.search(r"channel=([A-Za-z0-9_]+)", block)
        print(found.group(1) if found else "unbekannt")
        break
' "$1"
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
# 1. Die Liste der Prozessenden mit ihrem Grund. Sie reicht nur bis zum letzten Neustart sicher zurück und
#    beginnt mit einer neuen Installation von vorn, deshalb fragt der Test sie davor und am Schluss ab.
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

chooser() { adb shell dumpsys activity activities 2> /dev/null | grep -q "ChooserActivity"; }  # zeigt Android gerade seine Auswahl zum Weitergeben?

size() { wc -c < "$1" | tr -d ' '; }  # Datei -> Größe in Bytes

grant_and_exempt() {  # Paket: Benachrichtigungen erlauben und von der Akku-Optimierung ausnehmen, damit Android nicht nachfragt
  [ "$SDK" -ge 33 ] && adb shell pm grant "$1" android.permission.POST_NOTIFICATIONS
  adb shell dumpsys deviceidle whitelist +"$1" > /dev/null
}

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
for p in $PKG $DBG; do grant_and_exempt "$p"; done

log "Bildschirm: $(adb shell wm size | tr -d '\r' | tr '\n' ' ')$(adb shell wm density | tr -d '\r' | tr '\n' ' ')"

# ------------------------------------------------------------ Testbau: Blackout
adb shell am start -W -n "$DBG/$PKG.MainActivity" > /dev/null
page_has "$DBG" "Alarme auf dieses Handy holen" && ok "Testbau: Einrichten wird angezeigt" || bad "Testbau: Einrichten fehlt"
shot 00-einrichten
# Ein weiteres Handy einrichten: Die weitergegebene Nachricht liegt in der Zwischenablage, so als hätte sie jemand
# im Messenger kopiert. Wechselt der Mensch danach in die App, steht das Thema schon im Feld. Verbinden tippt er
# selbst. Der Lagebericht kommt dabei schon vom nachgestellten Server, nicht von GitHub.
debug_app --es status http://10.0.2.2:8765 > /dev/null
adb shell input keyevent KEYCODE_HOME
sleep 2
log "Zwischenablage: $(debug_app --es zwischenablage http://10.0.2.2:8765/testthema)"
adb shell am start -W -n "$DBG/$PKG.MainActivity" > /dev/null
field=""
wait_page "$DBG" "Aus der kopierten Nachricht übernommen" 20 > /dev/null && field=$(page "$DBG" "document.getElementById('topic').value")
[ "$field" = "http://10.0.2.2:8765/testthema" ] && ok "Testbau: Thema aus der kopierten Nachricht steht von selbst im Feld" \
  || bad "Testbau: Thema aus der kopierten Nachricht nicht übernommen (im Feld: \"$field\")"
shot 00b-einrichten-kopiert 7  # erst wenn der Hinweis von Android zum Kopieren wieder weg ist
page "$DBG" "document.getElementById('connect').click()" > /dev/null
connected=nein
for _ in $(seq 1 20); do
  [ "$(page "$DBG" "!!document.querySelector('.result')")" = true ] && connected=ja && break
  sleep 2
done
[ "$connected" = ja ] && ok "Testbau: danach genügt ein Tipp auf Verbinden" || bad "Testbau: Verbinden mit dem übernommenen Thema hat nicht geklappt"
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

# ------------------------------------------------------------ Testbau: Notweg
# Der Radar führt im Lagebericht, was er verschickt hat. Kommt davon etwas nicht über ntfy an, zeigt die App es
# selbst an und läutet. Hinter dem nachgestellten Server läuft dafür der echte Versand des Radars mit seinem
# Postausgang (fake_ntfy.py), der Lagebericht stammt also aus demselben Code wie im Betrieb.
n=$(reconcile)
[ "$n" = 0 ] && ok "Notweg: was vor dem Einrichten im Lagebericht stand, läutet nicht" || bad "Notweg: Abgleich ohne neue Meldung ergab $n statt 0"

# 1. Der Radar wird eine Meldung bei ntfy nicht los. Die App holt sie aus dem Lagebericht, so laut wie über ntfy.
radar schalter '{"radar_erreicht_ntfy": false}' > /dev/null
log "Radar: $(radar radar/meldung '{"title": "Notweg Alarm", "body": "Probe aus dem Emulator-Test: Diese Meldung wurde der Radar bei ntfy nicht los.", "level": "alarm"}')"
n=$(reconcile)
[ "$n" = 1 ] && ok "Notweg: Meldung, die der Radar nicht loswurde, aus dem Lagebericht geholt" || bad "Notweg: Abgleich ergab $n statt 1"
if wait_notification "Notweg Alarm" 20 > /dev/null; then ok "Notweg: Alarm als Benachrichtigung"; else bad "Notweg: Alarm nicht als Benachrichtigung"; fi
channel=$(channel_of "Notweg Alarm")
[ "$channel" = alarm_laut ] && ok "Notweg: Alarm läuft über den lauten Alarm-Kanal" || bad "Notweg: Alarm läuft über den Kanal \"$channel\" statt über den lauten Alarm-Kanal"
page_has "$DBG" "Der Radar konnte diese Meldung nicht an ntfy übergeben" && ok "Notweg: Liste zeigt die Meldung mit dem Grund" || bad "Notweg: Meldung oder Grund fehlt in der Liste"
shot 16-notweg-meldung 7  # erst wenn der Hinweis von Android am oberen Rand wieder weg ist
n=$(reconcile)
[ "$n" = 0 ] && ok "Notweg: dieselbe Meldung läutet beim nächsten Abgleich nicht noch einmal" || bad "Notweg: zweiter Abgleich ergab $n statt 0"

# 2. Im nächsten Lauf wird der Radar die Meldung doch noch los, mit seinem Vermerk "Verspätet zugestellt".
#    Sie tritt still an die Stelle des Eintrags: Geläutet hat es dafür schon.
radar schalter '{"radar_erreicht_ntfy": true}' > /dev/null
log "Radar: $(radar radar/lauf '{"minuten_spaeter": 25}')"
if t=$(wait_page "$DBG" "Verspätet zugestellt, erstellt am" 40); then ok "Notweg: spätere Zustellung über ntfy nach $t s in der Liste"; else bad "Notweg: spätere Zustellung über ntfy kam nicht an"; fi
[ "$(cards "Notweg Alarm")" = 1 ] && [ "$(cards "Notweg Alarm" "Über den Notweg")" = 0 ] \
  && ok "Notweg: spätere Zustellung ersetzt den Eintrag, nichts steht doppelt" \
  || bad "Notweg: nach der späteren Zustellung $(cards "Notweg Alarm") Karten, davon $(cards "Notweg Alarm" "Über den Notweg") vom Notweg"
count=$(notifications "Notweg Alarm")
[ "$count" = 1 ] && ok "Notweg: spätere Zustellung läutet nicht noch einmal" || bad "Notweg: $count Benachrichtigungen statt 1 nach der späteren Zustellung"
n=$(reconcile)
[ "$n" = 0 ] && ok "Notweg: nach der Zustellung fehlt nichts mehr" || bad "Notweg: Abgleich nach der Zustellung ergab $n statt 0"

# 3. Das Thema stimmt nicht: Der Radar stellt zu, aber nicht unter dem Thema dieses Handys.
radar schalter '{"thema_des_radars": "anderes-thema"}' > /dev/null
log "Radar: $(radar radar/meldung '{"title": "Notweg Thema", "body": "Probe aus dem Emulator-Test: Diese Meldung ging an ein anderes Thema.", "level": "warn"}')"
radar schalter '{"thema_des_radars": "testthema"}' > /dev/null
n=$(reconcile)
[ "$n" = 1 ] && page_has "$DBG" "unter dem Thema dieses Handys lag die Meldung dort aber nicht" \
  && ok "Notweg: Meldung unter fremdem Thema geholt, Liste weist auf das Thema hin" || bad "Notweg: Meldung unter fremdem Thema nicht geholt (Abgleich $n)"

# 4. Gegenprobe: Eine Meldung, die wie gewohnt über ntfy ankommt, löst keinen Notweg aus.
log "Radar: $(radar radar/meldung '{"title": "Ohne Notweg", "body": "Probe aus dem Emulator-Test: Diese Meldung kam wie gewohnt.", "level": "info"}')"
if wait_notification "Ohne Notweg" 30 > /dev/null; then ok "Notweg: gewöhnliche Meldung kommt über ntfy"; else bad "Notweg: gewöhnliche Meldung kam nicht über ntfy"; fi
n=$(reconcile)
[ "$n" = 0 ] && [ "$(cards "Ohne Notweg")" = 1 ] && [ "$(cards "Ohne Notweg" "Über den Notweg")" = 0 ] \
  && ok "Notweg: angekommene Meldung bleibt, wie sie ist" || bad "Notweg: angekommene Meldung wurde noch einmal geholt (Abgleich $n)"

# 5. ntfy fällt aus, der Lagebericht bleibt erreichbar. Niemand stößt den Abgleich an: Die App muss von selbst
#    im Lagebericht nachsehen. Der letzte Abgleich gilt dafür als lange her, sonst wartete sie den Mindestabstand ab.
radar schalter '{"handy_erreicht_ntfy": false}' > /dev/null
log "Radar: $(radar radar/meldung '{"title": "Notweg von selbst", "body": "Probe aus dem Emulator-Test: ntfy war für das Handy nicht erreichbar.", "level": "alarm"}')"
debug_app --ez ausgeruht true > /dev/null
if t=$(wait_notification "Notweg von selbst" 240); then ok "Notweg: ntfy ausgefallen, App alarmiert nach $t s von selbst"; else bad "Notweg: ntfy ausgefallen, App hat nicht von selbst alarmiert"; fi
page_has "$DBG" "ntfy war von diesem Handy aus nicht erreichbar" && ok "Notweg: Liste nennt den Ausfall von ntfy als Grund" || bad "Notweg: Grund für den Ausfall von ntfy fehlt"
quiet_system
adb shell cmd statusbar expand-notifications > /dev/null 2>&1
sleep 2
snap 17-notweg-benachrichtigung
adb shell cmd statusbar collapse > /dev/null 2>&1
# ntfy ist wieder da. Die App zu öffnen drängt sie zum nächsten Versuch. Die Meldung von ntfy ersetzt den Eintrag still.
radar schalter '{"handy_erreicht_ntfy": true}' > /dev/null
adb shell am start -n "$DBG/$PKG.MainActivity" --es tab meldungen > /dev/null
replaced=nein
for _ in $(seq 1 30); do
  [ "$(cards "Notweg von selbst" "Über den Notweg")" = 0 ] && replaced=ja && break
  sleep 2
done
[ "$replaced" = ja ] && [ "$(cards "Notweg von selbst")" = 1 ] && [ "$(notifications "Notweg von selbst")" = 1 ] \
  && ok "Notweg: ntfy wieder da, Meldung kommt nach und läutet nicht noch einmal" \
  || bad "Notweg: nach der Rückkehr von ntfy $(cards "Notweg von selbst") Karten und $(notifications "Notweg von selbst") Benachrichtigungen statt je 1"
adb shell am start -n "$DBG/$PKG.MainActivity" --es tab app > /dev/null
page_has "$DBG" "Meldungen kommen sofort an" && ok "Testbau: Verbindung wird als bestehend angezeigt" || bad "Testbau: Anzeige der Verbindung stimmt nicht"
page_has "$DBG" "bereit · Abgleich" && ok "Testbau: Notweg wird als bereit angezeigt" || bad "Testbau: Anzeige des Notwegs stimmt nicht"
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
# Weitergeben an ein weiteres Handy: Karte mit den beiden Knöpfen. Android zeigt seine Auswahl, erst mit der fertigen
# Nachricht, dann mit der App als Datei samt Thema. Was in dieser Datei steht, prüft der Schluss des Tests.
page_has "$PKG" "App samt Thema weitergeben" && page_has "$PKG" "Nur Nachricht mit Link weitergeben" \
  && ok "Knöpfe zum Weitergeben an weitere Handys vorhanden" || bad "Knöpfe zum Weitergeben fehlen"
page "$PKG" "[...document.querySelectorAll('h3')].find(h => h.textContent === 'Weitere Handys').scrollIntoView({ block: 'center' })" > /dev/null
shot 05b-weitere-handys
page "$PKG" "Native.share()" > /dev/null
sleep 3
chooser && ok "Weitergeben der Nachricht öffnet die Auswahl von Android" || bad "Weitergeben der Nachricht öffnet die Auswahl von Android nicht"
snap 06-weitergeben
adb shell input keyevent KEYCODE_BACK
sleep 2
page "$PKG" "Native.shareApp()" > /dev/null
sleep 3
chooser && ok "Weitergeben als Datei öffnet die Auswahl von Android" || bad "Weitergeben als Datei öffnet die Auswahl von Android nicht"
snap 06b-datei-weitergeben
adb shell input keyevent KEYCODE_BACK
adb shell am start -n "$PKG/.MainActivity" --es tab lage > /dev/null
shot 07-lage 3
# Das App-Symbol, so wie Android es zeichnet: In den App-Infos der Einstellungen steht es oben in der Mitte.
# Der Ausschnitt ist so schmal, dass er unverkleinert ins Protokoll kommt: Bildpunkt für Bildpunkt wie am Handy.
adb shell am start -W -a android.settings.APPLICATION_DETAILS_SETTINGS -d "package:$PKG" > /dev/null 2>&1
shot 08-app-infos 3
java -Djava.awt.headless=true "$HERE/Vorschau.java" ausschnitt "$OUT/08-app-infos.png" "$OUT/08b-app-symbol.png" 35 23 30 12 2> /dev/null \
  && log "Bild 08b-app-symbol" || log "Ausschnitt mit dem App-Symbol nicht möglich"
adb shell input keyevent KEYCODE_HOME

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

# ------------------------------------------------- App samt Thema als Datei weitergeben
# Ein eingerichtetes Handy gibt die App als Datei weiter, die sein Thema enthält (ApkTopic.kt). thema_datei.py legt
# das Thema am Rechner mit eigenem Code in die gebaute Datei: Was das Handy schreibt, muss dem Byte für Byte gleichen.
WORK=$(mktemp -d)
SHARE=blackout-radar-mit-thema.apk
python3 "$HERE/thema_datei.py" schreiben "$APK_DIR/blackout-radar-test.apk" "$WORK/testbau-erwartet.apk" http://10.0.2.2:8765/testthema \
  && python3 "$HERE/thema_datei.py" schreiben "$APK_DIR/blackout-radar-test.apk" "$WORK/testbau-anderes.apk" http://10.0.2.2:8765/anderes-thema \
  && python3 "$HERE/thema_datei.py" schreiben "$APK_DIR/blackout-radar.apk" "$WORK/fertig-erwartet.apk" "$TOPIC" \
  || bad "Datei mit Thema ließ sich am Rechner nicht schreiben"

same_file() {  # Name Vom-Handy Erwartet: gleicht die Datei vom Handy der erwarteten?
  if cmp -s "$2" "$3"; then
    ok "$1: Datei vom Handy ist die installierte App samt Thema, Byte für Byte ($(size "$2") Bytes)"
  else
    bad "$1: Datei vom Handy weicht ab ($(size "$2") statt $(size "$3") Bytes, Thema darin: $(python3 "$HERE/thema_datei.py" lesen "$2" 2>&1 | head -c 200)," \
      "Anfang: $(head -c 200 "$2" | tr -c '[:print:]' '.'))"
  fi
}

locked() {  # Paket: ohne Erlaubnis kommt niemand von außen an die Datei, auch nicht die Kommandozeile von adb
  adb shell content read --uri "content://$1.datei/$SHARE" > "$WORK/ohne-erlaubnis.txt" 2>&1
  [ "$(adb shell id -u | tr -d '\r')" = 2000 ] && grep -q "Permission Denial" "$WORK/ohne-erlaubnis.txt" && ! cmp -s -n 2 "$WORK/ohne-erlaubnis.txt" "$APK_DIR/blackout-radar.apk"
}

# Testbau: Knopf drücken, Android zeigt seine Auswahl. Die Datei liegt jetzt bereit.
adb shell am start -W -n "$DBG/$PKG.MainActivity" --es tab app > /dev/null
page_has "$DBG" "App samt Thema weitergeben" || bad "Testbau: Knopf zum Weitergeben als Datei fehlt"
page "$DBG" "Native.shareApp()" > /dev/null
sleep 3
chooser && ok "Testbau: Weitergeben als Datei öffnet die Auswahl von Android" || bad "Testbau: Weitergeben als Datei öffnet die Auswahl von Android nicht"
adb shell input keyevent KEYCODE_BACK
# Abgeholt wird sie so, wie es ein Messenger täte: von außen, über die Adresse aus der Auswahl. Das geht erst mit der
# Erlaubnis, die Android sonst der gewählten App gibt. Der Testbau erteilt sie hier der Kommandozeile von adb.
locked "$DBG" && ok "Testbau: ohne Erlaubnis kommt von außen niemand an die Datei" \
  || bad "Testbau: Datei ohne Erlaubnis nicht gesperrt: $(head -c 200 "$WORK/ohne-erlaubnis.txt" | tr -c '[:print:]' '.')"
log "Testbau: $(debug_app --ez freigabe true)"
adb exec-out "content read --uri content://$DBG.datei/$SHARE 2> /dev/null" > "$WORK/testbau-vom-handy.apk"  # Meldungen des Werkzeugs bleiben am Handy
same_file "Testbau" "$WORK/testbau-vom-handy.apk" "$WORK/testbau-erwartet.apk"
about=$(adb shell content query --uri "content://$DBG.datei/$SHARE" 2>&1 | tr -d '\r')
[[ "$about" == *"_display_name=$SHARE"* && "$about" == *"_size=$(size "$WORK/testbau-erwartet.apk")"* ]] \
  && ok "Testbau: die Datei nennt der empfangenden App Namen und Größe" || bad "Testbau: Angaben zur Datei stimmen nicht: $(head -c 300 <<< "$about")"

# Fertige App: Sie hat ihre Datei weiter oben geschrieben. Einen Testzugang hat sie nicht, deshalb liest der Test die
# Datei mit den Rechten, die nur der Emulator hergibt (root), über dieselbe Adresse aus.
locked "$PKG" && ok "Fertige App: ohne Erlaubnis kommt von außen niemand an die Datei" \
  || bad "Fertige App: Datei ohne Erlaubnis nicht gesperrt: $(head -c 200 "$WORK/ohne-erlaubnis.txt" | tr -c '[:print:]' '.')"
if adb root > /dev/null 2>&1 && wait_boot; then
  sleep 3
  adb exec-out "content read --uri content://$PKG.datei/$SHARE 2> /dev/null" > "$WORK/fertig-vom-handy.apk"
  adb unroot > /dev/null 2>&1
  wait_boot
  same_file "Fertige App" "$WORK/fertig-vom-handy.apk" "$WORK/fertig-erwartet.apk"
else
  log "adb root nicht möglich, Vergleich der Datei der fertigen App übersprungen"
fi

# Über eine vorhandene Installation gespielt, bleibt, was eingerichtet ist. Bringt die Datei ein anderes Thema mit,
# fragt die App einmal nach und ersetzt nichts von selbst.
answer=$(adb install -r "$WORK/testbau-anderes.apk" 2>&1) && ok "Datei mit Thema: Android spielt sie über die vorhandene App, die Signatur gilt" \
  || bad "Datei mit Thema: ließ sich nicht über die vorhandene App spielen: $(tail -c 300 <<< "$answer" | tr '\n' ' ')"
adb shell am start -W -n "$DBG/$PKG.MainActivity" --es tab app > /dev/null
page_has "$DBG" "Die Installationsdatei bringt ein anderes Thema mit" && ok "Datei mit anderem Thema: App fragt nach, statt das Thema zu ersetzen" \
  || bad "Datei mit anderem Thema: Rückfrage fehlt"
shot 18-datei-anderes-thema
page "$DBG" "document.querySelector('#modal .btn').click()" > /dev/null  # "Abbrechen"
adb shell am force-stop "$DBG"
adb shell am start -W -n "$DBG/$PKG.MainActivity" --es tab app > /dev/null
page_has "$DBG" "Weitere Handys" > /dev/null
sleep 2
# Das bisherige Thema steht verdeckt in der Karte der Verbindung (neun Punkte für "testthema"), das andere begänne mit "ande".
kept=$(page "$DBG" "!document.querySelector('#modal.show') && document.body.innerText.includes('•••••••••') && !document.body.innerText.includes('ande…ema')")
[ "$kept" = true ] && ok "Datei mit anderem Thema: nach „Abbrechen“ bleibt das Thema, und die App fragt kein zweites Mal" \
  || bad "Datei mit anderem Thema: Thema nicht behalten oder erneute Rückfrage ($kept)"

# Das andere Handy: Beide Apps kommen frisch aus der Datei mit Thema. Beim ersten Öffnen müssen sie verbunden sein,
# ohne dass jemand etwas eingibt. Mit der neuen Installation beginnt die Liste der Prozessenden von vorn.
note_exits enden-vor-datei.txt
adb uninstall "$DBG" > /dev/null
adb uninstall "$PKG" > /dev/null
answer=$(adb install "$WORK/testbau-erwartet.apk" 2>&1 && adb install "$WORK/fertig-erwartet.apk" 2>&1) \
  && ok "Datei mit Thema: Android installiert sie auf frischem Stand, die Signatur gilt" \
  || bad "Datei mit Thema: ließ sich nicht frisch installieren: $(tail -c 300 <<< "$answer" | tr '\n' ' ')"
for p in $PKG $DBG; do grant_and_exempt "$p"; done

adb shell am start -W -n "$DBG/$PKG.MainActivity" > /dev/null
if t=$(wait_page "$DBG" "Das Thema stand schon in der Installationsdatei" 40); then
  ok "Testbau aus der Datei: beim ersten Öffnen nach $t s eingerichtet, ohne Eingabe"
else
  bad "Testbau aus der Datei: hat sich nicht von selbst eingerichtet"
fi
shot 19-datei-testbau-eingerichtet
log "Testbau aus der Datei: $(debug_app --es status http://10.0.2.2:8765)"  # Lagebericht wieder vom nachgestellten Server
curl -sS -H "Title: Aus der Datei" -H "Priority: 4" -H "Tags: warning" -d "Zustellung an das Handy, das die App als Datei bekam" http://127.0.0.1:8765/testthema > /dev/null
if t=$(wait_notification "Aus der Datei" 40); then ok "Testbau aus der Datei: neue Meldung nach $t s als Benachrichtigung"; else bad "Testbau aus der Datei: neue Meldung kam nicht an"; fi

adb shell am start -W -n "$PKG/.MainActivity" > /dev/null
if t=$(wait_page "$PKG" "Das Thema stand schon in der Installationsdatei" 40); then
  ok "Fertige App aus der Datei: beim ersten Öffnen nach $t s eingerichtet, ohne Eingabe"
else
  bad "Fertige App aus der Datei: hat sich nicht von selbst eingerichtet"
fi
page_has "$PKG" "der letzten 12 Stunden gefunden" && ok "Fertige App aus der Datei: Meldungen dieses Laufs bei ntfy.sh gefunden" \
  || bad "Fertige App aus der Datei: Meldungen dieses Laufs nicht gefunden"
shot 20-datei-fertige-app-eingerichtet
page "$PKG" "document.querySelector('.result .btn.primary').click()" > /dev/null  # Knopf "Weiter"
for _ in $(seq 1 30); do service_running "$PKG" && break; sleep 1; done
sleep 5
publish "CI Aus der Datei" 4 warning "Diese Meldung kam an dem Handy an, das die App als Datei samt Thema bekam."
if t=$(wait_notification "CI Aus der Datei" 60); then ok "Fertige App aus der Datei: Meldung über ntfy.sh nach $t s angekommen"; else bad "Fertige App aus der Datei: Meldung über ntfy.sh nicht angekommen"; fi
rm -rf "$WORK"

adb logcat -d > "$OUT/logcat.txt" 2>&1
adb shell dumpsys notification --noredact > "$OUT/benachrichtigungen.txt" 2>&1
adb shell dumpsys activity services "$PKG" > "$OUT/dienste.txt" 2>&1
rm -f "$OUT/seite-fehler.txt" "$OUT/vergleich-fehler.txt"

# Ist die fertige App oder der Testbau im Lauf abgestürzt oder hängen geblieben?
note_exits enden-am-schluss.txt
log "Prozessenden im Lauf: $(sort -u "$OUT/enden-vor-neustart.txt" "$OUT/enden-vor-datei.txt" "$OUT/enden-am-schluss.txt" | tr '\n' ';')"
died=$(sort -u "$OUT/enden-vor-neustart.txt" "$OUT/enden-vor-datei.txt" "$OUT/enden-am-schluss.txt" | grep -E "$BAD_EXIT")
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
