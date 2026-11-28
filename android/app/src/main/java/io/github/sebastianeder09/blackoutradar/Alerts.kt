package io.github.sebastianeder09.blackoutradar

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.net.Uri
import android.provider.Settings

/** Benachrichtigungen: die Kanäle, die Android in den Einstellungen zeigt, und die Meldungen selbst. */
object Alerts {
    const val CH_ALARM_LOUD = "alarm_laut"
    const val CH_ALARM = "alarm"
    const val CH_WARN = "warnung"
    const val CH_INFO = "meldung"
    const val CH_QUIET = "leise"
    const val CH_SERVICE = "dienst"
    const val CH_APP = "hinweis"

    const val ID_SERVICE = 1
    const val ID_STALE = 2
    const val ID_TEST = 3

    /** Ältere Meldungen läuten nicht mehr als Alarm, sie kommen als gewöhnliche Meldung. */
    const val LATE_AFTER_MS = 3 * 60 * 60_000L

    private const val COLOR_ALARM = 0xFFD1242F.toInt()
    private const val COLOR_WARN = 0xFFBF8700.toInt()
    private const val COLOR_OK = 0xFF1A7F37.toInt()
    private const val COLOR_INFO = 0xFF0969DA.toInt()

    /** Wählt den Kanal nach Dringlichkeit, Einstellung und Alter der Meldung. */
    fun channelFor(priority: Int, loud: Boolean, ageMs: Long): String = when {
        priority >= 5 && ageMs > LATE_AFTER_MS -> CH_INFO
        priority >= 5 -> if (loud) CH_ALARM_LOUD else CH_ALARM
        priority == 4 -> if (ageMs > LATE_AFTER_MS) CH_INFO else CH_WARN
        priority == 3 -> CH_INFO
        else -> CH_QUIET
    }

    fun createChannels(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        val pattern = longArrayOf(0, 600, 250, 600, 250, 900)

        val loud = NotificationChannel(CH_ALARM_LOUD, "Alarm (laut)", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Großer Stromausfall in Österreich oder schwere Störung der Netzfrequenz. " +
                "Läutet über die Wecker-Lautstärke, auch bei Lautlos und Nicht stören."
            setSound(alarmSound(context), AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build())
            enableVibration(true)
            vibrationPattern = pattern
            enableLights(true)
            lightColor = COLOR_ALARM
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            setBypassDnd(true)
        }
        val alarm = NotificationChannel(CH_ALARM, "Alarm", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Wie der laute Alarm, aber mit dem gewöhnlichen Benachrichtigungston."
            enableVibration(true)
            vibrationPattern = pattern
            enableLights(true)
            lightColor = COLOR_ALARM
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        val warn = NotificationChannel(CH_WARN, "Warnung", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Hinweise auf einen Ausfall in Oberösterreich, Ausfälle in Nachbarländern, auffällige Netzfrequenz."
            enableVibration(true)
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        val info = NotificationChannel(CH_INFO, "Meldung", NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "Große Ausfälle im Rest der Welt, Zwischenstände und Entwarnungen."
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
        }
        val quiet = NotificationChannel(CH_QUIET, "Tägliche Übersicht", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Die leise Übersicht am Morgen. Sie ist zugleich das Lebenszeichen des Radars."
        }
        val service = NotificationChannel(CH_SERVICE, "Verbindung (Dauermeldung)", NotificationManager.IMPORTANCE_LOW).apply {
            description = "Zeigt, dass die App auf Meldungen wartet. Android verlangt diese Anzeige."
            setShowBadge(false)
        }
        val app = NotificationChannel(CH_APP, "Hinweise der App", NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "Zum Beispiel, wenn der Radar selbst keinen neuen Lagebericht mehr liefert."
        }
        manager.createNotificationChannels(listOf(loud, alarm, warn, info, quiet, service, app))
    }

    private fun alarmSound(context: Context): Uri {
        val actual = try {
            RingtoneManager.getActualDefaultRingtoneUri(context, RingtoneManager.TYPE_ALARM)
        } catch (e: RuntimeException) {
            null
        }
        return if (actual != null) Settings.System.DEFAULT_ALARM_ALERT_URI else Settings.System.DEFAULT_NOTIFICATION_URI
    }

    /** Zeigt eine Meldung des Radars an. */
    fun show(context: Context, notice: Notice, nowMs: Long = System.currentTimeMillis()) {
        val store = Store.get(context)
        val ageMs = nowMs - notice.time * 1000L
        val channel = channelFor(notice.priority, store.loudAlarm, ageMs)
        val late = ageMs > 20 * 60_000L
        var body = if (late) "Verspätet angekommen (${MonitorWatch.age(ageMs)}).\n${notice.message}" else notice.message
        // Kam die Meldung über den Notweg, steht der Grund am Schluss. Vorn bleibt, was passiert ist.
        if (notice.fallback) body += "\n\n" + Fallback.reason(notice.via, notice.public)
        val builder = Notification.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_stat_bolt)
            .setContentTitle(Ntfy.displayTitle(notice))
            .setContentText(body.lineSequence().firstOrNull { it.isNotBlank() } ?: "")
            .setStyle(Notification.BigTextStyle().bigText(body))
            .setWhen(notice.time * 1000L)
            .setShowWhen(true)
            .setAutoCancel(true)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setColor(when (notice.level) {
                "alarm" -> COLOR_ALARM
                "warn" -> COLOR_WARN
                "ok" -> COLOR_OK
                else -> COLOR_INFO
            })
            .setContentIntent(openApp(context, "lage", notice.id.hashCode()))
        val alarming = channel == CH_ALARM_LOUD || channel == CH_ALARM
        if (alarming) builder.setCategory(Notification.CATEGORY_ALARM)
        val notification = builder.build()
        if (alarming && store.repeatAlarm) notification.flags = notification.flags or Notification.FLAG_INSISTENT
        notify(context, 1000 + (notice.id.hashCode() and 0x0FFFFFFF), notification)
    }

    /** Ein Probealarm, der nur auf diesem Gerät entsteht. So klingt ein echter Alarm. */
    fun showTest(context: Context) {
        val store = Store.get(context)
        val channel = if (store.loudAlarm) CH_ALARM_LOUD else CH_ALARM
        val text = "So meldet sich die App bei einem großen Stromausfall in Österreich. " +
            "Dieser Probealarm kommt vom Handy selbst und prüft Ton und Anzeige, nicht den Weg über das Netz."
        val notification = Notification.Builder(context, channel)
            .setSmallIcon(R.drawable.ic_stat_bolt)
            .setContentTitle("🚨 Probealarm vom Blackout-Radar")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_ALARM)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setColor(COLOR_ALARM)
            .setContentIntent(openApp(context, "app", ID_TEST))
            .build()
        if (store.repeatAlarm) notification.flags = notification.flags or Notification.FLAG_INSISTENT
        notify(context, ID_TEST, notification)
    }

