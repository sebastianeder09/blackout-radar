import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;
import java.util.stream.Collectors;
import java.util.stream.Stream;
import javax.imageio.IIOImage;
import javax.imageio.ImageIO;
import javax.imageio.ImageWriteParam;
import javax.imageio.ImageWriter;
import javax.imageio.stream.MemoryCacheImageOutputStream;

/**
 * Bildschirmfotos aus dem Emulator-Test verkleinert ins Protokoll schreiben und wieder herausholen.
 *
 * Die Bilder in voller Größe liegen als Artefakt beim Lauf. Wer an die Artefakte nicht herankommt
 * (etwa eine Prüfung, die nur die Protokolle lesen darf), bekommt sie so trotzdem zu sehen:
 *
 *   java android/test/Vorschau.java schreiben <ordner> [breite]       im Lauf: alle *.png als Text ausgeben
 *   java android/test/Vorschau.java lesen <protokoll> <zielordner>    am Rechner: Bilder aus dem Protokoll holen
 *
 * Das Protokoll eines Laufs liefert: gh api repos/<besitzer>/<repo>/actions/jobs/<nummer>/logs
 *
 * Dazu der Vergleich zweier Bildschirmfotos, mit dem der Emulator-Test prüft, ob das Bild am Handy
 * einer Änderung wirklich folgt:
 *
 *   java android/test/Vorschau.java vergleichen <bild1> <bild2> [von] [bis]
 *
 * Verglichen wird der Streifen zwischen den Höhen "von" und "bis" (Prozent von oben, sonst das ganze
 * Bild). Ende mit 0, wenn sich das Bild dort geändert hat, mit 1, wenn es gleich geblieben ist.
 *
 * Braucht nur Java ab Version 11, keine Bibliotheken.
 */
public class Vorschau {
    private static final String START = "VORSCHAU-ANFANG ";
    private static final String LINE = "VORSCHAU-ZEILE ";
    private static final String END = "VORSCHAU-ENDE ";

    public static void main(String[] args) throws IOException {
        if (args.length >= 2 && args[0].equals("schreiben")) {
            write(Path.of(args[1]), args.length > 2 ? Integer.parseInt(args[2]) : 405);
        } else if (args.length == 3 && args[0].equals("lesen")) {
            read(Path.of(args[1]), Path.of(args[2]));
        } else if (args.length >= 3 && args[0].equals("vergleichen")) {
            System.exit(compare(Path.of(args[1]), Path.of(args[2]),
                    args.length > 3 ? Integer.parseInt(args[3]) : 0, args.length > 4 ? Integer.parseInt(args[4]) : 100));
        } else {
            System.err.println("Aufruf: Vorschau.java schreiben <ordner> [breite] | lesen <protokoll> <zielordner>"
                    + " | vergleichen <bild1> <bild2> [von] [bis]");
            System.exit(2);
        }
    }

    private static void write(Path folder, int width) throws IOException {
        List<Path> images;
        try (Stream<Path> files = Files.list(folder)) {
            images = files.filter(p -> p.getFileName().toString().endsWith(".png")).sorted().collect(Collectors.toList());
        }
        for (Path path : images) {
            BufferedImage image = ImageIO.read(path.toFile());
            if (image == null) continue;
            byte[] jpeg = jpeg(shrink(image, width), 0.62f);
            String name = path.getFileName().toString().replaceFirst("\\.png$", "");
            String text = Base64.getEncoder().encodeToString(jpeg);
            System.out.println(START + name + " " + jpeg.length);
            for (int i = 0; i < text.length(); i += 400) {
                System.out.println(LINE + text.substring(i, Math.min(text.length(), i + 400)));
            }
            System.out.println(END + name);
        }
    }

    /** Verkleinert in Schritten von höchstens der Hälfte, damit Schrift lesbar bleibt. */
    private static BufferedImage shrink(BufferedImage source, int width) {
        BufferedImage current = source;
        while (true) {
            int w = Math.max(width, current.getWidth() / 2);
            int h = Math.max(1, Math.round(current.getHeight() * (w / (float) current.getWidth())));
            BufferedImage next = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
            Graphics2D g = next.createGraphics();
            g.setRenderingHint(RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR);
            g.setRenderingHint(RenderingHints.KEY_RENDERING, RenderingHints.VALUE_RENDER_QUALITY);
            g.drawImage(current, 0, 0, w, h, null);
            g.dispose();
            current = next;
            if (w <= width) return current;
        }
    }

