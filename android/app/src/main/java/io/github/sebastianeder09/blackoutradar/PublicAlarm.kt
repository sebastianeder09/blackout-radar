package io.github.sebastianeder09.blackoutradar

/**
 * Der öffentliche Alarm: ein festes Thema bei ntfy für alle, die die App ohne eigenen Radar nutzen.
 * Installieren, öffnen, einschalten. Ein Thema gibt dabei niemand ein.
 *
 * Das Thema ist öffentlich bekannt, jeder kann dort mitlesen und selbst etwas hinschicken. Deshalb zählt für die
 * App nur, was der Radar unterschrieben hat (siehe [Signed]). Alles andere verwirft sie still: Es erscheint weder
 * als Benachrichtigung noch in der Liste. Aus einer geprüften Meldung nimmt die App Zeit, Dringlichkeit und
 * Kennung aus den unterschriebenen Angaben, nie aus den Feldern, die ntfy mitliefert. Die kann jeder setzen.
 *
 * Der öffentliche Alarm gilt genau dann, wenn als Ziel dieses Thema eingerichtet ist. Wer denselben Namen von
 * Hand als eigenes Thema einträgt, bekommt deshalb ebenfalls nur geprüfte Meldungen.
 */
object PublicAlarm {
    const val TOPIC = "blackout-radar-alarm"

    /** So beginnt die Kennung einer Meldung aus dem öffentlichen Alarm: pub:<Zeit>:<Schlüssel der Meldung>. */
    const val ID_PREFIX = "pub:"

    /**
     * So viel später, als der Radar sie erstellt hat, darf ntfy eine Meldung noch angenommen haben. Der Radar
     * versucht den Versand 12 Stunden lang. Was ntfy erst danach bekommen hat, ist keine Zustellung des Radars
     * mehr, sondern eine alte echte Meldung, die jemand noch einmal eingespielt hat.
     */
    const val MAX_DELAY_S = 13 * 60 * 60L

    private val BUILT_IN = Target(Ntfy.DEFAULT_SERVER, TOPIC)

    /** Wohin sich die App für den öffentlichen Alarm verbindet. Nur der Testbau kennt ein anderes Ziel. */
    fun target(store: Store): Target {
        val override = if (BuildConfig.DEBUG) store.publicOverride else null
        return override?.let { Ntfy.parseTarget(it, allowHttp = true) } ?: BUILT_IN
    }

    /** Wahr, wenn auf diesem Handy der öffentliche Alarm eingerichtet ist. */
    fun active(store: Store): Boolean = store.target?.let { it == target(store) } ?: false

    /**
     * Die Kennung einer Meldung des öffentlichen Alarms. Sie besteht nur aus unterschriebenen Angaben und ist
     * deshalb dieselbe, egal auf welchem Weg die Meldung kommt: über ntfy, noch einmal eingespielt oder über
     * den Notweg aus dem Lagebericht. So läutet jede Meldung nur einmal.
     */
    fun id(time: Long, ident: String): String = ID_PREFIX + time + ":" + ident

    /**
     * Die Meldung [raw], wie ntfy sie unter [topic] geliefert hat, in der Form, die die App anzeigt.
     * null, wenn die Unterschrift fehlt oder nicht passt, oder wenn ntfy die Meldung erst lange nach ihrem
     * Entstehen bekommen hat.
     */
    fun open(raw: Notice, topic: String, keys: Map<String, String> = Signed.KEYS): Notice? {
        val sealed = Signed.unseal(keys, topic, raw.title, raw.message, raw.click) ?: return null
        // raw.time setzt der Server von ntfy beim Annehmen, wer sendet, kann sie nicht zurückdatieren.
        if (raw.time - sealed.time > MAX_DELAY_S) return null
        return Notice(
            id = id(sealed.time, sealed.ident),
            time = sealed.time,
            title = raw.title,
            message = sealed.body,
            priority = Levels.priority(sealed.level),
            tags = Levels.tags(sealed.level),
            click = raw.click,
        )
    }
}
