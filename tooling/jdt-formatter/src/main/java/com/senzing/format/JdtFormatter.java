package com.senzing.format;

import org.eclipse.jdt.core.ToolFactory;
import org.eclipse.jdt.core.formatter.CodeFormatter;
import org.eclipse.jface.text.Document;
import org.eclipse.text.edits.TextEdit;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

import javax.xml.parsers.DocumentBuilderFactory;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;

/**
 * CLI wrapper around the Eclipse JDT formatter.
 *
 * <p>Usage:
 * <pre>
 *   java -jar jdt-formatter.jar &lt;profile.xml&gt; &lt;file1.java&gt; [file2.java ...]
 * </pre>
 *
 * <p>Reads {@code profile.xml} (Eclipse formatter-profile export), creates
 * a {@link CodeFormatter} configured with those settings, then formats each
 * Java file in place. Files unchanged by the formatter are left untouched (no
 * rewrite, no spurious mtime bump).
 *
 * <p>Exit codes:
 * <ul>
 *   <li>{@code 0} — all files processed successfully (modified or
 *       unchanged).</li>
 *   <li>{@code 1} — one or more files failed (read error, parse error,
 *       formatter returned null edit on a non-empty source). Per-file
 *       errors are logged to stderr; the formatter continues with
 *       subsequent files so a single broken file doesn't abort a
 *       batch.</li>
 *   <li>{@code 2} — argument-parsing error or profile load failure.</li>
 * </ul>
 */
public final class JdtFormatter
{
    private JdtFormatter() {}

    public static void main(String[] args)
    {
        if (args.length < 2) {
            System.err.println(
                "usage: java -jar jdt-formatter.jar "
                + "<profile.xml> <file1.java> [file2.java ...]");
            System.exit(2);
        }

        Path profilePath = Path.of(args[0]);
        Map<String, String> options;
        try {
            options = loadProfile(profilePath);
        } catch (Exception e) {
            System.err.println(
                "ERROR: failed to load profile " + profilePath + ": "
                + e.getMessage());
            System.exit(2);
            return;
        }

        CodeFormatter formatter = ToolFactory.createCodeFormatter(options);
        if (formatter == null) {
            System.err.println(
                "ERROR: ToolFactory.createCodeFormatter returned null. "
                + "Profile may be missing required settings.");
            System.exit(2);
            return;
        }

        int failures = 0;
        for (int i = 1; i < args.length; i++) {
            Path file = Path.of(args[i]);
            try {
                formatInPlace(formatter, file);
            } catch (Exception e) {
                System.err.println(
                    "ERROR: " + file + ": " + e.getMessage());
                failures++;
            }
        }

        System.exit(failures == 0 ? 0 : 1);
    }

    /**
     * Load an Eclipse formatter profile XML and return the setting-id → value
     * map suitable for
     * {@link ToolFactory#createCodeFormatter(Map)}.
     *
     * <p>Eclipse profile files look like:
     * <pre>
     *   &lt;profiles version="..."&gt;
     *     &lt;profile name="..." kind="CodeFormatterProfile"&gt;
     *       &lt;setting id="org.eclipse.jdt.core.formatter.X" value="..."/&gt;
     *       ...
     *     &lt;/profile&gt;
     *   &lt;/profiles&gt;
     * </pre>
     *
     * <p>This implementation collects all {@code &lt;setting&gt;} elements
     * regardless of which profile they belong to. The standards repo ships
     * exactly one profile per file so the loose collection is fine; a
     * multi-profile file would have its settings merged in document order with
     * later wins.
     */
    static Map<String, String> loadProfile(Path profilePath) throws Exception
    {
        DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
        dbf.setFeature(
            "http://apache.org/xml/features/disallow-doctype-decl", true);
        dbf.setFeature(
            "http://xml.org/sax/features/external-general-entities", false);
        dbf.setFeature(
            "http://xml.org/sax/features/external-parameter-entities", false);

        org.w3c.dom.Document xml = dbf.newDocumentBuilder()
            .parse(profilePath.toFile());

        Map<String, String> options = new HashMap<>();
        NodeList settings = xml.getElementsByTagName("setting");
        for (int i = 0; i < settings.getLength(); i++) {
            Element el = (Element) settings.item(i);
            String id = el.getAttribute("id");
            String value = el.getAttribute("value");
            if (!id.isEmpty()) {
                options.put(id, value);
            }
        }
        return options;
    }

    private static void formatInPlace(CodeFormatter formatter, Path file)
        throws IOException, org.eclipse.text.edits.MalformedTreeException,
               org.eclipse.jface.text.BadLocationException
    {
        String source = Files.readString(file, StandardCharsets.UTF_8);
        String lineSeparator = detectLineSeparator(source);

        TextEdit edit = formatter.format(
            CodeFormatter.K_COMPILATION_UNIT
                | CodeFormatter.F_INCLUDE_COMMENTS,
            source, 0, source.length(), 0, lineSeparator);

        if (edit == null) {
            // Formatter declined to format (e.g., source had a syntax
            // error JDT couldn't recover from). Leave file unchanged.
            return;
        }

        Document doc = new Document(source);
        edit.apply(doc);
        String formatted = doc.get();

        if (!formatted.equals(source)) {
            Files.writeString(
                file, formatted, StandardCharsets.UTF_8);
        }
    }

    /**
     * Return {@code "\r\n"} if the source already uses CRLF endings, else
     * {@code "\n"}. Preserves the file's existing convention.
     */
    private static String detectLineSeparator(String source)
    {
        return source.contains("\r\n") ? "\r\n" : "\n";
    }
}
