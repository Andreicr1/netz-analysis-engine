// Macro page — Regime matrix + cross-asset dashboard
const { useState, useMemo, useEffect, useRef } = React;

// --- Sparkline ---
function Spark({ series, width = 80, height = 28, color }) {
  const min = Math.min(...series), max = Math.max(...series);
  const rng = max - min || 1;
  const xOf = i => (i / (series.length - 1)) * width;
  const yOf = v => height - ((v - min) / rng) * height;
  const pts = series.map((v, i) => `${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`).join(" ");
  const up = series[series.length - 1] >= series[0];
  const c = color || (up ? "var(--up)" : "var(--down)");
  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", height }}>
      <polyline points={pts} fill="none" stroke={c} strokeWidth="1.2" />
    </svg>
  );
}

// --- Regime matrix (interactive draggable pin) ---
function RegimeMatrix({ pin, onPinChange }) {
  const size = 360;
  const pad = 30;
  const plot = size - pad * 2;
  const ref = useRef(null);
  const [dragging, setDragging] = useState(false);

  const toPx = (g, i) => ({
    x: pad + ((g + 1) / 2) * plot,
    y: pad + ((1 - (i + 1) / 2)) * plot,
  });

  const onMouseMove = (e) => {
    if (!dragging || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const scaleX = size / rect.width;
    const px = (e.clientX - rect.left) * scaleX;
    const py = (e.clientY - rect.top) * scaleX;
    const g = Math.max(-1, Math.min(1, ((px - pad) / plot) * 2 - 1));
    const i = Math.max(-1, Math.min(1, 1 - ((py - pad) / plot) * 2));
    onPinChange({ g, i });
  };

  useEffect(() => {
    const up = () => setDragging(false);
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);

  const quadColor = (g, i) => {
    if (g >= 0 && i < 0) return "var(--up)";       // Goldilocks
    if (g >= 0 && i >= 0) return "var(--accent)";  // Overheating
    if (g < 0 && i >= 0) return "var(--down)";     // Stagflation
    return "#6689BC";                               // Reflation
  };

  const trailPx = REGIME_TRAIL.map(p => ({ ...toPx(p.g, p.i), m: p.m, label: p.label }));
  const pinPx = toPx(pin.g, pin.i);
  const pinColor = quadColor(pin.g, pin.i);

  return (
    <svg
      ref={ref}
      viewBox={`0 0 ${size} ${size}`}
      style={{ width: "100%", height: "100%", display: "block", cursor: dragging ? "grabbing" : "default" }}
      onMouseMove={onMouseMove}
    >
      {/* Quadrant fills */}
      <rect x={pad} y={pad} width={plot / 2} height={plot / 2} fill="rgba(255,92,122,0.06)" />
      <rect x={pad + plot / 2} y={pad} width={plot / 2} height={plot / 2} fill="rgba(255,150,90,0.06)" />
      <rect x={pad} y={pad + plot / 2} width={plot / 2} height={plot / 2} fill="rgba(102,137,188,0.06)" />
      <rect x={pad + plot / 2} y={pad + plot / 2} width={plot / 2} height={plot / 2} fill="rgba(61,211,154,0.06)" />

      {/* Grid lines */}
      {[0, 0.25, 0.5, 0.75, 1].map(f => (
        <g key={f}>
          <line x1={pad + f * plot} y1={pad} x2={pad + f * plot} y2={pad + plot} stroke="rgba(102,137,188,0.1)" strokeDasharray="2 3" />
          <line x1={pad} y1={pad + f * plot} x2={pad + plot} y2={pad + f * plot} stroke="rgba(102,137,188,0.1)" strokeDasharray="2 3" />
        </g>
      ))}
      {/* Center axes */}
      <line x1={pad + plot / 2} y1={pad} x2={pad + plot / 2} y2={pad + plot} stroke="rgba(102,137,188,0.35)" />
      <line x1={pad} y1={pad + plot / 2} x2={pad + plot} y2={pad + plot / 2} stroke="rgba(102,137,188,0.35)" />

      {/* Quadrant labels */}
      <text x={pad + plot * 0.75} y={pad + 14} textAnchor="middle" fill="var(--accent)" fontSize="10" fontFamily="var(--font-mono)" letterSpacing="0.12em" fontWeight="700">OVERHEATING</text>
      <text x={pad + plot * 0.25} y={pad + 14} textAnchor="middle" fill="var(--down)" fontSize="10" fontFamily="var(--font-mono)" letterSpacing="0.12em" fontWeight="700">STAGFLATION</text>
      <text x={pad + plot * 0.75} y={pad + plot - 6} textAnchor="middle" fill="var(--up)" fontSize="10" fontFamily="var(--font-mono)" letterSpacing="0.12em" fontWeight="700">GOLDILOCKS</text>
      <text x={pad + plot * 0.25} y={pad + plot - 6} textAnchor="middle" fill="#6689BC" fontSize="10" fontFamily="var(--font-mono)" letterSpacing="0.12em" fontWeight="700">REFLATION</text>

      {/* Axis labels */}
      <text x={pad - 6} y={pad + plot / 2 - 8} textAnchor="end" fill="var(--fg-tertiary)" fontSize="9" fontFamily="var(--font-mono)" letterSpacing="0.1em">INFLATION ↑</text>
      <text x={pad - 6} y={pad + plot / 2 + 14} textAnchor="end" fill="var(--fg-tertiary)" fontSize="9" fontFamily="var(--font-mono)" letterSpacing="0.1em">DISINFL ↓</text>
      <text x={pad + plot / 2 + 8} y={pad + plot + 18} fill="var(--fg-tertiary)" fontSize="9" fontFamily="var(--font-mono)" letterSpacing="0.1em">GROWTH →</text>
      <text x={pad + plot / 2 - 8} y={pad + plot + 18} textAnchor="end" fill="var(--fg-tertiary)" fontSize="9" fontFamily="var(--font-mono)" letterSpacing="0.1em">← CONTRACTION</text>

      {/* Trail line */}
      <polyline points={trailPx.map(p => `${p.x},${p.y}`).join(" ")} fill="none" stroke="var(--fg-muted)" strokeWidth="1" strokeDasharray="3 2" opacity="0.8" />

      {/* Trail dots */}
      {trailPx.map((p, i) => (
        <g key={i}>
          <circle cx={p.x} cy={p.y} r="3" fill="var(--fg-muted)" opacity={0.4 + (i / trailPx.length) * 0.5} />
          {i === 0 && <text x={p.x + 8} y={p.y - 4} fill="var(--fg-tertiary)" fontSize="8" fontFamily="var(--font-mono)">{p.m}</text>}
        </g>
      ))}

      {/* Current pin */}
      <circle cx={pinPx.x} cy={pinPx.y} r="10" fill={pinColor} opacity="0.2" />
      <circle
        cx={pinPx.x}
        cy={pinPx.y}
        r="6"
        fill={pinColor}
        stroke="var(--term-void)"
        strokeWidth="2"
        style={{ cursor: "grab" }}
        onMouseDown={(e) => { e.preventDefault(); setDragging(true); }}
      />
      <text x={pinPx.x + 10} y={pinPx.y + 4} fill="var(--fg-primary)" fontSize="10" fontFamily="var(--font-mono)" fontWeight="700">NOW</text>
    </svg>
  );
}

// --- Full chart (for drawer) ---
function FullChart({ seriesList, labels, compareTicker }) {
  const w = 680, h = 260, padL = 40, padR = 20, padT = 10, padB = 22;
  // Normalize each series to start at 100
  const norm = seriesList.map(s => s.map(v => (v / s[0]) * 100));
  const all = norm.flat();
  const min = Math.min(...all), max = Math.max(...all);
  const rng = max - min || 1;
  const n = norm[0].length;
  const xOf = i => padL + (i / (n - 1)) * (w - padL - padR);
  const yOf = v => padT + (h - padT - padB) - ((v - min) / rng) * (h - padT - padB);
  const colors = ["var(--accent)", "var(--up)", "#6689BC", "var(--down)", "#FFC24A"];
  const ticks = 4;
  const tvals = Array.from({ length: ticks }, (_, i) => min + (rng * i) / (ticks - 1));

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "100%" }}>
      {tvals.map((v, i) => (
        <g key={i}>
          <line x1={padL} x2={w - padR} y1={yOf(v)} y2={yOf(v)} stroke="rgba(102,137,188,0.1)" strokeDasharray="2 3" />
          <text x={padL - 4} y={yOf(v) + 3} fill="var(--fg-tertiary)" fontSize="9" fontFamily="var(--font-mono)" textAnchor="end">{v.toFixed(0)}</text>
        </g>
      ))}
      {norm.map((s, si) => {
        const pts = s.map((v, i) => `${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`).join(" ");
        return <polyline key={si} points={pts} fill="none" stroke={colors[si % colors.length]} strokeWidth={si === 0 ? 1.8 : 1.2} />;
      })}
      {/* legend */}
      {labels.map((l, i) => (
        <g key={l} transform={`translate(${padL + i * 120} ${padT - 2})`}>
          <rect width="10" height="2" y="6" fill={colors[i % colors.length]} />
          <text x="14" y="10" fill={colors[i % colors.length]} fontSize="10" fontFamily="var(--font-mono)" fontWeight="700" letterSpacing="0.04em">{l}</text>
        </g>
      ))}
    </svg>
  );
}

