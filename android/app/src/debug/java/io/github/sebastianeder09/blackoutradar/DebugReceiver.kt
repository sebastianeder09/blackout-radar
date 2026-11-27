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
 */
class DebugReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext
        val pending = goAsync()
        Thread({
            try {
                intent.getStringExtra("status")?.let { Store.get(app).statusBaseOverride = it }
                intent.getStringExtra("ziel")?.let { Sync.setup(app, it, allowHttp = true) }
                if (intent.hasExtra("status")) StatusRepo.refresh(app, 8_000)
            } finally {
                pending.finish()
            }
        }, "testbau").start()
    }
}
