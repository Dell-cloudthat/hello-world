package com.efsavage.alerts;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

/**
 * Thin bridge from the WAR to the Python analytics code.
 *
 * This servlet executes:
 *   python3 analysis/alert_snapshot.py
 *
 * and returns stdout as application/json.
 *
 * Note: This assumes you're running the webapp from the repo root
 * (e.g., via "mvn jetty:run") so relative paths resolve.
 */
public class AlertSnapshotServlet extends HttpServlet {
  @Override
  protected void doGet(HttpServletRequest req, HttpServletResponse resp)
      throws ServletException, IOException {
    resp.setCharacterEncoding("UTF-8");
    resp.setContentType("application/json");

    File baseDir = findRepoRoot();
    File script = new File(baseDir, "analysis/alert_snapshot.py");
    if (!script.exists()) {
      resp.setStatus(500);
      resp.getWriter()
          .write(
              "{\"error\":\"Could not locate analysis/alert_snapshot.py\",\"baseDir\":"
                  + jsonEscape(baseDir.getAbsolutePath())
                  + "}");
      return;
    }

    ProcessBuilder pb =
        new ProcessBuilder("python3", script.getAbsolutePath());
    pb.directory(baseDir);
    pb.redirectErrorStream(true);

    Process p;
    try {
      p = pb.start();
    } catch (IOException e) {
      resp.setStatus(500);
      resp.getWriter()
          .write(
              "{\"error\":\"Failed to start python3. Ensure python3 is installed and available.\"}");
      return;
    }

    StringBuilder out = new StringBuilder();
    try (BufferedReader r =
        new BufferedReader(new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
      String line;
      while ((line = r.readLine()) != null) {
        out.append(line).append("\n");
      }
    }

    try {
      int code = p.waitFor();
      if (code != 0) {
        resp.setStatus(500);
        resp.getWriter()
            .write(
                "{\"error\":\"Python snapshot script failed\",\"exitCode\":"
                    + code
                    + ",\"output\":"
                    + jsonEscape(out.toString())
                    + "}");
        return;
      }
    } catch (InterruptedException ie) {
      Thread.currentThread().interrupt();
      resp.setStatus(500);
      resp.getWriter().write("{\"error\":\"Interrupted while waiting for python\"}");
      return;
    }

    resp.setStatus(200);
    resp.getWriter().write(out.toString());
  }

  private static File findRepoRoot() {
    // Start from the JVM working directory and walk up a few parents until we find pom.xml + analysis/
    File d = new File(System.getProperty("user.dir", ".")).getAbsoluteFile();
    for (int i = 0; i < 6; i++) {
      File pom = new File(d, "pom.xml");
      File analysisDir = new File(d, "analysis");
      if (pom.exists() && analysisDir.isDirectory()) {
        return d;
      }
      File parent = d.getParentFile();
      if (parent == null) {
        break;
      }
      d = parent;
    }
    // Fallback: current directory
    return new File(System.getProperty("user.dir", ".")).getAbsoluteFile();
  }

  private static String jsonEscape(String s) {
    // Minimal JSON string escape; enough for error payload.
    String escaped =
        s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r");
    return "\"" + escaped + "\"";
  }
}

