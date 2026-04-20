// Screener app — filter rail + results table + Fund Focus Mode
const { useState, useMemo, useEffect } = React;

// --- Filter Rail ---
function FilterRail({ filters, setFilters, resultCount, totalCount, onReset }) {
  const toggleSet = (key, val) => {
    setFilters(f => {
      const next = new Set(f[key]);
      next.has(val) ? next.delete(val) : next.add(val);
      return { ...f, [key]: next };
    });
  };
  const upd = (k, v) => setFilters(f => ({ ...f, [k]: v }));

  return (
    <aside className="scr-filters">
      <div className="phead">
        <div><span className="title">Filters</span></div>
        <div className="actions"><button className="icon-btn" onClick={onReset} title="Reset">⟲</button></div>
      </div>
      <div className="scr-filters-body">
        <div className="filter-group">
          <div className="label"><span>Universe</span><span className="count">{filters.universes.size}</span></div>
          <div className="chip-row">
            {FUND_UNIVERSES.map(u => (
              <button key={u} className={"chip " + (filters.universes.has(u) ? "on" : "")} onClick={() => toggleSet("universes", u)}>{u}</button>
            ))}
          </div>
        </div>
        <div className="filter-group">
          <div className="label"><span>Strategy</span><span className="count">{filters.strategies.size}</span></div>
          <div className="chip-row">
            {STRATEGIES.map(s => (
              <button key={s} className={"chip " + (filters.strategies.has(s) ? "on" : "")} onClick={() => toggleSet("strategies", s)}>{s}</button>
            ))}
          </div>
        </div>
        <div className="filter-group">
          <div className="label"><span>Geography</span><span className="count">{filters.geos.size}</span></div>
          <div className="chip-row">
            {GEOGRAPHIES.map(g => (
              <button key={g} className={"chip " + (filters.geos.has(g) ? "on" : "")} onClick={() => toggleSet("geos", g)}>{g}</button>
            ))}
          </div>
        </div>
        <div className="filter-group">
          <div className="label">AUM · R$ Bi</div>
          <div className="range-inputs">
            <input placeholder="min" value={filters.aumMin} onChange={e => upd("aumMin", e.target.value)} />
            <span className="sep">—</span>
            <input placeholder="max" value={filters.aumMax} onChange={e => upd("aumMax", e.target.value)} />
          </div>
        </div>
        <div className="filter-group">
          <div className="label">Return 1Y · %</div>
          <div className="range-inputs">
            <input placeholder="min" value={filters.ret1yMin} onChange={e => upd("ret1yMin", e.target.value)} />
            <span className="sep">—</span>
            <input placeholder="max" value={filters.ret1yMax} onChange={e => upd("ret1yMax", e.target.value)} />
          </div>
        </div>
        <div className="filter-group">
          <div className="label">Sharpe (min)</div>
          <div className="range-inputs">
            <input placeholder="min" value={filters.sharpeMin} onChange={e => upd("sharpeMin", e.target.value)} />
            <span className="sep">—</span>
            <input placeholder="max" value={filters.sharpeMax} onChange={e => upd("sharpeMax", e.target.value)} />
          </div>
        </div>
        <div className="filter-group">
          <div className="label">Max Drawdown · %</div>
          <div className="range-inputs">
            <input placeholder="worst" value={filters.ddMin} onChange={e => upd("ddMin", e.target.value)} />
            <span className="sep">—</span>
            <input placeholder="best" value={filters.ddMax} onChange={e => upd("ddMax", e.target.value)} />
          </div>
        </div>
        <div className="filter-group">
          <div className="label">Expense Ratio (max · %)</div>
          <div className="range-inputs" style={{ gridTemplateColumns: "1fr" }}>
            <input placeholder="e.g. 1.5" value={filters.expMax} onChange={e => upd("expMax", e.target.value)} />
          </div>
        </div>
        <div className="filter-group">
          <div className="toggle" onClick={() => upd("eliteOnly", !filters.eliteOnly)}>
            <span style={{ fontSize: 11, color: "var(--fg-secondary)" }}>Netz Elite only</span>
            <span className={"toggle-state " + (filters.eliteOnly ? "on" : "")}>{filters.eliteOnly ? "ON" : "OFF"}</span>
          </div>
        </div>
      </div>
      <div className="scr-filters-foot">
        <button className="btn" onClick={onReset}>RESET</button>
        <button className="btn primary">SAVE PRESET</button>
      </div>
    </aside>
  );
}

