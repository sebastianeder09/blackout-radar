package io.github.sebastianeder09.blackoutradar

import android.content.BroadcastReceiver
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
                pending.resultData = "einrichten: " +
                    (setup?.let { "ok=${it.ok} meldungen=${it.count} ohne-netz=${it.offline}" } ?: "nein") +
                    ", lagebericht=" + (status ?: "nein")
            } finally {
                pending.finish()
            }
        }, "testbau").start()
    }
}
