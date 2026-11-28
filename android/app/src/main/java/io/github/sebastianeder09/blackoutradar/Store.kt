package io.github.sebastianeder09.blackoutradar

import android.content.Context
import android.content.SharedPreferences
import java.io.File

/** Alles, was die App sich merkt: Thema, Einstellungen, Meldungen und der letzte Lagebericht. */
class Store private constructor(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("einstellungen", Context.MODE_PRIVATE)

    val log = MessageLog(File(context.filesDir, "meldungen.json"))
    val statusJsonFile = File(context.filesDir, "status.json")
    val statusMdFile = File(context.filesDir, "status.md")

    var target: Target?
        get() {
            val topic = prefs.getString("topic", null) ?: return null
            return Target(prefs.getString("server", null) ?: Ntfy.DEFAULT_SERVER, topic)
        }
        set(value) {
            val editor = prefs.edit()
            if (value == null) editor.remove("topic").remove("server")
            else editor.putString("topic", value.topic).putString("server", value.server)
            editor.apply()
        }

    /**
     * Das Thema aus der Installationsdatei, mit dem die App schon etwas angefangen hat (siehe [AppFile]).
     * Solange hier etwas anderes steht als in der Datei, bietet die App das Thema aus der Datei an.
     */
    var builtInSeen: String?
        get() = prefs.getString("builtInSeen", null)
        set(value) = prefs.edit().putString("builtInSeen", value).apply()

    /** Die letzte verarbeitete Meldung. Ab ihr fragt die App beim Server nach. */
    var lastId: String?
        get() = prefs.getString("lastId", null)
        set(value) = prefs.edit().putString("lastId", value).apply()

    /** Zeitpunkt der Einrichtung in Sekunden. Gilt als Startpunkt, solange noch keine Meldung da ist. */
    var sinceTime: Long
        get() = prefs.getLong("sinceTime", 0L)
        set(value) = prefs.edit().putLong("sinceTime", value).apply()

    /**
     * Beim Einrichten war der Server nicht erreichbar: Was er von davor noch hat, fehlt in der Liste
     * und wird nachgeholt, sobald die Verbindung steht.
     */
    var historyPending: Boolean
        get() = prefs.getBoolean("historyPending", false)
        set(value) = prefs.edit().putBoolean("historyPending", value).apply()

    /** Alarm über die Wecker-Lautstärke, damit er auch bei "Lautlos" und "Nicht stören" läutet. */
    var loudAlarm: Boolean
        get() = prefs.getBoolean("loudAlarm", true)
        set(value) = prefs.edit().putBoolean("loudAlarm", value).apply()

    /** Alarmton wiederholen, bis jemand reagiert. */
    var repeatAlarm: Boolean
        get() = prefs.getBoolean("repeatAlarm", false)
        set(value) = prefs.edit().putBoolean("repeatAlarm", value).apply()

    /** Hinweis, wenn der Radar selbst keinen neuen Lagebericht mehr liefert. */
    var watchMonitor: Boolean
        get() = prefs.getBoolean("watchMonitor", true)
        set(value) = prefs.edit().putBoolean("watchMonitor", value).apply()

    var statusFetchedAt: Long
        get() = prefs.getLong("statusFetchedAt", 0L)
        set(value) = prefs.edit().putLong("statusFetchedAt", value).apply()

    var statusCheckedAt: Long
        get() = prefs.getLong("statusCheckedAt", 0L)
        set(value) = prefs.edit().putLong("statusCheckedAt", value).apply()

    var staleWarnedAt: Long
        get() = prefs.getLong("staleWarnedAt", 0L)
        set(value) = prefs.edit().putLong("staleWarnedAt", value).apply()

    /** Wann die App den Lagebericht zuletzt mit den angekommenen Meldungen abgeglichen hat (Notweg). */
    var fallbackCheckedAt: Long
        get() = prefs.getLong("fallbackCheckedAt", 0L)
        set(value) = prefs.edit().putLong("fallbackCheckedAt", value).apply()

    /** Ob der Lagebericht die Meldungen des Radars führt. Ohne sie gibt es nichts abzugleichen. */
    var fallbackReady: Boolean
        get() = prefs.getBoolean("fallbackReady", false)
        set(value) = prefs.edit().putBoolean("fallbackReady", value).apply()

    var updateCheckedAt: Long
        get() = prefs.getLong("updateCheckedAt", 0L)
        set(value) = prefs.edit().putLong("updateCheckedAt", value).apply()

    /** Nummer der neuesten veröffentlichten App-Fassung, 0 wenn unbekannt. */
    var latestBuild: Int
        get() = prefs.getInt("latestBuild", 0)
        set(value) = prefs.edit().putInt("latestBuild", value).apply()

    /** Ob die App schon einmal um die Erlaubnisse gebeten hat. */
    var askedPermissions: Boolean
        get() = prefs.getBoolean("askedPermissions", false)
        set(value) = prefs.edit().putBoolean("askedPermissions", value).apply()

    /** Nur im Testbau: anderes Ziel für den öffentlichen Alarm, etwa der nachgestellte Server (siehe [PublicAlarm]). */
    var publicOverride: String?
        get() = prefs.getString("publicTarget", null)
        set(value) = prefs.edit().putString("publicTarget", value).apply()

    /** Nur im Testbau: andere Adresse für den Lagebericht. */
    var statusBaseOverride: String?
        get() = prefs.getString("statusBase", null)
        set(value) = prefs.edit().putString("statusBase", value).apply()

    companion object {
        @Volatile
        private var instance: Store? = null

        fun get(context: Context): Store =
            instance ?: synchronized(this) {
                instance ?: Store(context.applicationContext).also { instance = it }
            }
    }
}