// --- Perf sparkline chart for focus mode ---
function PerfChart({ series, label }) {
  const w = 480, h = 160, padL = 30, padR = 10, padT = 12, padB = 22;
  const min = Math.min(...series), max = Math.max(...series);
  const rng = max - min || 1;
  const xOf = i => padL + (i / (series.length - 1)) * (w - padL - padR);
  const yOf = v => padT + (h - padT - padB) - ((v - min) / rng) * (h - padT - padB);
  const pts = series.map((v, i) => `${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`).join(" ");
  const last = series[series.length - 1];
  const first = series[0];
  const up = last >= first;
  const areaPath = `M ${xOf(0)},${h - padB} L ${pts.replace(/,/g, " ").split(" ").reduce((a, _, i, arr) => i % 2 === 0 ? a + (i ? " L " : "") + arr[i] + "," + arr[i + 1] : a, "")} L ${xOf(series.length - 1)},${h - padB} Z`;
  const ticks = 4;
  const tvals = Array.from({ length: ticks }, (_, i) => min + (rng * i) / (ticks - 1));
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="perf-chart" style={{ width: "100%", height: 160 }}>
      <defs>
        <linearGradient id="perfGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={up ? "#3DD39A" : "#FF5C7A"} stopOpacity="0.25" />
          <stop offset="100%" stopColor={up ? "#3DD39A" : "#FF5C7A"} stopOpacity="0" />
        </linearGradient>
      </defs>
      {tvals.map((v, i) => (
        <g key={i}>
          <line x1={padL} x2={w - padR} y1={yOf(v)} y2={yOf(v)} stroke="rgba(102,137,188,0.1)" strokeDasharray="2 3" />
          <text x={padL - 4} y={yOf(v) + 3} fill="var(--fg-tertiary)" fontSize="9" fontFamily="var(--font-mono)" textAnchor="end">{v.toFixed(0)}</text>
        </g>
      ))}
      <path d={areaPath} fill="url(#perfGrad)" />
      <polyline points={pts} fill="none" stroke={up ? "var(--up)" : "var(--down)"} strokeWidth="1.5" />
      <text x={padL} y={10} fill="var(--fg-muted)" fontSize="9" fontFamily="var(--font-mono)" letterSpacing="0.1em">{label}</text>
    </svg>
  );
}

// --- Composite Score Radar ---
function CompositeRadar({ axes, overall, tone }) {
  const size = 260;
  const cx = size / 2, cy = size / 2;
  const rings = [0.25, 0.5, 0.75, 1];
  const outerR = 100;
  const n = axes.length;
  // Start at top, go clockwise
  const angleFor = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const pt = (i, r) => [cx + Math.cos(angleFor(i)) * r, cy + Math.sin(angleFor(i)) * r];
  const ringPath = (r) => axes.map((_, i) => pt(i, r)).map(([x, y], i) => (i ? "L" : "M") + x.toFixed(1) + "," + y.toFixed(1)).join(" ") + " Z";
  const dataPts = axes.map((a, i) => pt(i, outerR * (a.value / 100)));
  const dataPath = dataPts.map(([x, y], i) => (i ? "L" : "M") + x.toFixed(1) + "," + y.toFixed(1)).join(" ") + " Z";
  const labelPts = axes.map((a, i) => {
    const [x, y] = pt(i, outerR + 18);
    const angle = angleFor(i);
    let anchor = "middle";
    if (Math.cos(angle) > 0.3) anchor = "start";
    else if (Math.cos(angle) < -0.3) anchor = "end";
    return { x, y: y + 3, anchor, label: a.label, value: Math.round(a.value) };
  });
  const overallColor = tone === "up" ? "var(--up)" : tone === "down" ? "var(--down)" : "var(--accent)";
  return (
    <div className="radar-wrap">
      <svg viewBox={`0 0 ${size + 160} ${size}`} style={{ width: "100%", maxWidth: 420, height: "auto", display: "block", margin: "0 auto" }}>
        <g transform={`translate(80 0)`}>
          {rings.map((r, i) => (
            <path key={i} d={ringPath(outerR * r)} fill="none" stroke="rgba(102,137,188,0.2)" strokeWidth="0.8" />
          ))}
          {axes.map((_, i) => {
            const [x, y] = pt(i, outerR);
            return <line key={i} x1={cx} y1={cy} x2={x} y2={y} stroke="rgba(102,137,188,0.15)" strokeWidth="0.8" />;
          })}
          <path d={dataPath} fill={overallColor} fillOpacity="0.18" stroke={overallColor} strokeWidth="1.4" />
          {dataPts.map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r="2.5" fill={overallColor} />
          ))}
          {labelPts.map((l, i) => (
            <text key={i} x={l.x} y={l.y} fill="var(--fg-tertiary)" fontSize="8.5" fontFamily="var(--font-mono)" letterSpacing="0.08em" textAnchor={l.anchor}>{l.label}</text>
          ))}
          {/* Overall in center */}
          <text x={cx} y={cy - 4} fill="var(--fg-tertiary)" fontSize="8" fontFamily="var(--font-mono)" letterSpacing="0.12em" textAnchor="middle">OVERALL</text>
          <text x={cx} y={cy + 16} fill={overallColor} fontSize="22" fontFamily="var(--font-mono)" fontWeight="700" textAnchor="middle">{overall}</text>
        </g>
      </svg>
    </div>
  );
}

