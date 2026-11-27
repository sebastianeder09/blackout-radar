package io.github.sebastianeder09.blackoutradar

import android.app.Application
import android.app.NotificationManager
import android.content.Context
import android.os.PowerManager
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        Alerts.createChannels(this)
    }
}

/** Der Zustand der App als JSON für die Oberfläche. */
object StateJson {
    fun build(context: Context, dark: Boolean): JSONObject {
        val store = Store.get(context)
        val target = store.target
        val power = context.getSystemService(PowerManager::class.java)
        val manager = context.getSystemService(NotificationManager::class.java)
        val alarmChannel = if (store.loudAlarm) Alerts.CH_ALARM_LOUD else Alerts.CH_ALARM
        val alarmMuted = manager?.getNotificationChannel(alarmChannel)?.importance == NotificationManager.IMPORTANCE_NONE
        return JSONObject()
            .put("now", System.currentTimeMillis())
            .put("version", BuildConfig.VERSION_NAME)
            .put("build", BuildConfig.VERSION_CODE)
            .put("debug", BuildConfig.DEBUG)
            .put("repo", BuildConfig.REPO)
            .put("dark", dark)
            .put("hasTopic", target != null)
            .put("topic", target?.let { Ntfy.mask(it.topic) } ?: "")
            .put("server", target?.server ?: "")
            .put("conn", JSONObject()
                .put("state", AppState.conn.name.lowercase())
                .put("since", AppState.connSince)
                .put("detail", AppState.connDetail)
                .put("nextRetryAt", AppState.nextRetryAt)
                .put("running", ListenerService.running))
            .put("perms", JSONObject()
                .put("notifications", Alerts.notificationsAllowed(context))
                .put("battery", power?.isIgnoringBatteryOptimizations(context.packageName) ?: true)
                .put("alarmMuted", alarmMuted))
            .put("settings", JSONObject()
                .put("loudAlarm", store.loudAlarm)
                .put("repeatAlarm", store.repeatAlarm)
                .put("watchMonitor", store.watchMonitor))
            .put("messagesRev", AppState.messagesRev)
            .put("statusRev", AppState.statusRev)
            .put("status", JSONObject()
                .put("loading", AppState.statusLoading)
                .put("error", AppState.statusError)
                .put("fetchedAt", store.statusFetchedAt))
            .put("update", JSONObject()
                .put("latest", store.latestBuild)
                .put("available", store.latestBuild > BuildConfig.VERSION_CODE))
    }
}

/** Neue Fassungen der App. Sie liegen als Download bei GitHub, einen Store gibt es nicht. */
object Updates {
    val DOWNLOAD_URL: String = "https://github.com/" + BuildConfig.REPO + "/releases/latest/download/blackout-radar.apk"
    const val CHECK_EVERY_MS = 12 * 60 * 60_000L

    private val TAG = Regex("app-v(\\d{1,9})")

    /** Liest die laufende Nummer aus dem Namen einer Veröffentlichung, zum Beispiel 12 aus "app-v12". */
    fun parseBuild(tag: String): Int = TAG.matchEntire(tag.trim())?.groupValues?.get(1)?.toIntOrNull() ?: 0

    /** Fragt GitHub nach der neuesten Fassung. Liefert true, wenn die Abfrage gelungen ist. */
    fun check(context: Context): Boolean {
        val store = Store.get(context)
        store.updateCheckedAt = System.currentTimeMillis()
        return try {
            val body = Http.getText("https://api.github.com/repos/" + BuildConfig.REPO + "/releases/latest",
                10_000, "application/vnd.github+json")
            store.latestBuild = parseBuild(JSONObject(body).optString("tag_name"))
            AppState.changed()
            true
        } catch (e: IOException) {
            false
        } catch (e: JSONException) {
            false
        }
    }
}