// --- Mini card ---
function MiniCard({ asset, selected, compared, onOpen, onToggleCompare, compareMode }) {
  const chg = asset.chg1m;
  return (
    <div className={"mini-card " + (selected ? "selected" : "")} onClick={() => onOpen(asset)}>
      <div className="mc-head">
        <div className="mc-tk">
          {compareMode && (
            <input
              type="checkbox"
              checked={compared}
              onClick={e => e.stopPropagation()}
              onChange={e => { e.stopPropagation(); onToggleCompare(asset); }}
            />
          )}
          {asset.ticker}
        </div>
        <div className="mc-name">{asset.name}</div>
      </div>
      <div className="mc-chart">
        <Spark series={asset.series.slice(-24)} />
      </div>
      <div className="mc-nums">
        <div className="mc-last">{asset.last.toLocaleString("en-US", { maximumFractionDigits: 2 })}</div>
        <div className={"mc-chg " + (chg >= 0 ? "up" : "down")}>
          {(chg >= 0 ? "+" : "") + chg.toFixed(2)}% 1M
        </div>
      </div>
    </div>
  );
}

// --- Asset drawer ---
function AssetDrawer({ asset, compareAssets, onClose, onRemoveCompare, timeframe }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const all = [asset, ...compareAssets.filter(a => a.ticker !== asset.ticker)];
  const chg = asset.chg1d;

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer" onClick={e => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <div className="title">{asset.name}</div>
            <div className="sub">
              <span>{asset.ticker}</span>
              <span>{asset.sector}</span>
              <span>{asset.region}</span>
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div className="last">{asset.last.toLocaleString("en-US", { maximumFractionDigits: 2 })}</div>
            <div className={"chg " + (chg >= 0 ? "up" : "down")}>
              {(chg >= 0 ? "+" : "") + chg.toFixed(2)}% 1D
            </div>
          </div>
        </div>
        <div className="drawer-body">
          <div className="drawer-chart">
            <FullChart
              seriesList={all.map(a => a.series)}
              labels={all.map(a => a.ticker)}
              compareTicker={asset.ticker}
            />
          </div>
          <div className="drawer-stats">
            <div className="cell"><div className="l">1W</div><div className={"v " + (asset.chg1w >= 0 ? "up" : "down")}>{(asset.chg1w >= 0 ? "+" : "") + asset.chg1w.toFixed(2)}%</div></div>
            <div className="cell"><div className="l">1M</div><div className={"v " + (asset.chg1m >= 0 ? "up" : "down")}>{(asset.chg1m >= 0 ? "+" : "") + asset.chg1m.toFixed(2)}%</div></div>
            <div className="cell"><div className="l">3M</div><div className={"v " + (asset.chg3m >= 0 ? "up" : "down")}>{(asset.chg3m >= 0 ? "+" : "") + asset.chg3m.toFixed(1)}%</div></div>
            <div className="cell"><div className="l">YTD</div><div className={"v " + (asset.chgYTD >= 0 ? "up" : "down")}>{(asset.chgYTD >= 0 ? "+" : "") + asset.chgYTD.toFixed(1)}%</div></div>
            <div className="cell"><div className="l">1Y</div><div className={"v " + (asset.chg1y >= 0 ? "up" : "down")}>{(asset.chg1y >= 0 ? "+" : "") + asset.chg1y.toFixed(1)}%</div></div>
            <div className="cell"><div className="l">5Y</div><div className={"v " + (asset.chg5y >= 0 ? "up" : "down")}>{(asset.chg5y >= 0 ? "+" : "") + asset.chg5y.toFixed(1)}%</div></div>
            <div className="cell"><div className="l">52W High</div><div className="v">{(asset.last * 1.12).toFixed(2)}</div></div>
            <div className="cell"><div className="l">52W Low</div><div className="v">{(asset.last * 0.86).toFixed(2)}</div></div>
          </div>
          {compareAssets.length > 0 && (
            <div className="drawer-section">
              <h4>Compare · {compareAssets.length} asset{compareAssets.length > 1 ? "s" : ""}</h4>
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                {compareAssets.map(c => (
                  <span key={c.ticker} className="cchip" onClick={() => onRemoveCompare(c)}>{c.ticker} ×</span>
                ))}
              </div>
            </div>
          )}
          <div className="drawer-section">
            <h4>Macro Notes</h4>
            <div style={{ fontSize: 11, color: "var(--fg-secondary)", fontFamily: "var(--font-mono)", lineHeight: 1.5 }}>
              <div>· Regime sensitivity: {asset.sector === "RATES" ? "HIGH to inflation shocks" : asset.sector === "EQUITY" ? "MEDIUM to growth shocks" : asset.sector === "COMMODITY" ? "HIGH to geopolitical shocks" : "MEDIUM"}</div>
              <div>· Current quadrant exposure: <span style={{ color: "var(--accent)" }}>OVERHEATING</span> — typically {asset.sector === "RATES" ? "bearish (yields up)" : asset.sector === "EQUITY" ? "mixed, cyclicals outperform" : "supportive commodities, USD firm"}</div>
              <div>· 60-day correlation with DXY: {(Math.random() * 0.8 - 0.4).toFixed(2)}</div>
            </div>
          </div>
        </div>
        <div className="drawer-foot">
          <button className="btn" onClick={onClose}>CLOSE</button>
          <button className="btn">CREATE ALERT</button>
          <button className="btn primary">ADD TO WATCHLIST</button>
        </div>
      </div>
    </div>
  );
}

