// Dashboard statistik Mac: KPI + grafik riwayat 5 menit (SVG, dengan hover).
const WINDOW_MS = 5 * 60 * 1000;

const fmtBytes = (b, d = 1) => {
  if (b == null) return "-";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(i < 2 ? 0 : d)} ${u[i]}`;
};
const fmtRate = (b) => fmtBytes(b) + "/s";
const fmtPct = (v) => (v == null ? "-" : `${Math.round(v)}%`);
const fmtTemp = (v) => (v == null ? "-" : `${v.toFixed(1)}°C`);
const fmtClock = (t) => new Date(t).toLocaleTimeString(LANG === "ru" ? "ru-RU" : "en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
// Footer sidebar tampil di SEMUA halaman, jadi durasinya ikut bahasa antarmuka
// (fmtDur di atas tetap dipakai di dalam halaman Dashboard yang belum dimigrasi).
function fmtDurI18n(s) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  if (d) return t("time.dhm", { d, h });
  return h ? t("time.hm", { h, m }) : t("time.m", { m });
}
const uptimeFoot = (sys) =>
  `${esc(sys.model)} · ${esc(sys.chip)}<br>macOS ${esc(sys.macos)}<br>${esc(t("shell.uptime"))} ${esc(fmtDurI18n(sys.uptime))}`;
let lastSystem = null;   // footer sidebar digambar ulang saat bahasa berganti
document.addEventListener("langchange", () => {
  if (lastSystem && $("sideFoot")) $("sideFoot").innerHTML = uptimeFoot(lastSystem);
});
function niceMax(v, floor, base = 10) {
  v = Math.max(v, floor);
  // base 1024 untuk byte: skala di satuan KB/MB/GB lalu bulatkan 1-2-5
  const unit = base === 1024 ? 1024 ** Math.floor(Math.log(v) / Math.log(1024)) : 1;
  const u = v / unit, p = 10 ** Math.floor(Math.log10(u));
  return [1, 2, 5, 10].map((m) => m * p).find((x) => x >= u) * unit;
}
const batteryStateKeys = { charging: "dash.bat.charging", discharging: "dash.bat.discharging", charged: "dash.bat.charged", "AC attached": "dash.bat.acAttached", finishing: "dash.bat.finishing" };
const batteryState = (st) => (batteryStateKeys[st] ? t(batteryStateKeys[st]) : st);
const tempStatus = (v) => v == null ? null : v < 70 ? ["good", "✓", t("dash.status.normal")] : v < 85 ? ["warning", "▲", t("dash.status.warm")] : ["critical", "✕", t("dash.status.hot")];
const pressureStatus = (p) => ({ normal: ["good", "✓", t("dash.status.normal")], warning: ["warning", "▲", t("dash.status.caution")], critical: ["critical", "✕", t("dash.status.critical")] })[p];
const statusHtml = (s) => (s ? `<span class="status ${s[0]}">${s[1]} ${esc(s[2])}</span>` : "");

// ------------------------------------------------------------ chart
// opts: { times, series: [{label, color, values}], max | floor, height, mini, fmt, area }
function lineChart(el, opts) {
  el._opts = opts;
  const W = el.clientWidth || 300, H = opts.height || 140;
  const pl = opts.mini ? 0 : 40, pr = 4, pt = 6, pb = opts.mini ? 2 : 18;
  const { times } = opts;
  const tMax = times.at(-1) ?? Date.now(), tMin = tMax - WINDOW_MS;
  const all = opts.series.flatMap((s) => s.values).filter((v) => v != null);
  const max = opts.max ?? niceMax(Math.max(0, ...all) * 1.1, opts.floor || 1, opts.bytes ? 1024 : 10);
  const x = (t) => pl + ((t - tMin) / WINDOW_MS) * (W - pl - pr);
  const y = (v) => pt + (1 - Math.min(v, max) / max) * (H - pt - pb);
  el._geo = { x, y, W, H, pl, pr, pt, pb, tMin, max };

  let svg = "";
  if (!opts.mini) {
    for (const v of [0, max / 2, max]) {
      svg += `<line class="grid-line" x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}"/>
        <text class="axis-label" x="${pl - 6}" y="${y(v) + 3}" text-anchor="end">${opts.fmt(v, true)}</text>`;
    }
    svg += `<text class="axis-label" x="${pl}" y="${H - 3}">${esc(t("dash.chart.minus5"))}</text>
      <text class="axis-label" x="${W - pr}" y="${H - 3}" text-anchor="end">${esc(t("dash.chart.now"))}</text>`;
  }
  if (times.length < 2) {
    svg += `<text class="axis-label" x="${(W + pl) / 2}" y="${H / 2}" text-anchor="middle">${esc(t("dash.collecting"))}</text>`;
  } else {
    for (const s of opts.series) {
      const pts = times.map((t, i) => [x(t), s.values[i]]).filter((p) => p[1] != null && p[0] >= pl - 1);
      if (pts.length < 2) continue;
      const d = pts.map(([px, v], i) => `${i ? "L" : "M"}${px.toFixed(1)},${y(v).toFixed(1)}`).join("");
      if (opts.area) {
        svg += `<path d="${d}L${pts.at(-1)[0]},${y(0)}L${pts[0][0]},${y(0)}Z" fill="${s.color}" opacity=".14"/>`;
      }
      svg += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    }
  }
  svg += `<g class="hover"></g><rect class="hit" x="${pl}" y="0" width="${Math.max(W - pl - pr, 0)}" height="${H}"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}">${svg}</svg>`;

  if (!el._bound) {
    el._bound = true;
    el.addEventListener("mousemove", (e) => { el._hoverX = e.clientX; el._hoverY = e.clientY; chartHover(el); });
    el.addEventListener("mouseleave", () => { el._hoverX = null; $("tip").style.display = "none"; });
  }
  if (el._hoverX != null) chartHover(el);
}

