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
            // Der öffentliche Alarm: festes Thema für alle, nur unterschriebene Meldungen zählen.
            .put("public", target != null && target == PublicAlarm.target(store))
            // Die Fassung aus dem Play Store aktualisiert sich dort und gibt sich nicht als Datei weiter.
            .put("play", BuildConfig.PLAY)
            .put("appFile", AppFile.ENABLED)
            .put("builtIn", AppFile.builtIn(context) != null)
            .put("brand", JSONObject()
                .put("name", Brand.NAME)
                .put("web", Brand.WEB)
                .put("contact", Brand.CONTACT)
                .put("phone", Brand.PHONE)
                .put("mail", Brand.MAIL))
            .put("legal", JSONObject()
                .put("imprint", Legal.url(Legal.IMPRINT))
                .put("privacy", Legal.url(Legal.PRIVACY)))
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
            .put("fallback", JSONObject()
                .put("ready", store.fallbackReady)
                .put("checkedAt", store.fallbackCheckedAt))
            .put("update", JSONObject()
                .put("latest", store.latestBuild)
                .put("available", Updates.ENABLED && store.latestBuild > BuildConfig.VERSION_CODE))
    }
}

/**
 * Neue Fassungen der App. Die Fassung von GitHub liegt dort als Download und sieht selbst nach, ob es eine
 * neuere gibt. Die Fassung aus dem Play Store lässt das bleiben: Dort aktualisiert der Store, und eine App
 * von dort darf sich nicht an ihm vorbei erneuern.
 */
object Updates {
    val ENABLED: Boolean = !BuildConfig.PLAY

    /** Wo es die App gibt: im Play Store oder als Datei bei GitHub. Steht in der Nachricht zum Weitergeben. */
    val DOWNLOAD_URL: String =
        if (BuildConfig.PLAY) "https://play.google.com/store/apps/details?id=" + BuildConfig.APPLICATION_ID.removeSuffix(".debug")
        else "https://github.com/" + BuildConfig.REPO + "/releases/latest/download/blackout-radar.apk"
    const val CHECK_EVERY_MS = 12 * 60 * 60_000L

    private val TAG = Regex("app-v(\\d{1,9})")

    /** Liest die laufende Nummer aus dem Namen einer Veröffentlichung, zum Beispiel 12 aus "app-v12". */
    fun parseBuild(tag: String): Int = TAG.matchEntire(tag.trim())?.groupValues?.get(1)?.toIntOrNull() ?: 0

    /** Fragt GitHub nach der neuesten Fassung. Liefert true, wenn die Abfrage gelungen ist. */
    fun check(context: Context): Boolean {
        if (!ENABLED) return true
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

/**
 * Wer die App anbietet. Dieselben Angaben stehen im Impressum (docs/impressum.md). Die Seite zeigt sie unter
 * "Über uns", von dort führen Knöpfe zur Homepage und zum Telefon.
 */
object Brand {
    const val NAME = "ASE-IT"
    const val WEB = "https://www.ase-it.at"
    const val CONTACT = "https://www.ase-it.at/kontakt/"
    const val PHONE = "07263 883 52 10"

    /** Dieselbe Nummer in der Form, die das Telefon wählt. */
    const val PHONE_DIAL = "+4372638835210"

    /** E-Mail-Adresse für Anfragen. Leer hieße: Die Seite bietet stattdessen die Kontaktseite der Homepage an. */
    const val MAIL = "office@ase-it.at"
}

/**
 * Impressum und Datenschutzerklärung. Der Wortlaut liegt einmal im Repository (docs/) und kommt beim Bauen in
 * die App (Ordner "rechtstexte" in den Assets, siehe app/build.gradle.kts). So zeigt die App genau den Text,
 * der auch öffentlich im Netz steht, und sie zeigt ihn ohne Netz.
 */
object Legal {
    const val IMPRINT = "impressum"
    const val PRIVACY = "datenschutz"

    private val NAMES = setOf(IMPRINT, PRIVACY)

    /**
     * Die Adresse, unter der derselbe Text öffentlich steht, oder leer. Die Fassung aus dem Play Store zeigt den
     * Text nur in der App und verweist nicht nach außen: Die öffentliche Adresse steht dort im Eintrag im Store.
     */
    fun url(name: String): String =
        if (BuildConfig.PLAY) "" else "https://github.com/" + BuildConfig.REPO + "/blob/main/docs/" + name + ".md"

    /** Der Text aus der App selbst, oder leer, wenn es ihn nicht gibt. */
    fun text(context: Context, name: String): String {
        if (name !in NAMES) return ""
        return try {
            context.assets.open("rechtstexte/$name.md").bufferedReader(Charsets.UTF_8).use { it.readText() }
        } catch (e: IOException) {
            ""
        }
    }
}
