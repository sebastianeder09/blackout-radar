package io.github.sebastianeder09.blackoutradar

import android.app.AlarmManager
import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.PowerManager
import android.os.SystemClock

/** Sorgt dafür, dass alles läuft, was laufen soll. */
object Starter {
    /** Startet Dienst und Wächter, wenn ein Thema eingerichtet ist. Liefert true, wenn der Dienst läuft. */
    fun ensure(context: Context): Boolean {
        if (Store.get(context).target == null) return false
        Watchdog.arm(context)
        return ListenerService.running || ListenerService.start(context)
    }
}

/**
 * Das Sicherheitsnetz hinter der Dauerverbindung.
 *
 * Zwei Wege wecken den Wächter etwa alle 15 Minuten: ein Wecker, der auch im Tiefschlaf
 * des Geräts auslöst, und eine wiederkehrende Aufgabe, die Android nach einem Neustart
 * von selbst wieder einplant. Der Wächter startet den Dienst neu, falls Android ihn
 * beendet hat, erneuert eine tote Verbindung und fragt notfalls selbst beim Server nach.
 */
object Watchdog {
    private const val JOB_ID = 4711
    private const val INTERVAL_MS = 15 * 60_000L

    fun arm(context: Context) {
        val app = context.applicationContext
        try {
            val alarms = app.getSystemService(AlarmManager::class.java)
            alarms?.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + INTERVAL_MS, alarmIntent(app))
        } catch (e: RuntimeException) {
            // Der Wecker ist nur einer von zwei Wegen.
        }
        try {
            val scheduler = app.getSystemService(JobScheduler::class.java)
            if (scheduler != null && scheduler.getPendingJob(JOB_ID) == null) {
                scheduler.schedule(JobInfo.Builder(JOB_ID, ComponentName(app, WatchdogJob::class.java))
                    .setPeriodic(INTERVAL_MS)
                    .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                    .setPersisted(true)
                    .build())
            }
        } catch (e: RuntimeException) {
            // siehe oben
        }
    }

    fun disarm(context: Context) {
        val app = context.applicationContext
        try {
            app.getSystemService(AlarmManager::class.java)?.cancel(alarmIntent(app))
            app.getSystemService(JobScheduler::class.java)?.cancel(JOB_ID)
        } catch (e: RuntimeException) {
            // nichts eingeplant
        }
    }

    private fun alarmIntent(context: Context): PendingIntent =
        PendingIntent.getBroadcast(context, 0, Intent(context, WatchdogReceiver::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    /**
     * Ein Durchgang. [quick] gilt für den Wecker: Im Tiefschlaf gibt Android der App nur
     * wenige Sekunden Netz, deshalb sind die Wartezeiten dort kurz.
     */
    fun run(context: Context, quick: Boolean) {
        val app = context.applicationContext
        val store = Store.get(app)
        if (store.target == null) return
        arm(app)
        if (!ListenerService.running) {
            if (!ListenerService.start(app)) Sync.catchUp(app, if (quick) 5_000 else 15_000)
        } else if (AppState.conn == AppState.Conn.CONNECTED) {
            val silence = SystemClock.elapsedRealtime() - AppState.lastActivityElapsed
            if (silence > ListenerService.STALE_AFTER_MS) ListenerService.kick(force = true)
        } else {
            ListenerService.kick(force = false)
        }
        if (!quick) checkMonitor(app, store)
    }

    /** Prüft, ob der Radar selbst noch läuft, und hält dabei den Lagebericht für die Anzeige frisch. */
    private fun checkMonitor(context: Context, store: Store) {
        val now = System.currentTimeMillis()
        if (now - store.statusCheckedAt < MonitorWatch.CHECK_EVERY_MS) return
        store.statusCheckedAt = now
        if (!StatusRepo.refresh(context)) return
        val generatedAt = StatusRepo.generatedAt(store)
        if (!MonitorWatch.isStale(now, generatedAt)) {
            if (store.staleWarnedAt != 0L) {
                store.staleWarnedAt = 0L
                Alerts.cancelStale(context)
            }
        } else if (store.watchMonitor && MonitorWatch.shouldWarn(now, generatedAt, store.staleWarnedAt)) {
            store.staleWarnedAt = now
            Alerts.showStale(context, generatedAt, now)
        }
    }
}

/** Der Wecker des Wächters. */
class WatchdogReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext
        val pending = goAsync()
        val wakeLock = try {
            app.getSystemService(PowerManager::class.java)
                ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "BlackoutRadar:Waechter")
                ?.apply { acquire(20_000L) }
        } catch (e: RuntimeException) {
            null
        }
        Thread({
            try {
                Watchdog.run(app, quick = true)
            } catch (e: RuntimeException) {
                // Ein Fehler hier darf den nächsten Durchgang nicht verhindern.
            } finally {
                try {
                    if (wakeLock?.isHeld == true) wakeLock.release()
                } catch (e: RuntimeException) {
                    // war schon abgelaufen
                }
                pending.finish()
            }
        }, "waechter").start()
    }
}

/** Die wiederkehrende Aufgabe des Wächters. Sie hat Netz und mehr Zeit als der Wecker. */
class WatchdogJob : JobService() {
    override fun onStartJob(params: JobParameters): Boolean {
        Thread({
            try {
                Watchdog.run(applicationContext, quick = false)
            } catch (e: RuntimeException) {
                // siehe WatchdogReceiver
            } finally {
                jobFinished(params, false)
            }
        }, "waechter-aufgabe").start()
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean = false
}

/** Nach dem Einschalten des Handys und nach einem Update der App: alles wieder starten. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED -> Starter.ensure(context)
        }
    }
}
