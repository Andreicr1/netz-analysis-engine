// Panel components for Netz Terminal

const { useState, useEffect, useRef, useMemo } = React;

// ---------- TopBar ----------
function TopBar({ portfolios, selected, onSelectPortfolio, clock, totalAumFormatted, dayReturnPct, onOpenTweaks, tweaksOn, dataStatus }) {
  const [cmdOpen, setCmdOpen] = useState(false);
  const [q, setQ] = useState("");
  const inputRef = useRef(null);

  useEffect(() => {
    const onKey = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setCmdOpen(true);
        setTimeout(() => inputRef.current?.focus(), 10);
      } else if (e.key === "Escape") {
        setCmdOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const tabs = [
    { l: "LIVE", active: true },
    { l: "SCREENER", href: "Netz Terminal - Screener.html" },
    { l: "MACRO", href: "Netz Terminal - Macro.html" },
    { l: "DD" }, { l: "ALERTS" },
    { l: "BUILDER", href: "Netz Terminal - Builder.html" },
  ];

  return (
    <header className="topbar">
      <div className="topbar-brand">
        <svg className="symbol" viewBox="0 0 40 40">
          <path d="M 4 20 L 14 6 L 20 14 L 10 28 Z" fill="#E9EEFB" />
          <path d="M 26 20 L 36 6 L 30 14 L 20 28 Z" fill="#E9EEFB" transform="translate(0,0)"/>
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
        <input
          ref={inputRef}
          placeholder={cmdOpen ? "Type a command: PORT / TICKER / HELP" : "VTI US <GO>"}
          value={q}
          onFocus={() => setCmdOpen(true)}
          onChange={e => setQ(e.target.value)}
        />
        <span className="hint">⌘K</span>
      </div>

      <div className="topbar-meta">
        <div className="meta-item">
          <span className="meta-label">Portfolio AUM</span>
          <span className="meta-value">{totalAumFormatted}</span>
        </div>
        <div className="meta-item">
          <span className="meta-label">Day P/L</span>
          <span className={"meta-value " + (dayReturnPct >= 0 ? "up" : "down")}>
            {(dayReturnPct >= 0 ? "+" : "") + dayReturnPct.toFixed(2)}%
          </span>
        </div>
        <div className="meta-item">
          <span className="meta-label">
            <span className={"status-dot " + (dataStatus === "live" ? "" : dataStatus === "delayed" ? "delayed" : "off")} />
            {dataStatus === "live" ? "LIVE NYSE" : dataStatus === "delayed" ? "DELAYED" : "OFFLINE"}
          </span>
          <span className="meta-value">{clock}</span>
        </div>
        <button
          className="icon-cta"
          style={{ borderLeft: "1px solid var(--term-panel-edge)", height: 36, marginRight: -14 }}
          onClick={onOpenTweaks}
        >
          {tweaksOn ? "HIDE TWEAKS" : "TWEAKS"}
        </button>
      </div>
    </header>
  );
}

// ---------- StatusBar ----------
function StatusBar({ message, keyHints }) {
  return (
    <footer className="statusbar">
      <span>{message}</span>
      <span className="sb-spacer" />
      {keyHints.map((h, i) => (
        <span key={i} className="sb-hint">
          <span className="kbd">{h.k}</span>
          <span>{h.l}</span>
        </span>
      ))}
    </footer>
  );
}

// ---------- PortfolioSelector ----------
function PortfolioSelector({ portfolios, selected, onSelect }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="psel">
      <button className="psel-btn" onClick={() => setOpen(!open)}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {selected ? selected.display_name : "Select"}
        </span>
        <span className="chev">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="psel-menu">
          {portfolios.map(p => (
            <div
              key={p.id}
              className={"psel-item " + (p.id === selected?.id ? "active" : "")}
              onClick={() => { onSelect(p); setOpen(false); }}
            >
              <span className="name">{p.display_name}</span>
              <span className="profile">{p.profile}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- Watchlist ----------
function Watchlist({ items, selectedTicker, onSelect, prices, flashMap }) {
  return (
    <div className="panel">
      <div className="phead">
        <div>
          <span className="title">Watchlist</span>
          <span className="counter">{items.length}</span>
        </div>
        <div className="actions">
          <button className="icon-btn" title="Add ticker">+</button>
          <button className="icon-btn" title="Sort">⇅</button>
        </div>
      </div>
      <div className="wl-header">
        <span>TICKER</span>
        <span>NAME</span>
        <span style={{ textAlign: "right" }}>LAST</span>
        <span style={{ textAlign: "right" }}>CHG%</span>
      </div>
      <div className="pbody">
        {items.map(it => {
          const price = prices[it.ticker] ?? it.price;
          const flash = flashMap[it.ticker];
          const chg = it.dayPct;
          return (
            <div
              key={it.ticker}
              className={"wl-row " + (selectedTicker === it.ticker ? "selected " : "") + (flash === "up" ? "flash-up" : flash === "down" ? "flash-down" : "")}
              onClick={() => onSelect(it.ticker)}
            >
              <span className="tk">{it.ticker}</span>
              <span className="nm">{it.name}</span>
              <span className="px">{price.toFixed(2)}</span>
              <span className={"chg " + (chg >= 0 ? "up" : "down")}>
                {(chg >= 0 ? "+" : "") + chg.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------- AlertStream ----------
function AlertStream({ alerts, onAck }) {
  const critical = alerts.filter(a => a.severity === "critical").length;
  return (
    <div className="panel">
      <div className="phead">
        <div>
          <span className="title">Alerts</span>
          <span className="counter">{alerts.length}</span>
          {critical > 0 && <span style={{ marginLeft: 8, color: "var(--down)", fontWeight: 700 }}>· {critical} CRIT</span>}
        </div>
        <div className="actions">
          <button className="icon-btn">⌕</button>
        </div>
      </div>
      <div className="pbody">
        {alerts.map(a => (
          <div key={a.id} className={"alert-row " + a.severity} onClick={() => onAck(a.id)}>
            <span className="sev-bar" />
            <span className="src">{a.source}</span>
            <span className="title">{a.title}</span>
            <span className="tm">{a.time}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- TradeLog ----------
function TradeLog({ trades }) {
  return (
    <div className="panel">
      <div className="phead">
        <div>
          <span className="title">Trade Log</span>
          <span className="counter">{trades.length}</span>
        </div>
      </div>
      <div className="pbody">
        {trades.map(t => (
          <div key={t.id} className="trade-row">
            <span className={"side " + t.side}>{t.side}</span>
            <span className="tk">{t.ticker}</span>
            <span className="qty">{t.qty.toLocaleString()}</span>
            <span className="px">{t.price.toFixed(2)}</span>
            <span className="tm">{t.time.slice(0, 5)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- PortfolioSummary ----------
function Summary({ portfolio, aum, dayPct, instrumentCount, driftStatus, lastRebal, onRebalance }) {
  const driftPill = driftStatus === "aligned"
    ? <span className="pill ok dot">Aligned</span>
    : driftStatus === "watch"
    ? <span className="pill warn dot">Watch</span>
    : <span className="pill alert dot">Breach</span>;
  return (
    <div className="summary">
      <div className="phead">
        <span className="title">Portfolio</span>
        <span className="pill">{portfolio?.profile ?? "—"}</span>
      </div>
      <div className="summary-body">
        <div className="sum-row">
          <span className="lbl">AUM</span>
          <span className="val big">${(aum / 1e6).toFixed(2)}M</span>
        </div>
        <div className="sum-row">
          <span className="lbl">Day P/L</span>
          <span className={"val " + (dayPct >= 0 ? "up" : "down")}>
            {(dayPct >= 0 ? "+" : "") + dayPct.toFixed(2)}%
          </span>
        </div>
        <div className="sum-row">
          <span className="lbl">Holdings</span>
          <span className="val">{instrumentCount}</span>
        </div>
        <div className="sum-row">
          <span className="lbl">Drift</span>
          <span className="val">{driftPill}</span>
        </div>
        <div className="sum-row">
          <span className="lbl">Last Rebal.</span>
          <span className="val" style={{ fontSize: 11 }}>{lastRebal}</span>
        </div>
      </div>
      <button className="rebal-btn" onClick={onRebalance}>⟲ REBALANCE</button>
    </div>
  );
}

// ---------- HoldingsTable ----------
function Holdings({ rows, selectedTicker, onSelect, prices, sort, onSort, filter, onFilter }) {
  const sorted = useMemo(() => {
    const f = filter.trim().toUpperCase();
    let list = rows;
    if (f) list = list.filter(r => r.ticker.includes(f) || r.name.toUpperCase().includes(f) || r.sector.includes(f));
    const arr = list.slice();
    arr.sort((a, b) => {
      const { key, dir } = sort;
      let av, bv;
      if (key === "ticker") { av = a.ticker; bv = b.ticker; }
      else if (key === "weight") { av = a.weight; bv = b.weight; }
      else if (key === "target") { av = a.target; bv = b.target; }
      else if (key === "drift") { av = Math.abs(a.weight - a.target); bv = Math.abs(b.weight - b.target); }
      else if (key === "price") { av = prices[a.ticker] ?? a.price; bv = prices[b.ticker] ?? b.price; }
      else if (key === "dayPct") { av = a.dayPct; bv = b.dayPct; }
      else { av = a[key]; bv = b[key]; }
      if (typeof av === "string") return dir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
      return dir === "asc" ? av - bv : bv - av;
    });
    return arr;
  }, [rows, sort, prices, filter]);

  const sortIndicator = (key) => sort.key === key ? (sort.dir === "asc" ? "▲" : "▼") : "";

  return (
    <div className="holdings">
      <div className="phead">
        <div>
          <span className="title">Holdings</span>
          <span className="counter">{sorted.length}/{rows.length}</span>
        </div>
        <div className="actions" style={{ gap: 8, alignItems: "center" }}>
          <input
            value={filter}
            onChange={e => onFilter(e.target.value)}
            placeholder="FILTER ⌕"
            style={{
              background: "var(--term-panel-raise)",
              border: "1px solid var(--term-panel-edge)",
              color: "var(--fg-primary)",
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              padding: "2px 6px",
              letterSpacing: "0.04em",
              width: 110,
              outline: "none",
            }}
          />
        </div>
      </div>
      <div className="holdings-head">
        <span className={"sortable " + (sort.key === "ticker" ? "sort-active" : "")} onClick={() => onSort("ticker")}>TK {sortIndicator("ticker")}</span>
        <span className={"sortable " + (sort.key === "sector" ? "sort-active" : "")} onClick={() => onSort("sector")}>NAME / SECTOR</span>
        <span className={"sortable " + (sort.key === "price" ? "sort-active" : "")} onClick={() => onSort("price")} style={{ textAlign: "right" }}>LAST {sortIndicator("price")}</span>
        <span className={"sortable " + (sort.key === "dayPct" ? "sort-active" : "")} onClick={() => onSort("dayPct")} style={{ textAlign: "right" }}>CHG% {sortIndicator("dayPct")}</span>
        <span className={"sortable " + (sort.key === "weight" ? "sort-active" : "")} onClick={() => onSort("weight")} style={{ textAlign: "right" }}>WT {sortIndicator("weight")}</span>
        <span style={{ textAlign: "center" }}>DRIFT</span>
        <span className={"sortable " + (sort.key === "drift" ? "sort-active" : "")} onClick={() => onSort("drift")} style={{ textAlign: "right" }}>Δ pp {sortIndicator("drift")}</span>
        <span style={{ textAlign: "right" }}>TGT</span>
      </div>
      <div className="holdings-body">
        {sorted.map(r => {
          const price = prices[r.ticker] ?? r.price;
          const drift = (r.weight - r.target) * 100; // pp
          const absDrift = Math.abs(drift);
          const maxDriftView = 4; // ±4pp visual cap
          const barPct = Math.min(1, absDrift / maxDriftView);
          const driftColor = absDrift >= 3 ? "var(--down)" : absDrift >= 2 ? "var(--accent)" : "var(--up)";
          return (
            <div
              key={r.ticker}
              className={"holdings-row " + (selectedTicker === r.ticker ? "selected" : "")}
              onClick={() => onSelect(r.ticker)}
            >
              <span className="tk">{r.ticker}</span>
              <span className="nm">
                <span style={{ color: "var(--fg-primary)" }}>{r.name}</span>
                <span style={{ color: "var(--fg-muted)", marginLeft: 6, fontSize: 9, letterSpacing: "0.06em" }}>{r.sector}</span>
              </span>
              <span className="px">{price.toFixed(2)}</span>
              <span className={"dp " + (r.dayPct >= 0 ? "up" : "down")}>
                {(r.dayPct >= 0 ? "+" : "") + r.dayPct.toFixed(2)}
              </span>
              <span className="wt">{(r.weight * 100).toFixed(1)}%</span>
              <span className="drift-bar-wrap">
                <span className="drift-mid" />
                <span
                  className="drift-bar"
                  style={{
                    left: drift >= 0 ? "50%" : `${50 - barPct * 50}%`,
                    width: `${barPct * 50}%`,
                    background: driftColor,
                  }}
                />
              </span>
              <span className="tgt" style={{ color: driftColor, fontWeight: 600 }}>
                {(drift >= 0 ? "+" : "") + drift.toFixed(2)}
              </span>
              <span className="tgt">{(r.target * 100).toFixed(1)}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------- NewsFeed ----------
function NewsFeed({ items, onSelectTicker }) {
  return (
    <div className="panel">
      <div className="phead">
        <div>
          <span className="title">News</span>
          <span className="counter">{items.length}</span>
        </div>
        <div className="actions">
          <button className="icon-btn">⌕</button>
        </div>
      </div>
      <div className="pbody">
        {items.map(n => (
          <div key={n.id} className="news-row">
            <div className="news-meta">
              <span className="src">{n.src}</span>
              <span>{n.time}</span>
            </div>
            <div className="news-title">{n.title}</div>
            {n.tickers.length > 0 && (
              <div className="news-tickers">
                {n.tickers.map(t => (
                  <span key={t} className="news-tk" onClick={e => { e.stopPropagation(); onSelectTicker(t); }}>{t}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- MacroRegime ----------
function MacroRegime({ regimes }) {
  return (
    <div className="panel">
      <div className="phead">
        <div>
          <span className="title">Macro Regime</span>
          <span className="counter">Real-time</span>
        </div>
      </div>
      <div className="pbody">
        {regimes.map(r => (
          <div key={r.region} className="macro-row">
            <span className="region">{r.region}</span>
            <span className="lbl">{r.label}</span>
            <span className={"stress " + r.color}>{(r.stress * 100).toFixed(0)}</span>
            <span className="trend">{r.trend}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- ChartToolbar ----------
function ChartToolbar({ ticker, name, price, dayPct, tf, onTf, onCompare, onRebalance }) {
  const tfs = ["1D", "1W", "1M", "3M", "1Y", "5Y", "MAX"];
  return (
    <div className="chart-toolbar">
      <div className="ticker-head">
        <span className="tk">{ticker}</span>
        <span className="nm">{name}</span>
      </div>
      <div className="chart-price-big">
        <span className="big">{price.toFixed(2)}</span>
        <span className={"chg " + (dayPct >= 0 ? "up" : "down")}>
          {(dayPct >= 0 ? "▲ +" : "▼ ") + dayPct.toFixed(2)}%
        </span>
      </div>
      <div className="tf-group">
        {tfs.map(t => (
          <button key={t} className={"tf-btn " + (tf === t ? "active" : "")} onClick={() => onTf(t)}>{t}</button>
        ))}
      </div>
      <div className="chart-tools-right">
        <button className="icon-cta" onClick={onCompare}>+ COMPARE</button>
        <button className="icon-cta">INDICATORS</button>
        <button className="icon-cta primary" onClick={onRebalance}>⟲ REBALANCE</button>
      </div>
    </div>
  );
}

Object.assign(window, {
  TopBar, StatusBar, PortfolioSelector, Watchlist, AlertStream, TradeLog,
  Summary, Holdings, NewsFeed, MacroRegime, ChartToolbar,
});
