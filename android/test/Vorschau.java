import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
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
        } else {
            System.err.println("Aufruf: Vorschau.java schreiben <ordner> [breite] | lesen <protokoll> <zielordner>");
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
}
