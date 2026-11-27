package io.github.sebastianeder09.blackoutradar

import android.content.Context
import org.json.JSONException
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.time.Instant
import java.time.format.DateTimeParseException

/**
 * Der Lagebericht des Radars. Er liegt öffentlich im Zweig "state" des Repositorys und
 * wird hier geladen und aufbewahrt, damit der letzte Stand auch ohne Netz lesbar bleibt.
 */
object StatusRepo {
    private val lock = Any()

    fun baseUrl(store: Store): String {
        val override = if (BuildConfig.DEBUG) store.statusBaseOverride else null
        return (override ?: "https://raw.githubusercontent.com/${BuildConfig.REPO}/state").trimEnd('/')
    }

    /** Die Seite, auf der der Lagebericht für Menschen lesbar steht. Dorthin führen auch die Meldungen des Radars. */
    fun pageUrl(): String = "https://github.com/${BuildConfig.REPO}/blob/state/status.md"

    fun cachedJson(store: Store): String? = read(store.statusJsonFile)

    fun cachedMarkdown(store: Store): String? = read(store.statusMdFile)

    /** Zeitpunkt, zu dem der Radar den aufbewahrten Bericht erstellt hat, in Millisekunden. 0 wenn unbekannt. */
    fun generatedAt(store: Store): Long = generatedAt(cachedJson(store))

    fun generatedAt(json: String?): Long {
        if (json == null) return 0L
        return try {
            Instant.parse(JSONObject(json).optString("generated_at")).toEpochMilli()
        } catch (e: JSONException) {
            0L
        } catch (e: DateTimeParseException) {
            0L
        }
    }

    /** Lädt beide Dateien neu. Liefert true bei Erfolg. Läuft nie auf dem Hauptfaden. */
    fun refresh(context: Context, timeoutMs: Int = 15_000): Boolean {
        val store = Store.get(context)
        synchronized(lock) {
            AppState.statusLoading = true
            AppState.changed()
            try {
                val base = baseUrl(store)
                // Die Minute als Zusatz umgeht den Zwischenspeicher von GitHub (sonst bis zu 5 Minuten alt).
                val fresh = "?t=" + System.currentTimeMillis() / 60_000L
                val json = Http.getText("$base/status.json$fresh", timeoutMs)
                JSONObject(json)  // nur als Probe: unvollständige Antworten nicht aufbewahren
                val markdown = Http.getText("$base/status.md$fresh", timeoutMs)
                write(store.statusJsonFile, json)
                write(store.statusMdFile, markdown)
                store.statusFetchedAt = System.currentTimeMillis()
                AppState.statusError = ""
                return true
            } catch (e: HttpStatusException) {
                AppState.statusError = "Der Lagebericht ist nicht abrufbar (Antwort ${e.code})."
            } catch (e: IOException) {
                AppState.statusError = "Keine Verbindung zum Lagebericht."
            } catch (e: JSONException) {
                AppState.statusError = "Der Lagebericht ist unvollständig angekommen."
            } finally {
                AppState.statusLoading = false
                AppState.statusChanged()
            }
            return false
        }
    }

    private fun read(file: File): String? = try {
        if (file.exists()) file.readText(Charsets.UTF_8) else null
    } catch (e: IOException) {
        null
    }

    private fun write(file: File, text: String) {
        val temp = File(file.parentFile, file.name + ".tmp")
        temp.writeText(text, Charsets.UTF_8)
        if (!temp.renameTo(file)) {
            file.writeText(text, Charsets.UTF_8)
            temp.delete()
        }
    }
}

/** Entscheidet, wann die App warnt, weil der Radar selbst stillsteht. */
object MonitorWatch {
    const val STALE_AFTER_MS = 3 * 60 * 60_000L
    const val REPEAT_AFTER_MS = 12 * 60 * 60_000L

    /**
     * Mindestabstand zwischen zwei Abfragen des Lageberichts im Hintergrund. Der Radar schreibt ihn alle
     * 5 Minuten neu, öfter nachzusehen bringt nichts. Der Wächter kommt etwa alle 15 Minuten, der Dienst
     * fragt in diesem Abstand, solange er ntfy nicht erreicht.
     */
    const val CHECK_EVERY_MS = 5 * 60_000L

    fun isStale(nowMs: Long, generatedAtMs: Long): Boolean =
        generatedAtMs > 0 && nowMs - generatedAtMs >= STALE_AFTER_MS

    fun shouldWarn(nowMs: Long, generatedAtMs: Long, lastWarnedMs: Long): Boolean =
        isStale(nowMs, generatedAtMs) && (lastWarnedMs <= 0 || nowMs - lastWarnedMs >= REPEAT_AFTER_MS)

    /** Alter in Worten, so wie der Radar Zeitspannen schreibt: "45 min", "3 h 20 min", "2 T 4 h". */
    fun age(ms: Long): String {
        val minutes = (ms / 60_000L).coerceAtLeast(0)
        if (minutes < 60) return "$minutes min"
        val hours = minutes / 60
        if (hours < 48) return "$hours h ${(minutes % 60).toString().padStart(2, '0')} min"
        return "${hours / 24} T ${hours % 24} h"
    }
}