function chartHover(el) {
  const o = el._opts, g = el._geo, svg = el.querySelector("svg");
  if (!o || o.times.length < 2 || !svg) return;
  const rect = svg.getBoundingClientRect();
  const t = g.tMin + ((el._hoverX - rect.left - g.pl) / (g.W - g.pl - g.pr)) * WINDOW_MS;
  let i = 0;
  o.times.forEach((ti, k) => { if (Math.abs(ti - t) < Math.abs(o.times[i] - t)) i = k; });
  const px = g.x(o.times[i]);
  if (px < g.pl - 1) return;
  let marks = `<line class="cross" x1="${px}" x2="${px}" y1="${g.pt}" y2="${g.H - g.pb}"/>`;
  for (const s of o.series) {
    const v = s.values[i];
    if (v != null) marks += `<circle class="dot-mark" cx="${px}" cy="${g.y(v)}" r="4" fill="${s.color}"/>`;
  }
  el.querySelector(".hover").innerHTML = marks;
  const tip = $("tip");
  tip.innerHTML = `<div class="muted">${fmtClock(o.times[i])}</div>` + o.series.map((s) =>
    `<div><span class="sw" style="background:${s.color}"></span>${esc(s.label)} <b>${o.fmt(s.values[i])}</b></div>`).join("");
  tip.style.display = "block";
  const tw = tip.offsetWidth;
  tip.style.left = `${Math.min(el._hoverX + 14, innerWidth - tw - 8)}px`;
  tip.style.top = `${el._hoverY + 14}px`;
}

