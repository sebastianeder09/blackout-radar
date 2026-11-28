package io.github.sebastianeder09.blackoutradar

import org.json.JSONArray
import org.json.JSONException
import java.io.File
import java.io.IOException

/**
 * Die empfangenen Meldungen, neueste zuerst, in einer Datei.
 *
 * Jede Meldung wird nur einmal aufgenommen. Daran hängt, dass ein Alarm nicht doppelt
 * läutet, wenn dieselbe Meldung über die Dauerverbindung und über die Nachfrage kommt.
 */
class MessageLog(private val file: File, private val limit: Int = 300) {
    private var cache: MutableList<Notice>? = null

    @Synchronized
    fun all(): List<Notice> = ArrayList(load())

    @Synchronized
    fun newestId(): String? = load().firstOrNull()?.id

    @Synchronized
    fun find(id: String): Notice? = load().firstOrNull { it.id == id }

    /** Nimmt die Meldung auf. Liefert false, wenn sie schon bekannt ist. */
    @Synchronized
    fun add(notice: Notice): Boolean = put(notice, null)

    /**
     * Nimmt die Meldung auf und entfernt dafür den Eintrag [oldId]: dieselbe Meldung, die vorher
     * auf einem anderen Weg gekommen war. Liefert false, wenn die Meldung schon unter einer anderen
     * Kennung bekannt ist. Trägt sie dieselbe Kennung wie der alte Eintrag, tritt sie an seine Stelle.
     */
    @Synchronized
    fun replace(oldId: String, notice: Notice): Boolean = put(notice, oldId)

    private fun put(notice: Notice, dropId: String?): Boolean {
        val list = load()
        if (list.any { it.id == notice.id && it.id != dropId }) return false
        if (dropId != null) list.removeAll { it.id == dropId }
        var index = list.indexOfFirst { it.time <= notice.time }
        if (index < 0) index = list.size
        list.add(index, notice)
        while (list.size > limit) list.removeAt(list.size - 1)
        save(list)
        return true
    }

    @Synchronized
    fun clear() {
        cache = ArrayList()
        file.delete()
    }

    private fun load(): MutableList<Notice> {
        cache?.let { return it }
        val list = ArrayList<Notice>()
        try {
            if (file.exists()) {
                val array = JSONArray(file.readText(Charsets.UTF_8))
                for (i in 0 until array.length()) {
                    val notice = array.optJSONObject(i)?.let { Notice.fromJson(it) }
                    if (notice != null && list.none { it.id == notice.id }) list.add(notice)
                }
            }
        } catch (e: IOException) {
            // Eine unlesbare Datei darf die App nicht aufhalten. Die Meldungen kommen neu vom Server.
        } catch (e: JSONException) {
            list.clear()
        }
        list.sortByDescending { it.time }
        cache = list
        return list
    }

    private fun save(list: List<Notice>) {
        val array = JSONArray()
        for (notice in list) array.put(notice.toJson())
        try {
            val temp = File(file.parentFile, file.name + ".tmp")
            temp.writeText(array.toString(), Charsets.UTF_8)
            if (!temp.renameTo(file)) {
                file.writeText(array.toString(), Charsets.UTF_8)
                temp.delete()
            }
        } catch (e: IOException) {
            // Der Speicher ist voll oder gesperrt. Die Liste bleibt bis zum Neustart im Arbeitsspeicher.
        }
    }
}
