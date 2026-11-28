package io.github.sebastianeder09.blackoutradar

import android.content.Context
import java.io.IOException

/** Einrichten des Themas und Nachholen verpasster Meldungen. */
object Sync {
    class SetupResult(val ok: Boolean, val error: String = "", val count: Int = 0, val offline: Boolean = false)

    /** Schützt alles, was die Liste der Meldungen umbaut: Einrichten, Nachholen, Zustellen und den Notweg. */
    internal val lock = Any()

    /**
     * Übernimmt das Thema, lädt still, was der Server aus den letzten Stunden noch hat,
     * und startet die Verbindung. Läuft nie auf dem Hauptfaden.
     */
    fun setup(context: Context, input: String, allowHttp: Boolean = BuildConfig.DEBUG): SetupResult {
        val target = Ntfy.parseTarget(input, allowHttp)
            ?: return SetupResult(false, "Das sieht nicht nach einem Thema aus. Bitte nur den Themennamen " +
                "einfügen, ohne Leerzeichen. Erlaubt sind Buchstaben, Ziffern, Bindestrich und Unterstrich.")
        val store = Store.get(context)
        val nowSeconds = System.currentTimeMillis() / 1000L
        var notices: List<Notice>? = null
        var offline = false
        try {
            notices = poll(target, "all", 12_000)
        } catch (e: HttpStatusException) {
            if (e.code == 429 || e.code >= 500) offline = true
            else return SetupResult(false, "Der Server nimmt dieses Thema nicht an (Antwort ${e.code}).")
        } catch (e: IOException) {
            offline = true
        }
        synchronized(lock) {
            store.target = target
            store.log.clear()
            store.sinceTime = nowSeconds
            notices?.forEach { store.log.add(it) }
            store.lastId = store.log.newestId()
            // Ohne Antwort des Servers fehlt, was er von vorher noch hat. Das holt backfill nach.
            store.historyPending = notices == null
        }
        // Ab jetzt gilt, was eingerichtet ist. Ein Thema aus der Installationsdatei meldet sich nicht noch einmal.
        AppFile.markSeen(context)
        AppState.messagesChanged()
        Starter.ensure(context)
        ListenerService.kick(force = true)
        return SetupResult(true, count = notices?.size ?: 0, offline = offline)
    }

    /** Vergisst das Thema und alle Meldungen und beendet die Verbindung. */
    fun reset(context: Context) {
        val store = Store.get(context)
        synchronized(lock) {
            store.target = null
            store.lastId = null
            store.historyPending = false
            store.log.clear()
        }
        // Die Kopie der App zum Weitergeben enthält das bisherige Thema.
        AppFile.shareFile(context).delete()
        ListenerService.stop(context)
        Watchdog.disarm(context)
        AppState.messagesChanged()
    }

    /**
     * Fragt einmal nach, was seit der letzten Meldung gekommen ist, und zeigt es an.
     * Liefert die Zahl der neuen Meldungen oder -1, wenn der Server nicht erreichbar war.
     */
    fun catchUp(context: Context, timeoutMs: Int): Int {
        val store = Store.get(context)
        val target = store.target ?: return 0
        val since = store.lastId ?: store.sinceTime.toString()
        val notices = try {
            poll(target, since, timeoutMs)
        } catch (e: IOException) {
            return -1
        }
        var fresh = 0
        for (notice in notices) if (deliver(context, notice)) fresh++
        return fresh
    }

    /**
     * Holt nach, was der Server von vor dem Einrichten noch hat, falls er beim Einrichten nicht
     * erreichbar war. Diese Meldungen kommen still in die Liste: Sie waren schon alt, als das Handy
     * dazukam. Alles ab dem Einrichten liefert die Verbindung selbst, und das läutet.
     * Liefert false, wenn der Server noch immer nicht antwortet. Läuft nie auf dem Hauptfaden.
     */
    fun backfill(context: Context, timeoutMs: Int): Boolean {
        val store = Store.get(context)
        if (!store.historyPending) return true
        val target = store.target ?: return true
        val setupTime = store.sinceTime
        if (History.expired(System.currentTimeMillis() / 1000L, setupTime)) {
            store.historyPending = false
            return true
        }
        val notices = try {
            poll(target, "all", timeoutMs)
        } catch (e: IOException) {
            return false
        }
        var added = 0
        synchronized(lock) {
            // Wurde inzwischen neu eingerichtet oder zurückgesetzt, gehört die Antwort nicht mehr hierher.
            if (!store.historyPending || store.target != target || store.sinceTime != setupTime) return true
            for (notice in History.before(notices, setupTime)) if (store.log.add(notice)) added++
            store.historyPending = false
        }
        if (added > 0) AppState.messagesChanged()
        return true
    }

    /**
     * Nimmt eine Meldung von ntfy auf und zeigt sie an, falls sie neu ist.
     *
     * Hat die App dieselbe Meldung schon über den Notweg gezeigt (siehe [Fallback]), ersetzt die
     * Zustellung von ntfy diesen Eintrag still: Geläutet hat es dafür schon.
     */
    fun deliver(context: Context, notice: Notice): Boolean {
        val store = Store.get(context)
        var fresh = false
        var alert = false
        synchronized(lock) {
            val log = store.log.all()
            val twin = if (log.any { it.fallback }) Fallback.twin(log, notice, Fallback.zone(StatusRepo.cachedJson(store))) else null
            if (twin != null) {
                fresh = store.log.replace(twin.id, notice)
            } else {
                fresh = store.log.add(notice)
                alert = fresh
            }
            store.lastId = notice.id
        }
        if (alert) Alerts.show(context, notice)
        if (fresh) AppState.messagesChanged()
        return fresh
    }

    private fun poll(target: Target, since: String, timeoutMs: Int): List<Notice> {
        val body = Http.getText(Ntfy.pollUrl(target, since), timeoutMs)
        val notices = ArrayList<Notice>()
        for (line in body.lineSequence()) {
            val event = Ntfy.parseLine(line)
            if (event is StreamEvent.Message) notices.add(event.notice)
        }
        return notices
    }
}

/** Was beim Nachholen als Vorgeschichte gilt, also als Meldung von vor dem Einrichten. */
object History {
    /** So lange bewahrt ntfy.sh Meldungen auf. Danach gibt es nichts mehr nachzuholen. */
    const val KEPT_SECONDS = 12 * 60 * 60L

    /**
     * Die Meldungen von vor dem Einrichten. Was in derselben Sekunde oder später kam, bleibt der
     * Verbindung überlassen, damit ein Alarm nie still in der Liste landet.
     */
    fun before(notices: List<Notice>, setupSeconds: Long): List<Notice> = notices.filter { it.time < setupSeconds }

    fun expired(nowSeconds: Long, setupSeconds: Long): Boolean = nowSeconds - setupSeconds > KEPT_SECONDS
}
