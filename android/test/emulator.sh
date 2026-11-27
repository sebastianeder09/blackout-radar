#!/usr/bin/env bash
# Prüft die App in einem laufenden Emulator. Aufruf aus dem Hauptordner des Repositorys.
#
# Fertige App (release) gegen das echte ntfy.sh, auf einem Zufallsthema nur für diesen Lauf:
# Einrichten per Link, Zustellung eines Alarms, Funkloch, Ruhezustand (Doze),
# abgestürzter Dienst und Neustart des Handys. Testbau (debug) gegen einen nachgestellten
# Server (android/test/fake_ntfy.py auf Port 8765): Bildschirmfotos mit einem Blackout.
#
# Ergebnisse (Bilder, Ablauf, Protokolle) landen in $OUT.
set -uo pipefail

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
shot() { sleep "${2:-1}"; adb exec-out screencap -p > "$OUT/$1.png" && log "Bild $1"; }

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

ui_dump() {
  adb shell uiautomator dump /sdcard/ui.xml > /dev/null 2>&1
  adb pull /sdcard/ui.xml "$OUT/ui.xml" > /dev/null 2>&1
}

screen_has() {  # Text, der gerade auf dem Bildschirm steht (WebView-Inhalt eingeschlossen)
  for _ in 1 2 3 4 5; do
    ui_dump
    grep -qF "$1" "$OUT/ui.xml" 2> /dev/null && return 0
    sleep 2
  done
  return 1
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

# ------------------------------------------------------------ Testbau: Blackout
adb shell am start -W -n "$DBG/$PKG.MainActivity" > /dev/null
shot 00-einrichten 4
adb shell am broadcast -n "$DBG/$PKG.DebugReceiver" --es ziel http://10.0.2.2:8765/testthema --es status http://10.0.2.2:8765 > /dev/null
sleep 8
adb shell am start -n "$DBG/$PKG.MainActivity" --es tab lage > /dev/null
shot 10-blackout-lage 4
screen_has "Laufender Stromausfall" && ok "Testbau: Lagebericht mit laufendem Blackout angezeigt" || bad "Testbau: Lagebericht fehlt"
adb shell am start -n "$DBG/$PKG.MainActivity" --es tab meldungen > /dev/null
shot 11-blackout-meldungen 2
adb shell am start -n "$DBG/$PKG.MainActivity" --es tab app > /dev/null
shot 12-blackout-app 2
adb shell cmd uimode night yes > /dev/null
adb shell am start -n "$DBG/$PKG.MainActivity" --es tab lage > /dev/null
shot 13-blackout-lage-dunkel 4
adb shell cmd uimode night no > /dev/null
curl -sS -H "Title: Testbau live" -H "Priority: 4" -H "Tags: warning" -d "Zustellung im Testbau" http://127.0.0.1:8765/testthema > /dev/null
if t=$(wait_notification "Testbau live" 40); then ok "Testbau: neue Meldung nach $t s angezeigt"; else bad "Testbau: neue Meldung nicht angezeigt"; fi
adb shell am force-stop "$DBG"

# ------------------------------------------------- Fertige App gegen ntfy.sh
publish "CI Vorab" 3 zap "Diese Meldung lag schon vor dem Einrichten auf dem Thema."
sleep 3
adb shell am start -W -a android.intent.action.VIEW -d "blackoutradar://abo/$TOPIC" -p "$PKG" > /dev/null
sleep 6
shot 01-eingerichtet 2
screen_has "Meldung der letzten 12 Stunden" && ok "Einrichten per Link: Thema übernommen, vorhandene Meldung gefunden" \
  || bad "Einrichten per Link: Ergebnis nicht wie erwartet"
adb shell am start -n "$PKG/.MainActivity" --es tab lage > /dev/null
shot 02-lage 5

for _ in $(seq 1 30); do service_running "$PKG" && break; sleep 1; done
service_running "$PKG" && ok "Hintergrunddienst läuft" || bad "Hintergrunddienst läuft nicht"
sleep 5

publish "CI Alarm live" 5 rotating_light "Probe aus dem Emulator-Test: so kommt ein Alarm an."
if t=$(wait_notification "CI Alarm live" 60); then ok "Alarm über ntfy.sh nach $t s angekommen"; else bad "Alarm über ntfy.sh nicht angekommen"; fi
adb shell dumpsys notification --noredact > "$OUT/benachrichtigungen-alarm.txt"
grep -q "channel=alarm_laut" "$OUT/benachrichtigungen-alarm.txt" && ok "Alarm läuft über den lauten Alarm-Kanal" || bad "Alarm nicht im lauten Alarm-Kanal"
adb shell cmd statusbar expand-notifications > /dev/null 2>&1
shot 03-benachrichtigung 2
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
adb reboot
if wait_boot; then
  sleep 25
  service_running "$PKG" && ok "Dienst nach dem Neustart von selbst wieder gestartet" || bad "Dienst nach dem Neustart nicht gestartet"
  publish "CI Nach Neustart" 4 warning "Diese Meldung kam nach einem Neustart des Handys."
  if t=$(wait_notification "CI Nach Neustart" 180); then ok "Nach dem Neustart Meldung nach $t s"; else bad "Nach dem Neustart keine Meldung"; fi
else
  bad "Emulator kam nach dem Neustart nicht hoch"
fi

adb shell am start -W -n "$PKG/.MainActivity" --es tab meldungen > /dev/null
shot 04-meldungen 4
adb shell am start -n "$PKG/.MainActivity" --es tab app > /dev/null
shot 05-app 3
adb shell am start -n "$PKG/.MainActivity" --es tab lage > /dev/null
shot 06-lage 4

adb logcat -d > "$OUT/logcat.txt" 2>&1
adb shell dumpsys notification --noredact > "$OUT/benachrichtigungen.txt" 2>&1
adb shell dumpsys activity services "$PKG" > "$OUT/dienste.txt" 2>&1
rm -f "$OUT/ui.xml"

{
  echo "## Emulator-Test, Android API $SDK"
  echo
  printf -- '- %s\n' "${RESULTS[@]}"
} | tee "$OUT/ergebnis.md" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

log "Fehler: $FAILED"
[ "$FAILED" -eq 0 ]