// --- Liquidity panel ---
function LiquidityPanel() {
  const pct = ((LIQUIDITY_NOW + 1) / 2) * 100;
  return (
    <div>
      <h3>Global Liquidity · G4 CB Balance Δ</h3>
      <div className="liq-gauge">
        <div className="track" />
        <div className="labels">
          <span>TIGHT</span><span>NEUTRAL</span><span>LOOSE</span>
        </div>
        <div className="needle" style={{ left: pct + "%" }} />
      </div>
      <div className="liq-spark">
        <Spark series={LIQUIDITY_HISTORY} color="var(--accent)" height={36} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--fg-tertiary)", marginTop: 2 }}>
        <span>24M trail</span>
        <span>Current: <span style={{ color: "var(--accent)", fontWeight: 700 }}>{LIQUIDITY_NOW >= 0 ? "+" : ""}{LIQUIDITY_NOW.toFixed(2)}σ</span></span>
      </div>
    </div>
  );
}

// --- Sentiment panel ---
function SentimentPanel({ assets, onOpen }) {
  return (
    <div>
      <h3>Sentiment & Positioning</h3>
      <div className="sent-grid">
        {assets.map(a => (
          <div key={a.ticker} className="sent-tile" onClick={() => onOpen(a)}>
            <div>
              <div className="t-name">{a.ticker}</div>
              <div className="t-val">{a.last.toFixed(a.last < 10 ? 2 : 0)}</div>
              <div className={"t-chg " + (a.chg1w >= 0 ? "up" : "down")}>{(a.chg1w >= 0 ? "+" : "") + a.chg1w.toFixed(2)}% 1W</div>
            </div>
            <div className="t-spark">
              <Spark series={a.series.slice(-24)} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Econ panel ---
function EconPanel() {
  return (
    <div>
      <h3>Economic Pulse · Recent Releases</h3>
      <div className="econ-list">
        {ECON_PULSES.map((p, i) => (
          <div key={i} className="econ-row">
            <div>
              <div className="ename">{p.name}</div>
              <div className="eperiod">{p.period}</div>
            </div>
            <div className="eperiod" style={{ textAlign: "right" }}>ACT</div>
            <div className={"eact " + (p.surprise === "hot" ? "up" : "down")}>{p.actual}{p.unit}</div>
            <div className="econs">{p.consensus}{p.unit}</div>
            <div className={"esur " + p.surprise}>{p.surprise === "hot" ? "▲" : "▼"}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- CB calendar ---
function CBPanel() {
  return (
    <div>
      <h3>Central Bank Calendar · Next 30 Days</h3>
      <div className="cb-list">
        {CB_CALENDAR.map((c, i) => (
          <div key={i} className="cb-row">
            <div className="cb-name">{c.cb}</div>
            <div className="cb-date">{c.date}</div>
            <div className="cb-rate">
              {c.currentRate}
              <span className="arrow">→</span>
              {c.mktImplied}
              <span style={{ color: "var(--fg-muted)", fontSize: 9, marginLeft: 8 }}>· {c.prob}% priced</span>
            </div>
            <div className={"cb-chg " + (c.change.includes("−") ? "cut" : c.change === "HOLD" ? "hold" : "hike")}>{c.change}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MacroApp() {
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

  const [region, setRegion] = useState("GLOBAL");
  const [timeframe, setTimeframe] = useState("5Y");
  const [pin, setPin] = useState({ g: CURRENT_REGIME.g, i: CURRENT_REGIME.i });
  const [focusAsset, setFocusAsset] = useState(null);
  const [compareMode, setCompareMode] = useState(false);
  const [compared, setCompared] = useState([]);

  const filtered = useMemo(() => {
    if (region === "GLOBAL") return MACRO_ASSETS;
    return MACRO_ASSETS.filter(a => a.region === region || a.region === "GLOBAL");
  }, [region]);

  const bySector = useMemo(() => {
    const out = {};
    for (const a of filtered) {
      if (!out[a.sector]) out[a.sector] = [];
      out[a.sector].push(a);
    }
    return out;
  }, [filtered]);

  const sentimentAssets = filtered.filter(a => a.sector === "SENTIMENT");

  const [clock, setClock] = useState(() => new Date().toLocaleTimeString("en-US", { hour12: false }));
  useEffect(() => {
    const id = setInterval(() => setClock(new Date().toLocaleTimeString("en-US", { hour12: false })), 1000);
    return () => clearInterval(id);
  }, []);

  const tabs = [
    { l: "LIVE", href: "Netz Terminal.html" },
    { l: "SCREENER", href: "Netz Terminal — Screener.html" },
    { l: "MACRO", active: true },
    { l: "DD" }, { l: "ALERTS" },
    { l: "BUILDER", href: "Netz Terminal - Builder.html" },
  ];

  const quadrantLabel = (() => {
    const g = pin.g, i = pin.i;
    if (g >= 0 && i < 0) return "Goldilocks";
    if (g >= 0 && i >= 0) return "Overheating";
    if (g < 0 && i >= 0) return "Stagflation";
    return "Reflation";
  })();

  const toggleCompare = (asset) => {
    setCompared(prev => {
      const exists = prev.find(a => a.ticker === asset.ticker);
      if (exists) return prev.filter(a => a.ticker !== asset.ticker);
      if (prev.length >= 4) return prev;
      return [...prev, asset];
    });
  };

  const openAsset = (a) => {
    setFocusAsset(a);
  };

  // Filter news: show all (could be filtered by region but for now show all macro)
  const newsFiltered = MACRO_NEWS;

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
          <input placeholder="US10Y <GO>" />
          <span className="hint">⌘K</span>
        </div>
        <div className="topbar-meta">
          <div className="meta-item">
            <span className="meta-label">Regime</span>
            <span className="meta-value" style={{ color: "var(--accent)" }}>{quadrantLabel.toUpperCase()}</span>
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

      <div className="macro-shell">
        <div className="macro-toolbar">
          <div className="group">
            <span className="l">Region</span>
            <div className="seg">
              {["GLOBAL", "US", "EU", "ASIA", "BR"].map(r => (
                <button key={r} className={region === r ? "on" : ""} onClick={() => setRegion(r)}>{r}</button>
              ))}
            </div>
          </div>
          <div className="group">
            <span className="l">Window</span>
            <div className="seg">
              {["1W", "1M", "3M", "YTD", "1Y", "5Y"].map(t => (
                <button key={t} className={timeframe === t ? "on" : ""} onClick={() => setTimeframe(t)}>{t}</button>
              ))}
            </div>
          </div>
          <span className="macro-pill">REGIME · {quadrantLabel.toUpperCase()}</span>
          <span className="macro-pill" style={{ color: "var(--up)", borderColor: "var(--up-dim)", background: "rgba(61,211,154,0.08)" }}>
            LIQ · {LIQUIDITY_NOW >= 0 ? "EASING" : "TIGHT"}
          </span>
          <span style={{ flex: 1 }} />
          <button className={"icon-cta " + (compareMode ? "primary" : "")} style={{ border: compareMode ? "1px solid var(--accent)" : "1px solid var(--term-panel-edge)", height: 22, borderRadius: 2, fontSize: 10 }} onClick={() => { setCompareMode(v => !v); if (compareMode) setCompared([]); }}>
            {compareMode ? "EXIT COMPARE" : "+ COMPARE"}
          </button>
          {compareMode && compared.length > 0 && (
            <button className="icon-cta" style={{ border: "1px solid var(--accent)", height: 22, borderRadius: 2, fontSize: 10, background: "var(--accent)", color: "var(--term-void)", fontWeight: 700 }} onClick={() => setFocusAsset(compared[0])}>
              OPEN CHART ({compared.length})
            </button>
          )}
        </div>

        <div className="macro-grid">
          {/* Left — cross-asset */}
          <div className="macro-col">
            <div className="panel-list">
              {["RATES", "FX", "EQUITY", "COMMODITY", "CREDIT"].map(sec => (
                bySector[sec] && bySector[sec].length > 0 && (
                  <div key={sec}>
                    <div className="sec-hd">
                      <span>{sec}</span>
                      <span className="count">{bySector[sec].length}</span>
                    </div>
                    {bySector[sec].map(a => (
                      <MiniCard
                        key={a.ticker}
                        asset={a}
                        selected={focusAsset?.ticker === a.ticker}
                        compared={compared.some(c => c.ticker === a.ticker)}
                        onOpen={openAsset}
                        onToggleCompare={toggleCompare}
                        compareMode={compareMode}
                      />
                    ))}
                  </div>
                )
              ))}
            </div>
          </div>

          {/* Center — regime + factors */}
          <div className="macro-center">
            <div className="macro-center-top">
              <div className="regime-panel">
                <h3>
                  <span>Regime Matrix · Growth × Inflation</span>
                  <span className="curr">{quadrantLabel.toUpperCase()}</span>
                </h3>
                <div className="regime-chart">
                  <RegimeMatrix pin={pin} onPinChange={setPin} />
                </div>
                <div className="regime-legend">
                  <span className="tag"><span className="dot" style={{ background: "var(--up)" }} />Goldilocks</span>
                  <span className="tag"><span className="dot" style={{ background: "var(--accent)" }} />Overheating</span>
                  <span className="tag"><span className="dot" style={{ background: "var(--down)" }} />Stagflation</span>
                  <span className="tag"><span className="dot" style={{ background: "#6689BC" }} />Reflation</span>
                  <span style={{ flex: 1 }} />
                  <span className="tag" style={{ color: "var(--fg-muted)" }}>── 18M trail · drag pin</span>
                </div>
              </div>
              <div className="factor-panel">
                <LiquidityPanel />
                <SentimentPanel assets={sentimentAssets.length ? sentimentAssets : MACRO_ASSETS.filter(a => a.sector === "SENTIMENT")} onOpen={openAsset} />
              </div>
            </div>
            <div className="macro-center-top">
              <div className="factor-panel">
                <CBPanel />
              </div>
              <div className="factor-panel">
                <EconPanel />
              </div>
            </div>
          </div>

          {/* Right — news */}
          <div className="macro-col">
            <div className="phead">
              <div><span className="title">Macro News</span><span className="badge" style={{ marginLeft: 6 }}>LIVE</span></div>
              <div className="actions"><button className="icon-btn" title="Filter">⚑</button></div>
            </div>
            <div className="news-feed">
              {newsFiltered.map(n => (
                <div key={n.id} className="news-item" onClick={() => {
                  const t = MACRO_ASSETS.find(a => a.ticker === n.tickers[0]);
                  if (t) openAsset(t);
                }}>
                  <div className="nh">
                    <span className="src">{n.src}</span>
                    <span className="time">{n.time}</span>
                    <span className="tag">{n.tag}</span>
                  </div>
                  <div className="ntitle">{n.title}</div>
                  {n.tickers.length > 0 && (
                    <div className="ntickers">
                      {n.tickers.map(t => <span key={t} className="chip">{t}</span>)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <footer className="statusbar">
        <span>✓ Connected · {MACRO_ASSETS.length} instruments · regime <span style={{ color: "var(--accent)", fontWeight: 700 }}>{quadrantLabel.toUpperCase()}</span> · liquidity {LIQUIDITY_NOW >= 0 ? "easing" : "tight"}</span>
        <span className="sb-spacer" />
        <span className="sb-hint"><span className="kbd">R</span><span>Region</span></span>
        <span className="sb-hint"><span className="kbd">T</span><span>Timeframe</span></span>
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

      {focusAsset && (
        <AssetDrawer
          asset={focusAsset}
          compareAssets={compared.filter(c => c.ticker !== focusAsset.ticker)}
          onClose={() => setFocusAsset(null)}
          onRemoveCompare={(a) => setCompared(prev => prev.filter(x => x.ticker !== a.ticker))}
          timeframe={timeframe}
        />
      )}
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<MacroApp />);
