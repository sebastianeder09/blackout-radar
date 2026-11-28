package io.github.sebastianeder09.blackoutradar

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.File
import java.io.FileNotFoundException
import java.io.IOException

/**
 * Die Installationsdatei dieser App: das Thema, das sie mitbringt, und die Kopie zum Weitergeben.
 * Wie das Thema in die Datei kommt, steht bei [ApkTopic].
 */
object AppFile {
    /** Ob dieser Bau die App als Datei samt Thema weitergibt und ein mitgebrachtes Thema annimmt. */
    val ENABLED: Boolean = BuildConfig.APP_FILE

    /** Unter diesem Namen kommt die Datei am anderen Handy an. */
    const val SHARE_NAME = "blackout-radar-mit-thema.apk"
    const val MIME = "application/vnd.android.package-archive"

    /** Begleittext für die App, die die Datei verschickt. Messenger zeigen ihn unter der Datei an. */
    const val SHARE_TEXT = "Blackout-Radar: Alarm aufs Handy bei einem großen Stromausfall.\n\n" +
        "Die Datei antippen und installieren, dann die App einmal öffnen. Sie richtet sich selbst ein, " +
        "einzugeben ist nichts.\n\n" +
        "Bitte nicht weiterschicken: Die Datei enthält den Zugang zu den Meldungen."

    private var loaded = false
    private var builtIn: Target? = null

    /**
     * Das Thema, das die Installationsdatei mitgebracht hat, oder null. Die Datei ändert sich nicht, solange
     * die App läuft, deshalb liest die App sie nur einmal.
     */
    @Synchronized
    fun builtIn(context: Context): Target? {
        if (!loaded) {
            builtIn = if (!ENABLED) null else
                ApkTopic.read(File(context.applicationInfo.sourceDir))?.let { Ntfy.parseTarget(it, BuildConfig.DEBUG) }
            loaded = true
        }
        return builtIn
    }

    /**
     * Das mitgebrachte Thema, solange die App damit noch nichts angefangen hat. Danach gilt, was eingerichtet
     * ist: Wer das Thema später ändert, bekommt das alte nicht bei jedem Start wieder vorgesetzt.
     */
    fun pending(context: Context): Target? {
        val target = builtIn(context) ?: return null
        return if (Store.get(context).builtInSeen == Ntfy.plain(target)) null else target
    }

    /** Hält fest, dass das mitgebrachte Thema verarbeitet ist: eingerichtet, abgelehnt oder ohnehin schon das eigene. */
    fun markSeen(context: Context) {
        val target = builtIn(context) ?: return
        Store.get(context).builtInSeen = Ntfy.plain(target)
    }

    /**
     * Schreibt die Kopie der eigenen Installationsdatei mit dem Thema [target] in den Zwischenspeicher der App
     * und prüft sie durch Zurücklesen. Der Ordner gehört der App allein, andere Apps erreichen ihn nicht.
     */
    @Throws(IOException::class)
    fun writeShare(context: Context, target: Target): File {
        if (!ENABLED) throw IOException("Dieser Bau gibt die App nicht als Datei weiter")
        val file = shareFile(context)
        val fresh = File(file.parentFile, "$SHARE_NAME.neu")
        fresh.parentFile?.mkdirs()
        val text = Ntfy.plain(target)
        try {
            ApkTopic.write(File(context.applicationInfo.sourceDir), fresh, text)
            if (ApkTopic.read(fresh) != text) throw IOException("Das Thema steht nicht in der geschriebenen Datei")
            // Erst die fertige Datei bekommt den Namen, unter dem sie weitergegeben wird.
            if (!fresh.renameTo(file)) throw IOException("Die Datei ließ sich nicht ablegen")
        } finally {
            fresh.delete()
        }
        return file
    }

    fun shareFile(context: Context): File = File(File(context.cacheDir, "weitergabe"), SHARE_NAME)

    /** Adresse, unter der die gewählte App die Datei bei [AppFileProvider] abholt. */
    fun shareUri(context: Context): Uri = Uri.parse("content://${context.packageName}.datei/$SHARE_NAME")
}

/**
 * Reicht die Kopie der Installationsdatei an die App, die der Mensch zum Weitergeben gewählt hat (Messenger,
 * Quick Share, Bluetooth …). Von außen ist hier nichts erreichbar: Lesen darf nur, wem die App das für
 * diesen einen Aufruf erlaubt hat, und es gibt nur diese eine Datei.
 */
class AppFileProvider : ContentProvider() {
    override fun onCreate(): Boolean = true

    private fun file(uri: Uri): File? {
        val context = context ?: return null
        if (!AppFile.ENABLED) return null
        val segments = uri.pathSegments
        if (segments.size != 1 || segments[0] != AppFile.SHARE_NAME) return null
        return AppFile.shareFile(context).takeIf { it.isFile }
    }

    override fun getType(uri: Uri): String? = if (file(uri) != null) AppFile.MIME else null

    /** Name und Größe der Datei. Danach fragt die empfangende App, bevor sie die Datei liest. */
    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor? {
        val file = file(uri) ?: return null
        val columns = projection ?: arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
        val cursor = MatrixCursor(columns, 1)
        cursor.addRow(columns.map { column ->
            when (column) {
                OpenableColumns.DISPLAY_NAME -> AppFile.SHARE_NAME
                OpenableColumns.SIZE -> file.length()
                else -> null
            }
        })
        return cursor
    }

    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        val file = file(uri) ?: throw FileNotFoundException("Diese Datei gibt es hier nicht")
        if (mode != "r") throw FileNotFoundException("Die Datei lässt sich nur lesen")
        return ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
    }

    override fun insert(uri: Uri, values: ContentValues?): Uri? = null

    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = 0

    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = 0
}