// ------------------------------------------------------------ tab
tabs.dashboard = {
  interval: 2000,
  hist: [],
  procSort: "cpu",
  leave() { $("tip").style.display = "none"; },
  async load(silent) {
    const since = this.hist.at(-1)?.t || 0;
    let d;
    try { d = await api(`/api/stats?since=${since}`); } catch (e) { return silent || failView(e); }
    this.hist.push(...d.history.filter((p) => p.t > since));
    const cutoff = Date.now() - WINDOW_MS - 10000;
    this.hist = this.hist.filter((h) => h.t >= cutoff);
    this.data = d;
    if (!$("dash")) this.skeleton();
    this.render();
  },
  skeleton() {
    view.innerHTML = `<div id="dash">
      <div class="grid kpis">
        ${["cpu", "mem", "temp", "gpu"].map((k) => `<div class="card kpi">
          <div class="label"><span id="k-${k}-label"></span><span id="k-${k}-status"></span></div>
          <div class="value" id="k-${k}-value">-</div>
          <div class="sub" id="k-${k}-sub"></div>
          <div class="chart" id="k-${k}-spark" style="margin-top:8px"></div></div>`).join("")}
      </div>
      <div class="grid two">
        <div class="card"><h3>${esc(t("dash.cpuUsage"))}</h3><div class="chart" id="c-cpu"></div></div>
        <div class="card"><h3>${esc(t("dash.perCore"))} <span class="spacer"></span><span class="muted small" id="coreNote"></span></h3>
          <div class="cores" id="cores"></div></div>
      </div>
      <div class="grid two">
        <div class="card"><h3>${esc(t("dash.memory"))} <span class="spacer"></span><span id="memStatus"></span></h3>
          <div class="meter" style="height:12px" id="memBar"></div>
          <div class="legend" id="memLegend"></div>
          <div class="chart" id="c-mem" style="margin-top:14px"></div></div>
        <div class="card"><h3>${esc(t("dash.temp"))} <span class="spacer"></span><span class="muted small">${esc(t("dash.socSensors"))}</span></h3>
          <div id="temps"></div>
          <div class="chart" id="c-temp" style="margin-top:10px"></div></div>
      </div>
      <div class="grid two">
        <div class="card"><h3>${esc(t("dash.network"))}</h3><div class="chart" id="c-net"></div><div class="legend" id="netLegend"></div></div>
        <div class="card"><h3>Disk <span class="spacer"></span><span class="muted small" id="diskNote"></span></h3>
          <div class="meter" style="height:12px"><div id="diskBar"></div></div>
          <div class="legend" id="diskLegend"></div>
          <div class="chart" id="c-disk" style="margin-top:14px"></div><div class="legend" id="ioLegend"></div></div>
      </div>
      <div class="grid three">
        <div class="card"><h3>${esc(t("dash.battery"))} <span class="spacer"></span><span id="batStatus"></span></h3><div id="battery"></div></div>
        <div class="card"><h3>${esc(t("dash.system"))}</h3><dl class="kv" id="sysinfo"></dl></div>
        <div class="card"><h3>${esc(t("dash.topProcs"))} <span class="spacer"></span>
          <span class="seg">${btn("CPU", "procSort", { by: "cpu" }, "active")}${btn(esc(t("dash.memory")), "procSort", { by: "mem" })}</span></h3>
          <table id="procs"></table>
          <div class="card-foot">
            ${btn(`<svg viewBox="0 0 24 24" class="am-ico"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>${esc(t("dash.openAM"))}`, "openAM", {}, "", `title="${esc(t("dash.openAM"))}"`)}
          </div></div>
      </div>
    </div>`;
  },
  render() {
    const d = this.data, h = this.hist, last = h.at(-1) || {};
    const times = h.map((p) => p.t), col = (k) => h.map((p) => p[k]);
    const S1 = "var(--series-1)", S2 = "var(--series-2)";
    const pct = (v, axis) => (v == null ? "-" : axis ? `${v}%` : `${v.toFixed(1)}%`);
    const sys = d.system, mem = d.memory, cpuTemp = d.temps["CPU / SoC"];

    $("hostName").textContent = sys.hostname;
    lastSystem = sys;
    $("sideFoot").innerHTML = uptimeFoot(sys);
    $("headline").textContent = t("dash.updated", { time: fmtClock(Date.now()) });

    // KPI
    const kpi = (k, label, value, unit, sub, status, series, fmt, max) => {
      $(`k-${k}-label`).textContent = label;
      $(`k-${k}-value`).innerHTML = `${value}<small>${unit}</small>`;
      $(`k-${k}-sub`).innerHTML = sub;
      $(`k-${k}-status`).innerHTML = statusHtml(status);
      lineChart($(`k-${k}-spark`), { times, series: [{ label, color: S1, values: series }], height: 40, mini: true, area: true, fmt, max });
    };
    kpi("cpu", "CPU", last.cpu != null ? Math.round(last.cpu) : "-", "%",
      `Load ${sys.load.join(" · ")}`, null, col("cpu"), pct, 100);
    kpi("mem", "RAM", Math.round(mem.percent), "%", `${fmtBytes(mem.used)} / ${fmtBytes(mem.total, 0)}`,
      pressureStatus(mem.pressure), col("mem"), pct, 100);
    kpi("temp", t("dash.cpuTemp"), cpuTemp ? cpuTemp.avg.toFixed(0) : "-", "°C",
      cpuTemp ? esc(t("dash.maxSensors", { max: fmtTemp(cpuTemp.max), n: cpuTemp.sensors })) : esc(t("dash.noSensor")),
      tempStatus(cpuTemp?.max), col("temp"), (v) => fmtTemp(v), 100);
    kpi("gpu", "GPU", d.gpu ? d.gpu.usage : "-", "%",
      d.gpu ? `${esc(d.gpu.model)} · ${esc(t("dash.gpuCores", { n: d.gpu.cores }))}` : "", null, col("gpu"), pct, 100);

    // CPU
    lineChart($("c-cpu"), { times, series: [{ label: "CPU", color: S1, values: col("cpu") }], height: 170, area: true, fmt: pct, max: 100 });
    $("coreNote").textContent = t("dash.coreSplit", { p: sys.cores_p, e: sys.cores_e });
    $("cores").innerHTML = (last.cores || []).map((v, i) => `<div class="core"><span class="muted">${esc(t("dash.coreN", { n: i + 1 }))}</span>
      <div class="meter"><div style="width:${v}%"></div></div><span>${Math.round(v)}%</span></div>`).join("")
      || `<div class="muted small">${esc(t("dash.collecting"))}</div>`;

    // Memori
    const parts = [[t("dash.mem.app"), mem.app, "--series-1"], ["Wired", mem.wired, "--series-2"],
      [t("dash.mem.compressed"), mem.compressed, "--series-3"], ["Cache", mem.cached, "--series-4"]];
    $("memBar").innerHTML = parts.map(([l, v, c]) =>
      `<div title="${esc(l)}: ${fmtBytes(v)}" style="width:${(100 * v) / mem.total}%;background:var(${c})"></div>`).join("");
    $("memLegend").innerHTML = parts.map(([l, v, c]) => `<span><i style="background:var(${c})"></i>${esc(l)} <b>${fmtBytes(v)}</b></span>`).join("") +
      `<span><i style="background:var(--track)"></i>${esc(t("dash.mem.free"))} <b>${fmtBytes(mem.free)}</b></span>
       <span>Swap <b>${fmtBytes(mem.swap_used)} / ${fmtBytes(mem.swap_total, 0)}</b></span>`;
    $("memStatus").innerHTML = `<span class="muted small">${esc(t("dash.memPressure"))}</span> ${statusHtml(pressureStatus(mem.pressure))}`;
    lineChart($("c-mem"), { times, series: [{ label: t("dash.ramUsed"), color: S1, values: col("mem") }], height: 100, area: true, fmt: pct, max: 100 });

    // Suhu
    const temps = Object.entries(d.temps);
    $("temps").innerHTML = temps.length ? temps.map(([name, tv]) => `<div class="temp-row">
        <span>${esc(name === "Battery" ? t("dash.battery") : name)}</span>
        <div class="meter"><div style="width:${Math.min(100, tv.max)}%"></div></div>
        <span><b>${fmtTemp(tv.avg)}</b> <span class="muted small">${esc(t("dash.maxShort"))} ${fmtTemp(tv.max)}</span> ${statusHtml(tempStatus(tv.max))}</span>
      </div>`).join("") : `<div class="muted small">${esc(t("dash.tempUnreadable"))}</div>`;
    lineChart($("c-temp"), { times, series: [{ label: t("dash.cpuTemp"), color: S1, values: col("temp") }], height: 100, fmt: (v, ax) => v == null ? "-" : ax ? `${v}°` : fmtTemp(v), max: 100 });

    // Jaringan
    const rate = (v, ax) => (v == null ? "-" : ax ? fmtBytes(v, 0) : fmtRate(v));
    lineChart($("c-net"), { times, series: [{ label: t("dash.download"), color: S1, values: col("rx") }, { label: t("dash.upload"), color: S2, values: col("tx") }],
      height: 170, fmt: rate, floor: 10240, bytes: true });
    $("netLegend").innerHTML = `<span><i style="background:${S1}"></i>${esc(t("dash.download"))} <b>${fmtRate(last.rx)}</b></span>
      <span><i style="background:${S2}"></i>${esc(t("dash.upload"))} <b>${fmtRate(last.tx)}</b></span>`;

    // Disk
    const dk = d.disk;
    $("diskBar").style.width = `${dk.percent}%`;
    $("diskNote").textContent = t("dash.diskUsedPct", { n: dk.percent });
    $("diskLegend").innerHTML = `<span>${esc(t("dash.disk.used"))} <b>${fmtBytes(dk.used)}</b></span><span>${esc(t("dash.mem.free"))} <b>${fmtBytes(dk.free)}</b></span><span>${esc(t("dash.disk.total"))} <b>${fmtBytes(dk.total, 0)}</b></span>`;
    lineChart($("c-disk"), { times, series: [{ label: t("dash.read"), color: S1, values: col("dr") }, { label: t("dash.write"), color: S2, values: col("dw") }],
      height: 100, fmt: rate, floor: 102400, bytes: true });
    $("ioLegend").innerHTML = `<span><i style="background:${S1}"></i>${esc(t("dash.read"))} <b>${fmtRate(last.dr)}</b></span>
      <span><i style="background:${S2}"></i>${esc(t("dash.write"))} <b>${fmtRate(last.dw)}</b></span>`;

    // Baterai
    const b = d.battery;
    if (b) {
      const healthStatus = b.health == null ? null : b.health >= 80 ? ["good", "✓", t("dash.bat.healthy")] : ["warning", "▲", t("dash.bat.service")];
      $("batStatus").innerHTML = statusHtml(healthStatus);
      $("battery").innerHTML = `
        <div class="kpi"><div class="value">${b.percent}<small>%</small></div>
          <div class="sub">${b.source === "AC" ? "🔌 " : "🔋 "}${esc(batteryState(b.state))}${b.remaining ? ` · ${esc(t("dash.bat.remaining", { time: b.remaining }))}` : ""}</div></div>
        <div class="meter" style="margin:10px 0 14px"><div style="width:${b.percent}%"></div></div>
        <dl class="kv">
          <dt>${esc(t("dash.bat.health"))}</dt><dd>${b.health ?? "-"}%</dd>
          <dt>${esc(t("dash.bat.capacity"))}</dt><dd>${b.max_mah ?? "-"} / ${b.design_mah ?? "-"} mAh</dd>
          <dt>${esc(t("dash.bat.cycles"))}</dt><dd>${b.cycles ?? "-"}</dd>
          <dt>${esc(t("dash.bat.sysPower"))}</dt><dd>${b.watts} W</dd>
          ${b.adapter_watts ? `<dt>${esc(t("dash.bat.adapter"))}</dt><dd>${b.adapter_watts} W</dd>` : ""}
          ${d.temps.Battery ? `<dt>${esc(t("dash.temp"))}</dt><dd>${fmtTemp(d.temps.Battery.avg)}</dd>` : ""}
        </dl>`;
    } else {
      $("battery").innerHTML = `<div class="muted small">${esc(t("dash.bat.none"))}</div>`;
    }

    // Sistem
    $("sysinfo").innerHTML = [
      [t("dash.sys.name"), sys.hostname], ["Model", `${sys.model} (${sys.model_id})`], ["Chip", sys.chip],
      ["Core", `${sys.cores_p + sys.cores_e} (${sys.cores_p}P + ${sys.cores_e}E)`],
      ["RAM", fmtBytes(mem.total, 0)], ["macOS", `${sys.macos} (${sys.build})`],
      ["Uptime", fmtDurI18n(sys.uptime)], ["Load avg", sys.load.join(" · ")], [t("dash.sys.procs"), d.processes.count],
    ].map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");

    this.renderProcs();
  },
  renderProcs() {
    const list = this.data.processes[this.procSort];
    $("procs").innerHTML = `<tr><th>${esc(t("dash.proc.process"))}</th><th class="num">CPU</th><th class="num">${esc(t("dash.memory"))}</th></tr>` +
      list.map((p) => `<tr><td class="pname" title="${esc(p.name)} · PID ${p.pid}">${esc(p.name)}</td><td class="num">${p.cpu.toFixed(1)}%</td>
        <td class="num">${fmtBytes(p.mem)}</td></tr>`).join("");
  },
};
handlers.openAM = async () => {
  const r = await api("/api/activity-monitor", { tab: tabs.dashboard.procSort });
  toast(r.was_running ? t("dash.amOpened") : t("dash.amOpenedTab", { tab: tabs.dashboard.procSort === "mem" ? t("dash.memory") : "CPU" }));
};
handlers.procSort = (d, el) => {
  tabs.dashboard.procSort = d.by;
  el.parentElement.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === el));
  tabs.dashboard.renderProcs();
};
// isi info Mac di sidebar walau dashboard belum dibuka
api("/api/stats?since=" + Date.now()).then((d) => {
  $("hostName").textContent = d.system.hostname;
  lastSystem = d.system;
  $("sideFoot").innerHTML = uptimeFoot(d.system);
}).catch(() => {});
window.addEventListener("resize", () => current === tabs.dashboard && tabs.dashboard.data && tabs.dashboard.render());
