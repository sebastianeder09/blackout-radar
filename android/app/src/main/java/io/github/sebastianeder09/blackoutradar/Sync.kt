package io.github.sebastianeder09.blackoutradar

import android.content.Context
import java.io.IOException

/** Einrichten des Themas und Nachholen verpasster Meldungen. */
object Sync {
    class SetupResult(val ok: Boolean, val error: String = "", val count: Int = 0, val offline: Boolean = false)

    private val setupLock = Any()

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
        synchronized(setupLock) {
            store.target = target
            store.log.clear()
            store.sinceTime = nowSeconds
            notices?.forEach { store.log.add(it) }
            store.lastId = store.log.newestId()
        }
        AppState.messagesChanged()
        Starter.ensure(context)
        ListenerService.kick(force = true)
        return SetupResult(true, count = notices?.size ?: 0, offline = offline)
    }

    /** Vergisst das Thema und alle Meldungen und beendet die Verbindung. */
    fun reset(context: Context) {
        val store = Store.get(context)
        synchronized(setupLock) {
            store.target = null
            store.lastId = null
            store.log.clear()
        }
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

    /** Nimmt eine Meldung auf und zeigt sie an, falls sie neu ist. */
    fun deliver(context: Context, notice: Notice): Boolean {
        val store = Store.get(context)
        val fresh = store.log.add(notice)
        store.lastId = notice.id
        if (fresh) {
            Alerts.show(context, notice)
            AppState.messagesChanged()
        }
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
