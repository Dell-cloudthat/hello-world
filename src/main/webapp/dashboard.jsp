<html>
<head>
  <title>International Rotation Alerts</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body { font-family: Arial, sans-serif; margin: 18px; color: #111; }
    .row { display: flex; gap: 16px; flex-wrap: wrap; }
    .card { border: 1px solid #ddd; border-radius: 10px; padding: 12px 14px; min-width: 280px; flex: 1; }
    .pill { display: inline-block; padding: 6px 10px; border-radius: 999px; font-weight: 700; }
    .pill.wait { background: #f2f2f2; color: #333; }
    .pill.watch { background: #fff2cc; color: #7a4f00; }
    .pill.buy { background: #d9f7d9; color: #0f4d0f; }
    .muted { color: #666; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 8px 6px; border-bottom: 1px solid #eee; font-size: 14px; }
    th { text-align: left; color: #333; }
    canvas { width: 100%; height: 220px; }
    .kpi { font-size: 28px; font-weight: 800; }
    .small { font-size: 12px; }
    a { color: #1256cc; text-decoration: none; }
    a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <h2>International Rotation Alerts</h2>
  <div class="muted">Auto-refreshes every 60s. Data source: Yahoo Finance via local Python.</div>

  <div class="row" style="margin-top: 14px;">
    <div class="card">
      <div class="muted">Signal</div>
      <div id="signalPill" class="pill wait">LOADING</div>
      <div style="margin-top: 10px;">
        <div class="muted">Recommended deploy (of target international sleeve)</div>
        <div id="alloc" class="kpi">—</div>
        <div id="asof" class="muted small"></div>
      </div>
    </div>

    <div class="card">
      <div class="muted">US Market</div>
      <div style="margin-top: 8px;">
        <div><b>S&P 500 drawdown</b>: <span id="dd">—</span></div>
        <div><b>VIX</b>: <span id="vix">—</span> <span class="muted small" id="vixReq"></span></div>
        <div class="muted small" id="nextTrig"></div>
      </div>
    </div>
  </div>

  <div class="row" style="margin-top: 14px;">
    <div class="card">
      <div class="muted">Drawdown (last ~1y)</div>
      <canvas id="ddChart" width="900" height="260"></canvas>
    </div>
    <div class="card">
      <div class="muted">VIX (last ~1y)</div>
      <canvas id="vixChart" width="900" height="260"></canvas>
    </div>
  </div>

  <div class="card" style="margin-top: 14px;">
    <div class="muted">Buy list (top candidates)</div>
    <div class="muted small">Click a row to load details. Use compare to overlay multiple tickers.</div>
    <table>
      <thead>
        <tr><th>Ticker</th><th>Name</th><th>Country</th><th>Link</th></tr>
      </thead>
      <tbody id="candidates">
        <tr><td colspan="4" class="muted">Loading…</td></tr>
      </tbody>
    </table>
  </div>

  <div class="row" style="margin-top: 14px;">
    <div class="card">
      <div class="muted">Selected ticker</div>
      <div id="selTitle" class="kpi" style="font-size: 22px;">—</div>
      <div class="muted small" id="selAsOf"></div>
      <div style="margin-top: 10px;">
        <canvas id="selChart" width="900" height="260"></canvas>
      </div>
      <table style="margin-top: 10px;">
        <tbody id="selMetrics">
          <tr><td class="muted">Click a ticker to load metrics…</td></tr>
        </tbody>
      </table>
      <div style="margin-top: 10px;">
        <button id="addCompare" disabled>Add to compare</button>
        <span class="muted small" id="compareHint"></span>
      </div>
    </div>

    <div class="card">
      <div class="muted">Compare (normalized to 100)</div>
      <div class="muted small">Up to 5 tickers. Click a chip to remove.</div>
      <div id="compareChips" style="margin-top: 8px;"></div>
      <div style="margin-top: 10px;">
        <canvas id="cmpChart" width="900" height="260"></canvas>
      </div>
    </div>
  </div>

  <script>
    function pct(x) { return (x * 100).toFixed(1) + "%"; }
    function fmt(x) { return (Math.round(x * 100) / 100).toString(); }

    function setPill(status) {
      const el = document.getElementById("signalPill");
      el.className = "pill " + (status === "BUY_WINDOW" ? "buy" : (status === "WATCH_VIX" ? "watch" : "wait"));
      el.textContent = status;
    }

    function drawLineChart(canvasId, values, options) {
      const c = document.getElementById(canvasId);
      const ctx = c.getContext("2d");
      const w = c.width, h = c.height;
      ctx.clearRect(0, 0, w, h);

      const padL = 44, padR = 10, padT = 10, padB = 24;
      const innerW = w - padL - padR;
      const innerH = h - padT - padB;

      const minV = options.min !== undefined ? options.min : Math.min(...values);
      const maxV = options.max !== undefined ? options.max : Math.max(...values);
      const range = (maxV - minV) || 1;

      // Axes
      ctx.strokeStyle = "#ddd";
      ctx.beginPath();
      ctx.moveTo(padL, padT);
      ctx.lineTo(padL, padT + innerH);
      ctx.lineTo(padL + innerW, padT + innerH);
      ctx.stroke();

      // Y ticks
      ctx.fillStyle = "#666";
      ctx.font = "12px Arial";
      for (let i = 0; i <= 4; i++) {
        const y = padT + innerH - (i / 4) * innerH;
        const v = minV + (i / 4) * range;
        ctx.strokeStyle = "#f0f0f0";
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(padL + innerW, y);
        ctx.stroke();
        ctx.fillText(options.formatY(v), 6, y + 4);
      }

      // Line
      ctx.strokeStyle = options.color || "#1256cc";
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let i = 0; i < values.length; i++) {
        const x = padL + (i / (values.length - 1)) * innerW;
        const y = padT + innerH - ((values[i] - minV) / range) * innerH;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    function drawMultiChart(canvasId, seriesList, options) {
      // seriesList: [{name, values}] where all values arrays share the same date axis (options.dates)
      const c = document.getElementById(canvasId);
      const ctx = c.getContext("2d");
      const w = c.width, h = c.height;
      ctx.clearRect(0, 0, w, h);

      const padL = 44, padR = 10, padT = 10, padB = 24;
      const innerW = w - padL - padR;
      const innerH = h - padT - padB;

      const all = [];
      for (const s of seriesList) all.push(...s.values);
      const minV = Math.min(...all);
      const maxV = Math.max(...all);
      const range = (maxV - minV) || 1;
      const yPad = range * 0.06; // breathing room
      const yMin = minV - yPad;
      const yMax = maxV + yPad;
      const yRange = (yMax - yMin) || 1;

      // Axes
      ctx.strokeStyle = "#ddd";
      ctx.beginPath();
      ctx.moveTo(padL, padT);
      ctx.lineTo(padL, padT + innerH);
      ctx.lineTo(padL + innerW, padT + innerH);
      ctx.stroke();

      // Y ticks
      ctx.fillStyle = "#666";
      ctx.font = "12px Arial";
      for (let i = 0; i <= 4; i++) {
        const y = padT + innerH - (i / 4) * innerH;
        const v = yMin + (i / 4) * yRange;
        ctx.strokeStyle = "#f0f0f0";
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(padL + innerW, y);
        ctx.stroke();
        ctx.fillText(options.formatY(v), 6, y + 4);
      }

      // Baseline at 100 (if in range)
      if (yMin <= 100 && yMax >= 100) {
        const y100 = padT + innerH - ((100 - yMin) / yRange) * innerH;
        ctx.strokeStyle = "#e0e0e0";
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(padL, y100);
        ctx.lineTo(padL + innerW, y100);
        ctx.stroke();
        ctx.setLineDash([]);
      }

      // X ticks (dates)
      const dates = options.dates || [];
      if (dates.length > 2) {
        ctx.fillStyle = "#666";
        ctx.font = "11px Arial";
        const ticks = 4;
        for (let i = 0; i <= ticks; i++) {
          const idx = Math.round((i / ticks) * (dates.length - 1));
          const x = padL + (idx / (dates.length - 1)) * innerW;
          ctx.strokeStyle = "#f7f7f7";
          ctx.beginPath();
          ctx.moveTo(x, padT);
          ctx.lineTo(x, padT + innerH);
          ctx.stroke();
          const label = String(dates[idx]);
          ctx.fillText(label, Math.max(padL, x - 28), padT + innerH + 16);
        }
      }

      const palette = ["#1256cc", "#cc1f1a", "#0f7b6c", "#7b3fe4", "#c45b00"];
      seriesList.forEach((s, idx) => {
        ctx.strokeStyle = palette[idx % palette.length];
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        for (let i = 0; i < s.values.length; i++) {
          const x = padL + (i / (s.values.length - 1)) * innerW;
          const y = padT + innerH - ((s.values[i] - yMin) / yRange) * innerH;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
      });

      // Legend
      ctx.font = "12px Arial";
      seriesList.forEach((s, idx) => {
        const last = s.values[s.values.length - 1];
        const first = s.values[0];
        const chg = first ? ((last / first) - 1) : 0;
        ctx.fillStyle = palette[idx % palette.length];
        ctx.fillRect(padL + idx * 120, 6, 10, 10);
        ctx.fillStyle = "#111";
        ctx.fillText(s.name + " " + last.toFixed(0) + " (" + (chg * 100).toFixed(1) + "%)", padL + idx * 120 + 14, 15);
      });
    }

    let selectedTicker = null;
    let selectedSnapshot = null;
    let compare = []; // [{ticker, dates: [...], values: [...]}]

    async function loadTicker(ticker) {
      selectedTicker = ticker;
      selectedSnapshot = null;
      document.getElementById("selTitle").textContent = ticker;
      document.getElementById("selAsOf").textContent = "Loading…";
      document.getElementById("selMetrics").innerHTML = "<tr><td class='muted'>Loading…</td></tr>";
      document.getElementById("addCompare").disabled = true;
      document.getElementById("compareHint").textContent = "";

      const url = "<%= request.getContextPath() %>/api/ticker-snapshot?ticker=" + encodeURIComponent(ticker);
      const res = await fetch(url, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok || !data || !data.ticker) {
        document.getElementById("selAsOf").textContent = "Error loading ticker: " + (data && data.error ? data.error : ("HTTP " + res.status));
        return;
      }
      selectedSnapshot = data;
      document.getElementById("selTitle").textContent = data.ticker + "  (last: " + fmt(data.price.last) + ")";
      document.getElementById("selAsOf").textContent = "As of " + data.as_of;

      const m = [];
      m.push(["3m return", pct(data.returns.r_3m)]);
      m.push(["6m return", pct(data.returns.r_6m)]);
      m.push(["12m return", pct(data.returns.r_12m)]);
      m.push(["Max DD (1y)", pct(data.risk.max_drawdown_1y)]);
      m.push(["Max DD (3y)", pct(data.risk.max_drawdown_3y)]);
      m.push(["Beta vs SPX (3y, weekly)", (data.market.beta_3y_weekly == null ? "—" : (Math.round(data.market.beta_3y_weekly * 100) / 100))]);
      m.push(["Corr vs SPX (3y, weekly)", (data.market.corr_3y_weekly == null ? "—" : (Math.round(data.market.corr_3y_weekly * 100) / 100))]);

      document.getElementById("selMetrics").innerHTML =
        m.map(([k,v]) => "<tr><td><b>" + k + "</b></td><td>" + v + "</td></tr>").join("");

      drawLineChart("selChart", data.series.norm_100, {
        color: "#0f7b6c",
        formatY: (v) => v.toFixed(0)
      });

      document.getElementById("addCompare").disabled = false;
      document.getElementById("compareHint").textContent = compare.some(x => x.ticker === data.ticker) ? "(already in compare)" : "";
    }

    function renderCompare() {
      const chips = document.getElementById("compareChips");
      chips.innerHTML = "";
      compare.forEach((c) => {
        const b = document.createElement("button");
        b.textContent = c.ticker + " ×";
        b.style.marginRight = "8px";
        b.onclick = () => { compare = compare.filter(x => x.ticker !== c.ticker); renderCompare(); };
        chips.appendChild(b);
      });

      if (compare.length === 0) {
        drawLineChart("cmpChart", [100,100], { color: "#ddd", formatY: (v)=>v.toFixed(0) });
        return;
      }

      // ACCURACY FIX:
      // Align all series on the same calendar dates (intersection of date strings).
      const sets = compare.map(s => new Set(s.dates));
      let common = sets[0];
      for (let i = 1; i < sets.length; i++) {
        const next = new Set();
        common.forEach(d => { if (sets[i].has(d)) next.add(d); });
        common = next;
      }
      let commonDates = Array.from(common).sort(); // YYYY-MM-DD sorts lexicographically
      if (commonDates.length === 0) return;

      // Keep last ~200 points for readability
      if (commonDates.length > 220) commonDates = commonDates.slice(-220);

      // Build aligned values
      const aligned = compare.map(s => {
        const map = {};
        for (let i = 0; i < s.dates.length; i++) map[s.dates[i]] = s.values[i];
        const vals = commonDates.map(d => map[d]);
        return { name: s.ticker, values: vals };
      });

      // Downsample (if still too dense)
      const L = commonDates.length;
      let step = 1;
      if (L > 220) step = Math.ceil(L / 220);
      const dsDates = commonDates.filter((_, i) => i % step === 0);
      const dsAligned = aligned.map(s => ({ name: s.name, values: s.values.filter((_, i) => i % step === 0) }));

      drawMultiChart("cmpChart", dsAligned, { dates: dsDates, formatY: (v)=>v.toFixed(0) });
    }

    async function refresh() {
      let res, data;
      try {
        res = await fetch("<%= request.getContextPath() %>/api/alert-snapshot", { cache: "no-store" });
        data = await res.json();
      } catch (e) {
        setPill("WAIT");
        document.getElementById("asof").textContent = "API error: " + (e && e.message ? e.message : String(e));
        return;
      }

      if (!res.ok || !data || !data.signal) {
        setPill("WAIT");
        const msg = data && data.error ? data.error : ("HTTP " + res.status);
        const detail = data && data.output ? (" | " + data.output) : "";
        document.getElementById("asof").textContent = "Snapshot error: " + msg + detail;
        return;
      }

      setPill(data.signal.status);
      document.getElementById("alloc").textContent = data.signal.recommended_allocation_pct_of_target + "%";
      document.getElementById("asof").textContent = "As of " + data.as_of + " (generated " + data.generated_at_utc + ")";
      // Email status (optional)
      if (data.email && data.email.enabled) {
        const extra = " | email: " + (data.email.sent ? ("sent @ " + data.email.sent_at_utc) : ("not sent" + (data.email.throttled ? " (throttled)" : ""))) + (data.email.error ? (" | error: " + data.email.error) : "");
        document.getElementById("asof").textContent += extra;
      }

      document.getElementById("dd").textContent = pct(data.spx.drawdown);
      document.getElementById("vix").textContent = fmt(data.vix.level);
      document.getElementById("vixReq").textContent = "(min " + fmt(data.vix.min_required) + ", ok=" + data.vix.ok + ")";
      document.getElementById("nextTrig").textContent = "Next drawdown trigger: " + (data.signal.next_drawdown_trigger === null ? "none" : pct(data.signal.next_drawdown_trigger));

      // Candidates table
      const tb = document.getElementById("candidates");
      tb.innerHTML = "";
      for (const c of data.candidates) {
        const tr = document.createElement("tr");
        tr.style.cursor = "pointer";
        tr.onclick = () => loadTicker(c.ticker);
        const t = document.createElement("td"); t.textContent = c.ticker;
        const n = document.createElement("td"); n.textContent = c.name || "";
        const co = document.createElement("td"); co.textContent = c.country || "";
        const l = document.createElement("td");
        const a = document.createElement("a");
        a.href = "https://finance.yahoo.com/quote/" + encodeURIComponent(c.ticker);
        a.target = "_blank";
        a.textContent = "Yahoo";
        l.appendChild(a);
        tr.appendChild(t); tr.appendChild(n); tr.appendChild(co); tr.appendChild(l);
        tb.appendChild(tr);
      }

      // Charts
      drawLineChart("ddChart", data.series.drawdown, {
        color: "#cc1f1a",
        formatY: (v) => (v * 100).toFixed(0) + "%"
      });
      drawLineChart("vixChart", data.series.vix, {
        color: "#1256cc",
        formatY: (v) => v.toFixed(0)
      });
    }

    document.getElementById("addCompare").onclick = () => {
      if (!selectedSnapshot) return;
      const t = selectedSnapshot.ticker;
      if (compare.some(x => x.ticker === t)) return;
      if (compare.length >= 5) {
        document.getElementById("compareHint").textContent = "(compare limit: 5)";
        return;
      }
      compare.push({ ticker: t, dates: selectedSnapshot.series.dates, values: selectedSnapshot.series.norm_100 });
      renderCompare();
      document.getElementById("compareHint").textContent = "";
    };

    refresh();
    renderCompare();
    setInterval(refresh, 60000);
  </script>
</body>
</html>

