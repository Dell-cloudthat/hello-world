package com.efsavage.alerts;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.regex.Pattern;
import javax.servlet.ServletException;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;

/**
 * Returns JSON details for a selected ticker.
 *
 * GET /api/ticker-snapshot?ticker=KSA
 */
public class TickerSnapshotServlet extends HttpServlet {
  private static final Pattern SAFE_TICKER = Pattern.compile("^[A-Za-z0-9\\.\\^\\-_=]{1,25}$");

  @Override
  protected void doGet(HttpServletRequest req, HttpServletResponse resp)
      throws ServletException, IOException {
    resp.setCharacterEncoding("UTF-8");
    resp.setContentType("application/json");

    String ticker = req.getParameter("ticker");
    if (ticker == null) {
      resp.setStatus(400);
      resp.getWriter().write("{\"error\":\"Missing required query param: ticker\"}");
      return;
    }
    ticker = ticker.trim();
    if (!SAFE_TICKER.matcher(ticker).matches()) {
      resp.setStatus(400);
      resp.getWriter().write("{\"error\":\"Invalid ticker format\"}");
      return;
    }

    File baseDir = AlertSnapshotServlet.findRepoRootForOtherServlets();
    File script = new File(baseDir, "analysis/ticker_snapshot.py");
    if (!script.exists()) {
      resp.setStatus(500);
      resp.getWriter()
          .write(
              "{\"error\":\"Could not locate analysis/ticker_snapshot.py\",\"baseDir\":"
                  + jsonEscape(baseDir.getAbsolutePath())
                  + "}");
      return;
    }

    ProcessBuilder pb =
        new ProcessBuilder("python3", script.getAbsolutePath(), "--ticker", ticker.toUpperCase());
    pb.directory(baseDir);
    pb.redirectErrorStream(true);

    Process p = pb.start();

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
                "{\"error\":\"Python ticker snapshot failed\",\"exitCode\":"
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

  // Minimal JSON escape for error payloads
  private static String jsonEscape(String s) {
    String escaped =
        s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r");
    return "\"" + escaped + "\"";
  }
}

