package io.github.sebastianeder09.blackoutradar

import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent

/**
 * Nur im Testbau: richtet die App vom Rechner aus ein, damit die Prüfung im Emulator
 * ohne Tippen auskommt und gegen einen nachgestellten Server laufen kann.
 *
 *   adb shell am broadcast -n io.github.sebastianeder09.blackoutradar/.DebugReceiver \
 *       --es ziel http://10.0.2.2:8765/testthema --es status http://10.0.2.2:8765
 *
 * Die Antwort des Aufrufs (data="…") sagt, wie das Einrichten ausging, etwa
 * "einrichten: ok=true meldungen=5 ohne-netz=false, lagebericht=true". Daran sieht der Test, ob der
 * Server im Emulator schon erreichbar war.
 *
 * Mit "--ez abgleich true" lädt der Testbau sofort den Lagebericht und gleicht ihn mit den angekommenen
 * Meldungen ab, so wie es sonst der Wächter alle 15 Minuten tut. Die Antwort nennt dann, wie viele
 * Meldungen über den Notweg kamen: "…, abgleich=1", oder "abgleich=nein", wenn der Lagebericht nicht zu laden war.
 *
 * Mit "--ez ausgeruht true" vergisst der Testbau, wann er den Lagebericht zuletzt abgeglichen hat. Der
 * nächste Abgleich, den die App von selbst anstößt, wartet dann keinen Mindestabstand ab. So prüft der
 * Emulator-Test, dass die App bei einem Ausfall von ntfy ohne Anstoß von außen im Lagebericht nachsieht.
 *
 * Mit "--es zwischenablage http://10.0.2.2:8765/testthema" legt der Testbau die Nachricht in die Zwischenablage,
 * mit der ein Handy App und Thema weitergibt, so als hätte sie jemand im Messenger kopiert. Damit prüft der
 * Emulator-Test, dass die App das Thema daraus beim Öffnen selbst einträgt. Die Antwort nennt dann
 * "zwischenablage=true", oder "zwischenablage=false", wenn die Angabe kein Thema ist.
 *
 * Mit "--ez freigabe true" erlaubt der Testbau der Kommandozeile von adb, die Datei zu lesen, mit der die App sich
 * samt Thema weitergibt (AppFile). Dieselbe Erlaubnis bekommt sonst die App, die der Mensch zum Weitergeben wählt.
 * Damit holt der Emulator-Test die Datei so ab, wie es ein Messenger täte: von außen und nur mit dieser Erlaubnis.
 * Die Antwort nennt dann "freigabe=true", oder "freigabe=false", wenn es die Datei noch nicht gibt.
 *
 * Mit "--ez absturz true" stürzt der Testbau absichtlich ab. Damit prüft der Emulator-Test,
 * dass er einen Absturz der App auch bemerkt.
 */
class DebugReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.getBooleanExtra("absturz", false)) error("Absichtlicher Absturz für die Gegenprobe im Emulator-Test")
        val app = context.applicationContext
        val pending = goAsync()
        Thread({
            try {
                intent.getStringExtra("status")?.let { Store.get(app).statusBaseOverride = it }
                val setup = intent.getStringExtra("ziel")?.let { Sync.setup(app, it, allowHttp = true) }
                val status = if (intent.hasExtra("status")) StatusRepo.refresh(app, 8_000) else null
                if (intent.getBooleanExtra("ausgeruht", false)) Store.get(app).statusCheckedAt = 0L
                val copied = intent.getStringExtra("zwischenablage")?.let { ", zwischenablage=" + copyShared(app, it) } ?: ""
                val granted = if (intent.getBooleanExtra("freigabe", false)) ", freigabe=" + grantShare(app) else ""
                val check = if (intent.getBooleanExtra("abgleich", false)) {
                    ", abgleich=" + (Watchdog.checkStatus(app, 8_000, minGapMs = 0L) ?: "nein")
                } else ""
                pending.resultData = "einrichten: " +
                    (setup?.let { "ok=${it.ok} meldungen=${it.count} ohne-netz=${it.offline}" } ?: "nein") +
                    ", lagebericht=" + (status ?: "nein") + copied + granted + check
            } finally {
                pending.finish()
            }
        }, "testbau").start()
    }

    /** Erlaubt der Kommandozeile von adb, die Datei zum Weitergeben zu lesen. Andere Apps bleiben draußen. */
    private fun grantShare(context: Context): Boolean {
        if (!AppFile.shareFile(context).isFile) return false
        context.grantUriPermission("com.android.shell", AppFile.shareUri(context), Intent.FLAG_GRANT_READ_URI_PERMISSION)
        return true
    }

    /** Legt die Nachricht zum Weitergeben für dieses Ziel in die Zwischenablage. Schreiben darf eine App auch im Hintergrund. */
    private fun copyShared(context: Context, input: String): Boolean {
        val target = Ntfy.parseTarget(input, allowHttp = true) ?: return false
        val clipboard = context.getSystemService(ClipboardManager::class.java) ?: return false
        clipboard.setPrimaryClip(ClipData.newPlainText("Blackout-Radar", Ntfy.shareText(target, Updates.DOWNLOAD_URL)))
        return true
    }
}