    /** Hinweis, dass der Radar selbst stillsteht. Wer den öffentlichen Alarm nutzt, betreibt den Radar nicht selbst. */
    fun showStale(context: Context, generatedAtMs: Long, nowMs: Long) {
        val text = "Der letzte Lagebericht ist ${MonitorWatch.age(nowMs - generatedAtMs)} alt. " +
            if (PublicAlarm.active(Store.get(context))) "Der Radar läuft vermutlich gerade nicht. Solange kommen auch keine Alarme."
            else "Die Überwachung bei GitHub läuft vermutlich nicht, es kämen also auch keine Alarme."
        val notification = Notification.Builder(context, CH_APP)
            .setSmallIcon(R.drawable.ic_stat_bolt)
            .setContentTitle("Der Blackout-Radar steht still")
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setAutoCancel(true)
            .setColor(COLOR_WARN)
            .setContentIntent(openApp(context, "lage", ID_STALE))
            .build()
        notify(context, ID_STALE, notification)
    }

    fun cancelStale(context: Context) {
        context.getSystemService(NotificationManager::class.java)?.cancel(ID_STALE)
    }

    /** Die Dauermeldung, die Android für eine Verbindung im Hintergrund verlangt. */
    fun service(context: Context, text: String): Notification =
        Notification.Builder(context, CH_SERVICE)
            .setSmallIcon(R.drawable.ic_stat_bolt)
            .setContentTitle("Blackout-Radar wacht")
            .setContentText(text)
            .setOngoing(true)
            .setShowWhen(false)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setContentIntent(openApp(context, "", ID_SERVICE))
            .build()

    fun updateService(context: Context, text: String) {
        notify(context, ID_SERVICE, service(context, text))
    }

    private fun notify(context: Context, id: Int, notification: Notification) {
        try {
            context.getSystemService(NotificationManager::class.java)?.notify(id, notification)
        } catch (e: SecurityException) {
            // Ohne Erlaubnis zeigt Android nichts an. Die Meldung steht trotzdem in der App.
        }
    }

    private fun openApp(context: Context, tab: String, requestCode: Int): PendingIntent {
        val intent = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        if (tab.isNotEmpty()) intent.putExtra(MainActivity.EXTRA_TAB, tab)
        return PendingIntent.getActivity(context, requestCode, intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }

    fun notificationsAllowed(context: Context): Boolean =
        context.getSystemService(NotificationManager::class.java)?.areNotificationsEnabled() ?: false
}