    private static byte[] jpeg(BufferedImage image, float quality) throws IOException {
        ImageWriter writer = ImageIO.getImageWritersByFormatName("jpeg").next();
        ImageWriteParam param = writer.getDefaultWriteParam();
        param.setCompressionMode(ImageWriteParam.MODE_EXPLICIT);
        param.setCompressionQuality(quality);
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (MemoryCacheImageOutputStream out = new MemoryCacheImageOutputStream(bytes)) {
            writer.setOutput(out);
            writer.write(null, new IIOImage(image, null, null), param);
        } finally {
            writer.dispose();
        }
        return bytes.toByteArray();
    }

    private static void read(Path log, Path target) throws IOException {
        Files.createDirectories(target);
        String name = null;
        List<String> parts = new ArrayList<>();
        int count = 0;
        // Jede Zeile des Protokolls beginnt mit einer Zeitangabe, deshalb zählt nur der Teil ab der Marke.
        for (String line : Files.readAllLines(log, StandardCharsets.UTF_8)) {
            int at;
            if ((at = line.indexOf(START)) >= 0) {
                name = line.substring(at + START.length()).trim().split(" ")[0].replaceAll("[^A-Za-z0-9._-]", "_");
                parts.clear();
            } else if (name != null && (at = line.indexOf(LINE)) >= 0) {
                parts.add(line.substring(at + LINE.length()).trim());
            } else if (name != null && line.contains(END)) {
                Files.write(target.resolve(name + ".jpg"), Base64.getDecoder().decode(String.join("", parts)));
                count++;
                name = null;
            }
        }
        System.out.println(count + " Bilder nach " + target);
    }

    /**
     * Ab diesem Anteil veränderter Bildpunkte gilt das Bild als geändert. Eine springende Uhrzeit oder eine
     * einzelne neue Zeile bleiben darunter (unter 1 %), eine neue Meldung oder ein anderer Reiter liegen weit darüber.
     */
    private static final double CHANGED_FROM_PERCENT = 2.0;

    private static int compare(Path first, Path second, int from, int to) {
        // Die Ausgabe enthält Umlaute, deshalb fest in UTF-8 und nicht in der Kodierung der Umgebung.
        PrintStream out = new PrintStream(new FileOutputStream(FileDescriptor.out), true, StandardCharsets.UTF_8);
        BufferedImage a, b;
        try {
            a = ImageIO.read(first.toFile());
            b = ImageIO.read(second.toFile());
        } catch (IOException e) {
            a = b = null;
        }
        if (a == null || b == null || a.getWidth() != b.getWidth() || a.getHeight() != b.getHeight()) {
            out.println("nicht vergleichbar (ein Bild fehlt oder die Größen passen nicht)");
            return 2;
        }
        int top = a.getHeight() * Math.max(0, from) / 100;
        int bottom = a.getHeight() * Math.min(100, to) / 100;
        long different = 0;
        for (int y = top; y < bottom; y++) {
            for (int x = 0; x < a.getWidth(); x++) {
                if (distance(a.getRGB(x, y), b.getRGB(x, y)) > 48) different++;
            }
        }
        long all = (long) Math.max(0, bottom - top) * a.getWidth();
        double percent = all == 0 ? 0 : 100.0 * different / all;
        out.println(String.format(Locale.GERMAN, "%.1f %% der Bildpunkte anders (Höhe %d bis %d %%)", percent, from, to));
        return percent >= CHANGED_FROM_PERCENT ? 0 : 1;
    }

    /** Abstand zweier Farben als Summe über Rot, Grün und Blau. */
    private static int distance(int p, int q) {
        return Math.abs((p >> 16 & 255) - (q >> 16 & 255)) + Math.abs((p >> 8 & 255) - (q >> 8 & 255))
                + Math.abs((p & 255) - (q & 255));
    }
}
