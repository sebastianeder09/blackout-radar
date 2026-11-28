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
 * Danach lädt er den Lagebericht und gleicht ihn mit den angekommenen Meldungen ab (Notweg).
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
        val timeoutMs = if (quick) 5_000 else 15_000
        var reachable = false
        if (!ListenerService.running) {
            if (!ListenerService.start(app)) reachable = Sync.catchUp(app, timeoutMs) >= 0
        } else if (AppState.conn == AppState.Conn.CONNECTED) {
            val silence = SystemClock.elapsedRealtime() - AppState.lastActivityElapsed
            if (silence > ListenerService.STALE_AFTER_MS) ListenerService.kick(force = true) else reachable = true
        } else {
            ListenerService.kick(force = false)
        }
        // Fehlt noch, was vor dem Einrichten kam, und der Server antwortet gerade: jetzt nachholen.
        if (reachable && store.historyPending) Sync.backfill(app, timeoutMs)
        checkStatus(app, timeoutMs)
    }

    /**
     * Lädt den Lagebericht neu, aber nur, wenn der letzte Versuch mindestens [minGapMs] her ist. Daran
     * hängen der Notweg (siehe [Fallback]) und die Warnung, wenn der Radar selbst stillsteht. Die Anzeige
     * bekommt dabei den frischen Stand. Liefert die Zahl der Meldungen, die über den Notweg kamen, oder
     * null, wenn es nichts abzugleichen gab. Immer nur ein Durchgang zur selben Zeit.
     */
    @Synchronized
    fun checkStatus(context: Context, timeoutMs: Int, minGapMs: Long = MonitorWatch.CHECK_EVERY_MS): Int? {
        val app = context.applicationContext
        val store = Store.get(app)
        if (store.target == null) return null
        val now = System.currentTimeMillis()
        if (now - store.statusCheckedAt < minGapMs) return null
        store.statusCheckedAt = now
        val shown = Fallback.sync(app, timeoutMs) ?: return null
        val generatedAt = StatusRepo.generatedAt(store)
        if (!MonitorWatch.isStale(now, generatedAt)) {
            if (store.staleWarnedAt != 0L) {
                store.staleWarnedAt = 0L
                Alerts.cancelStale(app)
            }
        } else if (store.watchMonitor && MonitorWatch.shouldWarn(now, generatedAt, store.staleWarnedAt)) {
            store.staleWarnedAt = now
            Alerts.showStale(app, generatedAt, now)
        }
        return shown
    }

    /**
     * Derselbe Abgleich auf einem eigenen Faden. Der Dienst ruft das nach jedem vergeblichen Versuch, solange
     * die Verbindung zu ntfy ausbleibt: Gerade dann soll der Notweg nicht auf den nächsten Wecker warten.
     */
    fun checkStatusAside(context: Context) {
        val app = context.applicationContext
        if (System.currentTimeMillis() - Store.get(app).statusCheckedAt < MonitorWatch.CHECK_EVERY_MS) return
        val wakeLock = Awake.hold(app, "BlackoutRadar:Abgleich", 30_000L)
        Thread({
            try {
                checkStatus(app, 8_000)
            } catch (e: RuntimeException) {
                // Der Wächter kommt ohnehin wieder.
            } finally {
                Awake.release(wakeLock)
            }
        }, "abgleich").start()
    }
}

/** Hält das Handy für eine kurze Arbeit im Hintergrund wach. */
object Awake {
    fun hold(context: Context, tag: String, maxMs: Long): PowerManager.WakeLock? = try {
        context.getSystemService(PowerManager::class.java)
            ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, tag)
            ?.apply { acquire(maxMs) }
    } catch (e: RuntimeException) {
        null
    }

    fun release(wakeLock: PowerManager.WakeLock?) {
        try {
            if (wakeLock?.isHeld == true) wakeLock.release()
        } catch (e: RuntimeException) {
            // war schon abgelaufen
        }
    }
}

/** Der Wecker des Wächters. */
class WatchdogReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val app = context.applicationContext
        val pending = goAsync()
        // Nachfrage bei ntfy, Lagebericht und Abgleich brauchen auch mit den kurzen Wartezeiten des Weckers
        // im ungünstigen Fall gut 20 Sekunden.
        val wakeLock = Awake.hold(app, "BlackoutRadar:Waechter", 30_000L)
        Thread({
            try {
                Watchdog.run(app, quick = true)
            } catch (e: RuntimeException) {
                // Ein Fehler hier darf den nächsten Durchgang nicht verhindern.
            } finally {
                Awake.release(wakeLock)
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