// --- Fund Focus Mode ---
function FundFocus({ fund, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const perfSeries = useMemo(() => {
    // Synthetic NAV series anchored on ret3y
    const ret = fund.ret3y;
    const vol = fund.vol;
    const n = 36;
    const hashStr = (str) => { let h = 0; for (const c of str) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h) || 1; };
    let s = hashStr(fund.id);
    const rand = () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296; };
    const out = [100];
    const drift = ret / 100 / 12;
    for (let i = 1; i < n; i++) {
      const shock = (rand() - 0.5) * vol / 100 * 0.9;
      out.push(Math.max(10, out[i - 1] * (1 + drift + shock)));
    }
    return out;
  }, [fund.id]);

  // Composite Score — 6 axes derived from fund metrics (0-100)
  const axes = useMemo(() => {
    const clamp = (v) => Math.max(0, Math.min(100, v));
    const hashStr = (str) => { let h = 0; for (const c of str) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h) || 1; };
    let s = hashStr(fund.id + "axes");
    const rand = () => { s = (s * 1664525 + 1013904223) % 4294967296; return s / 4294967296; };
    // Fee Efficiency: lower expense → higher score
    const feeEff = clamp(100 - (fund.expense / 2.5) * 100);
    // Risk Adjusted Return: Sharpe (0-2.3 typical) → 0-100
    const riskAdj = clamp((fund.sharpe / 2.3) * 100);
    // Return Consistency: based on 3Y ann. return (0-22) + noise
    const retCons = clamp((fund.ret3y / 22) * 85 + 15);
    // Information Ratio: proxy from sharpe + te — arbitrary but stable
    const infoRatio = clamp(((fund.sharpe * 40) + (10 - fund.te) * 4) + rand() * 15);
    // Drawdown Control: less negative ddMax → higher
    const ddCtrl = clamp(100 - (Math.abs(fund.ddMax) / 36) * 100);
    // Flows Momentum: synthetic from aum
    const flowsMo = clamp((fund.aum / 12) * 80 + rand() * 20);
    return [
      { k: "fee", label: "FEE EFFICIENCY", value: feeEff },
      { k: "risk", label: "RISK ADJUSTED RETURN", value: riskAdj },
      { k: "cons", label: "RETURN CONSISTENCY", value: retCons },
      { k: "info", label: "INFORMATION RATIO", value: infoRatio },
      { k: "dd", label: "DRAWDOWN CONTROL", value: ddCtrl },
      { k: "flow", label: "FLOWS MOMENTUM", value: flowsMo },
    ];
  }, [fund.id, fund.expense, fund.sharpe, fund.ret3y, fund.te, fund.ddMax, fund.aum]);

  const overall = Math.round(axes.reduce((s, a) => s + a.value, 0) / axes.length);
  const overallTone = overall >= 75 ? "up" : overall >= 55 ? "neu" : "down";

  // Peers (same strategy, sorted by sharpe)
  const peers = FUNDS
    .filter(f => f.strategy === fund.strategy && f.id !== fund.id)
    .sort((a, b) => b.sharpe - a.sharpe)
    .slice(0, 5);
  const maxSh = Math.max(fund.sharpe, ...peers.map(p => p.sharpe));

  return (
    <div className="focus-overlay" onClick={onClose}>
      <div className="focus-modal fund-focus" style={{ width: 1040, maxWidth: "94vw", height: "88vh" }} onClick={e => e.stopPropagation()}>
        <div className="focus-head">
          <div>
            <div className="title">
              {fund.name}
              {fund.elite && <span className="elite-badge" style={{ marginLeft: 10 }}>ELITE</span>}
            </div>
            <div className="sub">
              {fund.ticker} · {fund.manager} · {fund.strategy} · {fund.geo} · Inception {fund.inception}
            </div>
          </div>
          <button className="close" onClick={onClose}>ESC  CLOSE</button>
        </div>

        <div className="kpi-grid">
          <div className="kpi"><div className="l">AUM</div><div className="v">R$ {fund.aum.toFixed(1)}B</div></div>
          <div className="kpi"><div className="l">Return 1Y</div><div className={"v " + (fund.ret1y >= 0 ? "up" : "down")}>{(fund.ret1y >= 0 ? "+" : "") + fund.ret1y.toFixed(1)}%</div></div>
          <div className="kpi"><div className="l">Return 3Y (ann.)</div><div className={"v " + (fund.ret3y >= 0 ? "up" : "down")}>{(fund.ret3y >= 0 ? "+" : "") + fund.ret3y.toFixed(1)}%</div></div>
          <div className="kpi"><div className="l">Sharpe</div><div className="v">{fund.sharpe.toFixed(2)}</div></div>
          <div className="kpi"><div className="l">Vol (ann.)</div><div className="v">{fund.vol.toFixed(1)}%</div></div>
          <div className="kpi"><div className="l">Max Drawdown</div><div className="v down">{fund.ddMax.toFixed(1)}%</div></div>
        </div>

        <div className="fund-body">
          <div className="fund-section">
            <h3>Performance · Growth of 100 · 3Y rolling</h3>
            <PerfChart series={perfSeries} label={fund.ticker} />

            <h3 style={{ marginTop: 20 }}>Peer Sharpe · {fund.strategy}</h3>
            <div>
              <div className="peer-bar-row">
                <span className="lbl" style={{ color: "var(--accent)", fontWeight: 700 }}>{fund.ticker}</span>
                <span className="bar-wrap"><span className="bar self" style={{ width: (fund.sharpe / maxSh) * 100 + "%" }} /></span>
                <span className="val">{fund.sharpe.toFixed(2)}</span>
              </div>
              {peers.map(p => (
                <div key={p.id} className="peer-bar-row">
                  <span className="lbl">{p.ticker}</span>
                  <span className="bar-wrap"><span className="bar" style={{ width: (p.sharpe / maxSh) * 100 + "%" }} /></span>
                  <span className="val">{p.sharpe.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="fund-section">
            <h3>Composite Score · {overall}/100</h3>
            <CompositeRadar axes={axes} overall={overall} tone={overallTone} />
            <div className="axis-bars">
              {axes.map(a => (
                <div key={a.k} className="axis-row">
                  <div className="axis-lbl">{a.label}</div>
                  <div className="axis-bar-wrap">
                    <div className="axis-bar" style={{ width: a.value + "%" }} />
                  </div>
                  <div className="axis-val">{Math.round(a.value)}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="focus-foot">
          <button className="btn" onClick={onClose}>CANCEL</button>
          <button className="btn">OPEN DD REPORT</button>
          <button className="btn">ADD TO WATCHLIST</button>
          <button className="btn primary">ADD TO PORTFOLIO</button>
        </div>
      </div>
    </div>
  );
}

// --- Results table ---
function ResultsTable({ funds, sort, onSort, selectedId, onOpen }) {
  const sortInd = k => sort.key === k ? (sort.dir === "asc" ? " ▲" : " ▼") : "";
  const cls = k => "th " + (sort.key === k ? "sort-active" : "");
  return (
    <div className="scr-table-wrap">
      <table className="scr-table">
        <thead>
          <tr>
            <th className={cls("ticker")} onClick={() => onSort("ticker")}>TICKER{sortInd("ticker")}</th>
            <th className={cls("name")} onClick={() => onSort("name")}>NAME{sortInd("name")}</th>
            <th>UNIVERSE</th>
            <th className={cls("manager")} onClick={() => onSort("manager")}>MANAGER</th>
            <th className={cls("strategy")} onClick={() => onSort("strategy")}>STRATEGY</th>
            <th>GEO</th>
            <th className={"num " + cls("aum")} onClick={() => onSort("aum")}>AUM (Bi){sortInd("aum")}</th>
            <th className={"num " + cls("ret1y")} onClick={() => onSort("ret1y")}>1Y%{sortInd("ret1y")}</th>
            <th className={"num " + cls("ret3y")} onClick={() => onSort("ret3y")}>3Y%{sortInd("ret3y")}</th>
            <th className={"num " + cls("ret10y")} onClick={() => onSort("ret10y")}>10Y%{sortInd("ret10y")}</th>
            <th className={"num " + cls("sharpe")} onClick={() => onSort("sharpe")}>SHARPE{sortInd("sharpe")}</th>
            <th className={"num " + cls("vol")} onClick={() => onSort("vol")}>VOL%{sortInd("vol")}</th>
            <th className={"num " + cls("ddMax")} onClick={() => onSort("ddMax")}>MAX DD%{sortInd("ddMax")}</th>
            <th className={"num " + cls("expense")} onClick={() => onSort("expense")}>EXP%{sortInd("expense")}</th>
            <th className={"num " + cls("ddScore")} onClick={() => onSort("ddScore")}>SCORE{sortInd("ddScore")}</th>
          </tr>
        </thead>
        <tbody>
          {funds.map(f => (
            <tr key={f.id} className={selectedId === f.id ? "selected" : ""} onClick={() => onOpen(f)}>
              <td className="tk">{f.ticker}</td>
              <td className="name">
                {f.elite && <span className="elite-badge" style={{ marginRight: 6 }}>ELITE</span>}
                {f.name}
              </td>
              <td><span className={"universe-badge " + (f.universe === "NETZ ELITE" ? "elite" : f.universe === "RECOMMENDED" ? "recommended" : "")}>{f.universe}</span></td>
              <td className="dim">{f.manager}</td>
              <td className="dim">{f.strategy}</td>
              <td className="dim">{f.geo}</td>
              <td className="num">{f.aum.toFixed(1)}</td>
              <td className={"num " + (f.ret1y >= 0 ? "up" : "down")}>{(f.ret1y >= 0 ? "+" : "") + f.ret1y.toFixed(1)}</td>
              <td className={"num " + (f.ret3y >= 0 ? "up" : "down")}>{(f.ret3y >= 0 ? "+" : "") + f.ret3y.toFixed(1)}</td>
              <td className={"num " + (f.ret10y >= 0 ? "up" : "down")}>{(f.ret10y >= 0 ? "+" : "") + f.ret10y.toFixed(1)}</td>
              <td className="num">{f.sharpe.toFixed(2)}</td>
              <td className="num">{f.vol.toFixed(1)}</td>
              <td className="num down">{f.ddMax.toFixed(1)}</td>
              <td className="num">{f.expense.toFixed(2)}</td>
              <td className="num" style={{ color: f.ddScore > 85 ? "var(--up)" : f.ddScore > 70 ? "var(--accent)" : "var(--down)", fontWeight: 700 }}>{f.ddScore}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ScreenerApp() {
  const [settings, setSettings] = useState(() => (/*EDITMODE-BEGIN*/{
    "theme": "dark",
    "density": "compact",
    "accent": "netz"
  }/*EDITMODE-END*/));
  const [tweaksOpen, setTweaksOpen] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", settings.theme);
    document.documentElement.setAttribute("data-density", settings.density);
    document.documentElement.setAttribute("data-accent", settings.accent);
  }, [settings]);

  useEffect(() => {
    const onMsg = (e) => {
      if (!e.data) return;
      if (e.data.type === "__activate_edit_mode") setTweaksOpen(true);
      if (e.data.type === "__deactivate_edit_mode") setTweaksOpen(false);
    };
    window.addEventListener("message", onMsg);
    window.parent.postMessage({ type: "__edit_mode_available" }, "*");
    return () => window.removeEventListener("message", onMsg);
  }, []);

  const defaultFilters = {
    universes: new Set(), strategies: new Set(), geos: new Set(),
    aumMin: "", aumMax: "", ret1yMin: "", ret1yMax: "",
    sharpeMin: "", sharpeMax: "", ddMin: "", ddMax: "", expMax: "",
    eliteOnly: false,
  };
  const [filters, setFilters] = useState(defaultFilters);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState({ key: "ret1y", dir: "desc" });
  const [focus, setFocus] = useState(null);

  const toggleSort = (key) => setSort(s => s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" });

  const filtered = useMemo(() => {
    const q = search.trim().toUpperCase();
    let list = FUNDS;
    if (filters.universes.size) list = list.filter(f => filters.universes.has(f.universe));
    if (filters.strategies.size) list = list.filter(f => filters.strategies.has(f.strategy));
    if (filters.geos.size) list = list.filter(f => filters.geos.has(f.geo));
    if (filters.eliteOnly) list = list.filter(f => f.elite);
    const num = v => v === "" || v == null ? null : parseFloat(v);
    const aumMin = num(filters.aumMin), aumMax = num(filters.aumMax);
    if (aumMin != null) list = list.filter(f => f.aum >= aumMin);
    if (aumMax != null) list = list.filter(f => f.aum <= aumMax);
    const r1Min = num(filters.ret1yMin), r1Max = num(filters.ret1yMax);
    if (r1Min != null) list = list.filter(f => f.ret1y >= r1Min);
    if (r1Max != null) list = list.filter(f => f.ret1y <= r1Max);
    const shMin = num(filters.sharpeMin), shMax = num(filters.sharpeMax);
    if (shMin != null) list = list.filter(f => f.sharpe >= shMin);
    if (shMax != null) list = list.filter(f => f.sharpe <= shMax);
    const ddMin = num(filters.ddMin), ddMax = num(filters.ddMax);
    if (ddMin != null) list = list.filter(f => f.ddMax >= ddMin);
    if (ddMax != null) list = list.filter(f => f.ddMax <= ddMax);
    const expMax = num(filters.expMax);
    if (expMax != null) list = list.filter(f => f.expense <= expMax);
    if (q) list = list.filter(f => f.name.toUpperCase().includes(q) || f.ticker.includes(q) || f.manager.toUpperCase().includes(q));
    const arr = list.slice();
    arr.sort((a, b) => {
      const { key, dir } = sort;
      const av = a[key], bv = b[key];
      if (typeof av === "string") return dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return dir === "asc" ? av - bv : bv - av;
    });
    return arr;
  }, [filters, search, sort]);

  // Simplified topbar
  const tabs = [
    { l: "LIVE", href: "Netz Terminal.html" },
    { l: "SCREENER", active: true },
    { l: "MACRO", href: "Netz Terminal - Macro.html" },
    { l: "DD" }, { l: "ALERTS" },
    { l: "BUILDER", href: "Netz Terminal - Builder.html" },
  ];

  const [clock, setClock] = useState(() => new Date().toLocaleTimeString("en-US", { hour12: false }));
  useEffect(() => {
    const id = setInterval(() => setClock(new Date().toLocaleTimeString("en-US", { hour12: false })), 1000);
    return () => clearInterval(id);
  }, []);

  const eliteCount = filtered.filter(f => f.elite).length;
  const avgSharpe = filtered.length ? filtered.reduce((s, f) => s + f.sharpe, 0) / filtered.length : 0;
  const avgRet1y = filtered.length ? filtered.reduce((s, f) => s + f.ret1y, 0) / filtered.length : 0;

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-brand">
          <svg className="symbol" viewBox="0 0 40 40">
            <path d="M 4 20 L 14 6 L 20 14 L 10 28 Z" fill="#E9EEFB" />
            <path d="M 26 20 L 36 6 L 30 14 L 20 28 Z" fill="#E9EEFB" />
            <path d="M 20 14 L 26 20 L 20 26 L 14 20 Z" fill="var(--accent)"/>
          </svg>
          <span className="wm">NETZ<span className="accent">·</span>TERMINAL</span>
          <span className="mode">v0.4</span>
        </div>
        <nav className="topbar-tabs">
          {tabs.map((t, i) => (
            t.href ? (
              <a key={t.l} href={t.href} className={"topbar-tab " + (t.active ? "active" : "")} style={{ textDecoration: "none" }}>
                {t.l}<span className="kbd">F{i + 1}</span>
              </a>
            ) : (
              <button key={t.l} className={"topbar-tab " + (t.active ? "active" : "")}>
                {t.l}<span className="kbd">F{i + 1}</span>
              </button>
            )
          ))}
        </nav>
        <div className="topbar-cmd">
          <span className="prompt">&gt;</span>
          <input placeholder="VTI US <GO>" />
          <span className="hint">⌘K</span>
        </div>
        <div className="topbar-meta">
          <div className="meta-item">
            <span className="meta-label">Universe</span>
            <span className="meta-value">{FUNDS.length} funds</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">
              <span className="status-dot" />LIVE
            </span>
            <span className="meta-value">{clock}</span>
          </div>
          <button className="icon-cta" style={{ borderLeft: "1px solid var(--term-panel-edge)", height: 36, marginRight: -14 }} onClick={() => setTweaksOpen(v => !v)}>
            {tweaksOpen ? "HIDE TWEAKS" : "TWEAKS"}
          </button>
        </div>
      </header>

      <div className="scr-shell">
        <FilterRail
          filters={filters}
          setFilters={setFilters}
          resultCount={filtered.length}
          totalCount={FUNDS.length}
          onReset={() => setFilters(defaultFilters)}
        />
        <section className="scr-results">
          <div className="scr-toolbar">
            <div className="summary">
              <span className="num">{filtered.length}</span> / {FUNDS.length} funds ·
              <span style={{ color: "var(--accent)", fontWeight: 700 }}> {eliteCount}</span> elite ·
              avg 1Y <span className={avgRet1y >= 0 ? "up" : "down"} style={{ color: avgRet1y >= 0 ? "var(--up)" : "var(--down)" }}>{(avgRet1y >= 0 ? "+" : "") + avgRet1y.toFixed(1)}%</span> ·
              avg Sharpe <span style={{ color: "var(--fg-primary)" }}>{avgSharpe.toFixed(2)}</span>
            </div>
            <div className="search">
              <span className="prompt">⌕</span>
              <input placeholder="search fund / ticker / manager" value={search} onChange={e => setSearch(e.target.value)} />
            </div>
            <button className="icon-cta" style={{ border: "1px solid var(--term-panel-edge)", height: 22, borderRadius: 2 }}>EXPORT CSV</button>
            <button className="icon-cta primary" style={{ border: "1px solid var(--accent)", height: 22, borderRadius: 2 }}>+ COMPARE</button>
          </div>
          <ResultsTable funds={filtered} sort={sort} onSort={toggleSort} selectedId={focus?.id} onOpen={f => setFocus(f)} />
        </section>
      </div>

      <footer className="statusbar">
        <span>✓ Connected · {FUNDS.length} funds indexed · filters {Object.values(filters).filter(v => v instanceof Set ? v.size : v).length} active</span>
        <span className="sb-spacer" />
        <span className="sb-hint"><span className="kbd">/</span><span>Search</span></span>
        <span className="sb-hint"><span className="kbd">Enter</span><span>Open</span></span>
        <span className="sb-hint"><span className="kbd">C</span><span>Compare</span></span>
        <span className="sb-hint"><span className="kbd">Esc</span><span>Close</span></span>
      </footer>

      {tweaksOpen && (
        <div className="tweaks">
          <div className="tweaks-head">
            <span className="title">⟐ Tweaks</span>
            <button className="close" onClick={() => setTweaksOpen(false)}>×</button>
          </div>
          <div className="tweaks-body">
            <div className="tweak-field">
              <span className="label">Theme</span>
              <div className="tweak-seg">
                {["dark", "light"].map(o => (
                  <button key={o} className={settings.theme === o ? "active" : ""} onClick={() => {
                    const next = { ...settings, theme: o };
                    setSettings(next);
                    window.parent.postMessage({ type: "__edit_mode_set_keys", edits: next }, "*");
                  }}>{o}</button>
                ))}
              </div>
            </div>
            <div className="tweak-field">
              <span className="label">Density</span>
              <div className="tweak-seg">
                {["compact", "comfy"].map(o => (
                  <button key={o} className={settings.density === o ? "active" : ""} onClick={() => {
                    const next = { ...settings, density: o };
                    setSettings(next);
                    window.parent.postMessage({ type: "__edit_mode_set_keys", edits: next }, "*");
                  }}>{o}</button>
                ))}
              </div>
            </div>
            <div className="tweak-field">
              <span className="label">Accent</span>
              <div className="tweak-seg">
                {[{ v: "netz", l: "Netz" }, { v: "amber", l: "Amber" }, { v: "bloomberg", l: "BBG" }].map(o => (
                  <button key={o.v} className={settings.accent === o.v ? "active" : ""} onClick={() => {
                    const next = { ...settings, accent: o.v };
                    setSettings(next);
                    window.parent.postMessage({ type: "__edit_mode_set_keys", edits: next }, "*");
                  }}>{o.l}</button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {focus && <FundFocus fund={focus} onClose={() => setFocus(null)} />}
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<ScreenerApp />);
