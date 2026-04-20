// Focus Mode (Rebalance) + Tweaks + App shell

const { useState, useEffect, useMemo, useRef, useCallback } = React;

// ---------- RebalanceFocusMode ----------
function RebalanceFocus({ portfolio, rows, onClose, onConfirm, prices }) {
  // Compute trades: drift * aum / price
  const trades = useMemo(() => {
    return rows.map(r => {
      const drift = r.target - r.weight; // positive => need to BUY more
      const driftPp = drift * 100;
      const notional = drift * (portfolio?.aum ?? 0);
      const px = prices[r.ticker] ?? r.price;
      const qty = Math.round(Math.abs(notional) / px);
      let action;
      if (Math.abs(driftPp) < 0.3) action = "HOLD";
      else if (drift > 0) action = "BUY";
      else action = "SELL";
      return {
        ticker: r.ticker,
        name: r.name,
        weight: r.weight,
        target: r.target,
        driftPp,
        action,
        qty: action === "HOLD" ? 0 : qty,
        notional: Math.abs(notional),
        price: px,
      };
    }).sort((a, b) => Math.abs(b.driftPp) - Math.abs(a.driftPp));
  }, [rows, portfolio, prices]);

  const totalNotional = trades.filter(t => t.action !== "HOLD").reduce((s, t) => s + t.notional, 0);
  const tradeCount = trades.filter(t => t.action !== "HOLD").length;

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="focus-overlay" onClick={onClose}>
      <div className="focus-modal" onClick={e => e.stopPropagation()}>
        <div className="focus-head">
          <div>
            <div className="title">Rebalance — {portfolio?.display_name}</div>
            <div className="sub">
              {tradeCount} trades · ${(totalNotional / 1e6).toFixed(2)}M notional · Draft
            </div>
          </div>
          <button className="close" onClick={onClose}>ESC ·  CLOSE</button>
        </div>
        <div className="focus-body">
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 18,
          }}>
            <KpiCard label="Drift Breaches" value={rows.filter(r => Math.abs(r.weight - r.target) >= 0.03).length} tone="alert" />
            <KpiCard label="Drift Watches"  value={rows.filter(r => Math.abs(r.weight - r.target) >= 0.02 && Math.abs(r.weight - r.target) < 0.03).length} tone="warn" />
            <KpiCard label="Est. Trading Cost" value={"$" + (totalNotional * 0.0008 / 1000).toFixed(1) + "K"} tone="neutral" />
            <KpiCard label="Post-Trade Cash" value="$0.12M" tone="neutral" />
          </div>
          <table className="focus-table">
            <thead>
              <tr>
                <th>ACTION</th>
                <th>TICKER</th>
                <th>NAME</th>
                <th style={{ textAlign: "right" }}>CURR WT</th>
                <th style={{ textAlign: "right" }}>TGT WT</th>
                <th style={{ textAlign: "right" }}>DRIFT pp</th>
                <th style={{ textAlign: "right" }}>QTY</th>
                <th style={{ textAlign: "right" }}>PX</th>
                <th style={{ textAlign: "right" }}>NOTIONAL</th>
              </tr>
            </thead>
            <tbody>
              {trades.map(t => (
                <tr key={t.ticker}>
                  <td><span className={"action " + t.action}>{t.action}</span></td>
                  <td className="tk">{t.ticker}</td>
                  <td style={{ color: "var(--fg-secondary)", fontSize: 11 }}>{t.name}</td>
                  <td className="num">{(t.weight * 100).toFixed(1)}%</td>
                  <td className="num" style={{ color: "var(--fg-tertiary)" }}>{(t.target * 100).toFixed(1)}%</td>
                  <td className={"num drift " + (t.driftPp >= 0 ? "up" : "down")}>
                    {(t.driftPp >= 0 ? "+" : "") + t.driftPp.toFixed(2)}
                  </td>
                  <td className="num">{t.action === "HOLD" ? "—" : t.qty.toLocaleString()}</td>
                  <td className="num">{t.price.toFixed(2)}</td>
                  <td className="num">{t.action === "HOLD" ? "—" : "$" + (t.notional / 1000).toFixed(1) + "K"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="focus-foot">
          <button className="btn" onClick={onClose}>CANCEL</button>
          <button className="btn">SAVE DRAFT</button>
          <button className="btn primary" onClick={onConfirm}>CONFIRM {tradeCount} TRADES</button>
        </div>
      </div>
    </div>
  );
}

function KpiCard({ label, value, tone }) {
  const color = tone === "alert" ? "var(--down)" : tone === "warn" ? "var(--accent)" : tone === "ok" ? "var(--up)" : "var(--fg-primary)";
  return (
    <div style={{
      border: "1px solid var(--term-panel-edge)",
      padding: "10px 12px",
      background: "var(--term-panel)",
    }}>
      <div style={{ fontSize: 9, letterSpacing: "0.08em", color: "var(--fg-tertiary)", textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 22, fontWeight: 600, color, marginTop: 4, fontVariantNumeric: "tabular-nums" }}>
        {value}
      </div>
    </div>
  );
}

// ---------- Tweaks panel ----------
function Tweaks({ settings, setSettings, onClose }) {
  const update = (k, v) => setSettings(s => ({ ...s, [k]: v }));
  return (
    <div className="tweaks">
      <div className="tweaks-head">
        <span className="title">⟐ Tweaks</span>
        <button className="close" onClick={onClose}>×</button>
      </div>
      <div className="tweaks-body">
        <div className="tweak-field">
          <span className="label">Theme</span>
          <div className="tweak-seg">
            {["dark", "light"].map(o => (
              <button key={o} className={settings.theme === o ? "active" : ""} onClick={() => update("theme", o)}>{o}</button>
            ))}
          </div>
        </div>
        <div className="tweak-field">
          <span className="label">Density</span>
          <div className="tweak-seg">
            {["compact", "comfy"].map(o => (
              <button key={o} className={settings.density === o ? "active" : ""} onClick={() => update("density", o)}>{o}</button>
            ))}
          </div>
        </div>
        <div className="tweak-field">
          <span className="label">Accent</span>
          <div className="tweak-seg">
            {[
              { v: "netz", l: "Netz Orange" },
              { v: "amber", l: "Amber" },
              { v: "bloomberg", l: "BBG Orange" },
            ].map(o => (
              <button key={o.v} className={settings.accent === o.v ? "active" : ""} onClick={() => update("accent", o.v)}>{o.l}</button>
            ))}
          </div>
        </div>
        <div className="tweak-field">
          <span className="label">Live Market Sim</span>
          <div className="tweak-toggle" onClick={() => update("liveSim", !settings.liveSim)}>
            <span className="label" style={{ color: "var(--fg-primary)" }}>Simulate ticking prices</span>
            <span className="state">{settings.liveSim ? "ON" : "OFF"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------- App ----------
function App() {
  const [settings, setSettings] = useState(() => {
    const saved = /*EDITMODE-BEGIN*/{
      "theme": "dark",
      "density": "compact",
      "accent": "netz",
      "liveSim": true
    }/*EDITMODE-END*/;
    return saved;
  });

  const [tweaksOpen, setTweaksOpen] = useState(false);

  // Apply theme/density/accent to document
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", settings.theme);
    document.documentElement.setAttribute("data-density", settings.density);
    document.documentElement.setAttribute("data-accent", settings.accent);
  }, [settings]);

  // Tweaks protocol (host toggle)
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

  const [selectedPid, setSelectedPid] = useState("netz-way-mod");
  const selected = PORTFOLIOS.find(p => p.id === selectedPid) ?? PORTFOLIOS[0];

  const [selectedTicker, setSelectedTicker] = useState("VTI");
  const [tf, setTf] = useState("1M");
  const [showFocus, setShowFocus] = useState(false);
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState({ key: "weight", dir: "desc" });
  const [alerts, setAlerts] = useState(ALERTS);

  const toggleSort = (key) => setSort(s => s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" });

  // Live-tick simulation
  const [prices, setPrices] = useState(() => Object.fromEntries(INSTRUMENTS.map(i => [i.ticker, i.price])));
  const [flashMap, setFlashMap] = useState({});
  const [liveTick, setLiveTick] = useState(null);

  useEffect(() => {
    if (!settings.liveSim) return;
    const id = setInterval(() => {
      setPrices(prev => {
        const next = { ...prev };
        const flash = {};
        // Pick 2-4 tickers to update each tick
        const picks = INSTRUMENTS
          .map(i => i.ticker)
          .sort(() => Math.random() - 0.5)
          .slice(0, 2 + Math.floor(Math.random() * 3));
        for (const tk of picks) {
          const cur = prev[tk];
          const nudge = (Math.random() - 0.5) * cur * 0.0012;
          const newP = Math.max(0.01, cur + nudge);
          next[tk] = newP;
          flash[tk] = newP > cur ? "up" : "down";
          if (tk === selectedTicker) {
            setLiveTick({ price: newP, time: Math.floor(Date.now() / 1000) });
          }
        }
        setFlashMap(flash);
        return next;
      });
    }, 1100);
    return () => clearInterval(id);
  }, [settings.liveSim, selectedTicker]);

  // Reset liveTick when switching tickers
  useEffect(() => {
    setLiveTick(null);
  }, [selectedTicker]);

  // Clock
  const [clock, setClock] = useState(() => new Date().toLocaleTimeString("en-US", { hour12: false }));
  useEffect(() => {
    const id = setInterval(() => setClock(new Date().toLocaleTimeString("en-US", { hour12: false })), 1000);
    return () => clearInterval(id);
  }, []);

  // Watchlist items
  const watchlistItems = INSTRUMENTS;

  // Holdings rows
  const holdingsRows = INSTRUMENTS;

  // Selected instrument
  const selectedInst = INSTRUMENTS.find(i => i.ticker === selectedTicker) ?? INSTRUMENTS[0];
  const selectedPrice = prices[selectedTicker] ?? selectedInst.price;

  // Aggregate portfolio return (weighted day pct)
  const dayReturnPct = useMemo(() => {
    return INSTRUMENTS.reduce((acc, i) => acc + i.weight * i.dayPct, 0);
  }, []);

  // Aggregate drift status
  const aggregateDrift = useMemo(() => {
    let maxDrift = 0;
    for (const r of holdingsRows) {
      maxDrift = Math.max(maxDrift, Math.abs(r.weight - r.target));
    }
    if (maxDrift >= 0.03) return "breach";
    if (maxDrift >= 0.02) return "watch";
    return "aligned";
  }, []);

  const totalAumFormatted = "$" + (selected.aum / 1e6).toFixed(2) + "M";

  const handleAck = (id) => setAlerts(prev => prev.filter(a => a.id !== id));

  const bars = HISTORICAL[selectedTicker] ?? [];

  return (
    <div className="app">
      <TopBar
        portfolios={PORTFOLIOS}
        selected={selected}
        clock={clock}
        totalAumFormatted={totalAumFormatted}
        dayReturnPct={dayReturnPct}
        onOpenTweaks={() => setTweaksOpen(v => !v)}
        tweaksOn={tweaksOpen}
        dataStatus={settings.liveSim ? "live" : "delayed"}
      />

      <div className="grid">
        {/* LEFT */}
        <aside className="col col-left">
          <PortfolioSelector portfolios={PORTFOLIOS} selected={selected} onSelect={p => setSelectedPid(p.id)} />
          <div style={{ flex: "60 1 0", minHeight: 0, display: "flex", borderBottom: "1px solid var(--term-panel-edge)" }}>
            <Watchlist
              items={watchlistItems}
              selectedTicker={selectedTicker}
              onSelect={setSelectedTicker}
              prices={prices}
              flashMap={flashMap}
            />
          </div>
          <div style={{ flex: "25 1 0", minHeight: 0, display: "flex", borderBottom: "1px solid var(--term-panel-edge)" }}>
            <AlertStream alerts={alerts} onAck={handleAck} />
          </div>
          <div style={{ flex: "20 1 0", minHeight: 0, display: "flex" }}>
            <TradeLog trades={TRADES} />
          </div>
        </aside>

        {/* CENTER */}
        <section className="col">
          <ChartToolbar
            ticker={selectedTicker}
            name={selectedInst.name}
            price={selectedPrice}
            dayPct={selectedInst.dayPct}
            tf={tf}
            onTf={setTf}
            onCompare={() => {}}
            onRebalance={() => setShowFocus(true)}
          />
          <div className="chart-area">
            <CandleChart bars={bars} liveTick={liveTick} ticker={selectedTicker} />
          </div>
          <div className="center-bottom">
            <Summary
              portfolio={selected}
              aum={selected.aum}
              dayPct={dayReturnPct}
              instrumentCount={holdingsRows.length}
              driftStatus={aggregateDrift}
              lastRebal="2026-04-14 · 09:32"
              onRebalance={() => setShowFocus(true)}
            />
            <Holdings
              rows={holdingsRows}
              selectedTicker={selectedTicker}
              onSelect={setSelectedTicker}
              prices={prices}
              sort={sort}
              onSort={toggleSort}
              filter={filter}
              onFilter={setFilter}
            />
          </div>
        </section>

        {/* RIGHT */}
        <aside className="col col-right">
          <div style={{ flex: "55 1 0", minHeight: 0, display: "flex", borderBottom: "1px solid var(--term-panel-edge)" }}>
            <NewsFeed items={NEWS} onSelectTicker={setSelectedTicker} />
          </div>
          <div style={{ flex: "45 1 0", minHeight: 0, display: "flex" }}>
            <MacroRegime regimes={MACRO_REGIMES} />
          </div>
        </aside>
      </div>

      <StatusBar
        message={settings.liveSim ? "✓ Connected · Tiingo WS · 14 tickers subscribed · " + alerts.length + " open alerts" : "◯ Paused · Live tick simulation OFF"}
        keyHints={[
          { k: "⌘K", l: "Cmd" },
          { k: "J/K", l: "Nav" },
          { k: "E",   l: "Ack" },
          { k: "R",   l: "Rebal" },
          { k: "?",   l: "Help" },
        ]}
      />

      {tweaksOpen && (
        <Tweaks settings={settings} setSettings={s => {
          const next = typeof s === "function" ? s(settings) : s;
          setSettings(next);
          window.parent.postMessage({ type: "__edit_mode_set_keys", edits: next }, "*");
        }} onClose={() => setTweaksOpen(false)} />
      )}

      {showFocus && (
        <RebalanceFocus
          portfolio={selected}
          rows={holdingsRows}
          prices={prices}
          onClose={() => setShowFocus(false)}
          onConfirm={() => setShowFocus(false)}
        />
      )}
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<App />);
