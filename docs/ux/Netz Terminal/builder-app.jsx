// Builder — App shell. 40/60 split, calibration, cascade simulation, 7 tabs.

const { useState, useEffect, useRef, useMemo } = React;

const TABS = [
  { id: "REGIME",   label: "Regime",      comp: "RegimeTab" },
  { id: "WEIGHTS",  label: "Weights",     comp: "WeightsTab" },
  { id: "RISK",     label: "Risk",        comp: "RiskTab" },
  { id: "STRESS",   label: "Stress",      comp: "StressTab" },
  { id: "BACKTEST", label: "Backtest",    comp: "BacktestTab" },
  { id: "MC",       label: "Monte Carlo", comp: "MonteCarloTab" },
  { id: "ADVISOR",  label: "Advisor",     comp: "AdvisorTab" },
];

// ── Breadcrumb ──
function Breadcrumb({ portfolio, onPortfolioChange }) {
  return (
    <div className="bd-breadcrumb">
      <a href="Netz Terminal - Screener.html" className="bd-crumb">← Screener</a>
      <span className="bd-crumb-sep">/</span>
      <a href="Netz Terminal.html" className="bd-crumb">Terminal</a>
      <span className="bd-crumb-sep">/</span>
      <a href="Netz Terminal - Macro.html" className="bd-crumb">Macro</a>
      <span className="bd-crumb-sep">/</span>
      <span className="bd-crumb current">Builder</span>
      <select className="bd-port-sel" value={portfolio} onChange={e => onPortfolioChange(e.target.value)}>
        <option value="GLOBAL_MACRO">Netz Global Macro · $82M</option>
        <option value="ENDOWMENT">Endowment Model · $210M</option>
        <option value="OFFSHORE_HNW">Offshore HNW Composite · $48M</option>
      </select>
      <span className="bd-port-badge">ALLOC</span>
    </div>
  );
}

// ── Zone A: Regime context ──
function ZoneA() {
  return (
    <div className="bd-zone-a">
      <div className="bd-za-header">
        <div className="bd-za-title">Regime Context · Live</div>
        <div className="bd-regime-pill">{REGIME_CONTEXT.current.replace("_"," ")}</div>
      </div>
      <div className="bd-za-bands">
        {REGIME_CONTEXT.bands.map(b => {
          const kind = b.z > 0.5 ? "hot" : b.z < -0.5 ? "cool" : "";
          return (
            <div key={b.code} className={"bd-za-band " + kind}>
              <div className="c">{b.code}</div>
              <div className="v">{b.v.toLocaleString("en-US", { maximumFractionDigits: 2 })}</div>
              <div className="z">{b.z > 0 ? "+" : ""}{b.z.toFixed(1)}σ</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Zone B: Calibration panel ──
function ZoneB({ cal, setCal }) {
  const applyPreset = (name) => {
    const p = PRESETS[name];
    setCal({
      ...cal,
      preset: name,
      optimizer: { ...cal.optimizer, riskAversion: p.riskAversion },
      constraints: { ...cal.constraints, maxDrawdown: p.maxDrawdown, trackingError: p.trackingError },
      factors: { ...cal.factors, momentum: p.factorMomentum, quality: p.factorQuality },
    });
  };
  const Factor = ({ id, name }) => (
    <div className="bd-slider">
      <label>{name}</label>
      <input type="range" min="-1.5" max="1.5" step="0.05"
        value={cal.factors[id]}
        onChange={e => setCal({ ...cal, preset: "CUSTOM", factors: { ...cal.factors, [id]: parseFloat(e.target.value) } })} />
      <span className={"val " + (cal.factors[id] > 0 ? "pos" : cal.factors[id] < 0 ? "neg" : "")}>
        {cal.factors[id] > 0 ? "+" : ""}{cal.factors[id].toFixed(2)}
      </span>
    </div>
  );
  const Constraint = ({ k, label, min, max, step, unit = "%" }) => (
    <div className="bd-slider">
      <label>{label}</label>
      <input type="range" min={min} max={max} step={step}
        value={cal.constraints[k]}
        onChange={e => setCal({ ...cal, preset: "CUSTOM", constraints: { ...cal.constraints, [k]: parseFloat(e.target.value) } })} />
      <span className="val">{cal.constraints[k].toFixed(step < 1 ? 1 : 0)}{unit}</span>
    </div>
  );
  return (
    <div className="bd-zone-b">
      {/* Presets */}
      <div className="bd-section">
        <div className="bd-section-hd"><h4>Risk Preset</h4><span className="sub">one click calibrations</span></div>
        <div className="bd-presets">
          {["CONSERVATIVE", "MODERATE", "AGGRESSIVE"].map(p => (
            <button key={p} className={"bd-preset " + (cal.preset === p ? "active" : "")} onClick={() => applyPreset(p)}>{p}</button>
          ))}
        </div>
      </div>
      {/* Factor tilts */}
      <div className="bd-section">
        <div className="bd-section-hd"><h4>Factor Tilts</h4><span className="sub">target β · −1.5σ … +1.5σ</span></div>
        <Factor id="growth"   name="Growth" />
        <Factor id="value"    name="Value" />
        <Factor id="momentum" name="Momentum" />
        <Factor id="quality"  name="Quality" />
        <Factor id="size"     name="Size" />
      </div>
      {/* Constraints */}
      <div className="bd-section">
        <div className="bd-section-hd"><h4>Constraints</h4><span className="sub">hard limits</span></div>
        <Constraint k="maxDrawdown"   label="Max DD"      min="5"  max="30" step="1" />
        <Constraint k="trackingError" label="Track Error" min="0.5" max="8" step="0.1" />
        <Constraint k="turnoverLimit" label="Turnover"    min="10" max="100" step="5" />
        <Constraint k="maxSingleName" label="Max Name"    min="3" max="15" step="0.5" />
      </div>
      {/* Region caps */}
      <div className="bd-section">
        <div className="bd-section-hd"><h4>Region Caps</h4><span className="sub">max allocation</span></div>
        <div className="bd-caps-grid">
          {Object.entries(cal.regionCaps).map(([k, v]) => (
            <div key={k} className="bd-cap">
              <span className="n">{k}</span>
              <span className="v">{v}%</span>
            </div>
          ))}
        </div>
      </div>
      {/* Optimizer settings */}
      <div className="bd-section">
        <div className="bd-section-hd"><h4>Optimizer</h4><span className="sub">SOCP parameters</span></div>
        <div className="bd-slider">
          <label>Risk Avers (λ)</label>
          <input type="range" min="0.5" max="5" step="0.1"
            value={cal.optimizer.riskAversion}
            onChange={e => setCal({ ...cal, preset: "CUSTOM", optimizer: { ...cal.optimizer, riskAversion: parseFloat(e.target.value) } })} />
          <span className="val">{cal.optimizer.riskAversion.toFixed(1)}</span>
        </div>
        <div className="bd-slider">
          <label>LW Shrinkage</label>
          <input type="range" min="0" max="1" step="0.05"
            value={cal.optimizer.shrinkage}
            onChange={e => setCal({ ...cal, preset: "CUSTOM", optimizer: { ...cal.optimizer, shrinkage: parseFloat(e.target.value) } })} />
          <span className="val">{cal.optimizer.shrinkage.toFixed(2)}</span>
        </div>
      </div>
    </div>
  );
}

// ── Zone C: Run controls ──
function ZoneC({ status, onRun, onReset }) {
  const isRunning = status === "RUNNING";
  const isDone = status === "DONE";
  return (
    <div className="bd-zone-c">
      <div className="bd-run-info">
        <div className="t">{isDone ? "Optimization Complete" : isRunning ? "Running Cascade…" : "Ready to Build"}</div>
        <div>{isDone ? "Review tabs then activate" : isRunning ? "do not close window" : "calibration locked · 22 assets · SOCP ready"}</div>
      </div>
      {isDone ? (
        <button className="bd-btn-build" onClick={onReset} style={{background:"var(--term-panel-raise)", color:"var(--accent)", border:"1px solid var(--accent)"}}>RESET</button>
      ) : (
        <button className={"bd-btn-build " + (isRunning ? "running" : "")} disabled={isRunning} onClick={onRun}>
          {isRunning ? "RUNNING…" : "BUILD ▸"}
        </button>
      )}
    </div>
  );
}

// ── Cascade timeline ──
function CascadeTimeline({ phaseIdx, phaseProgress, collapsed }) {
  return (
    <div className={"bd-cascade " + (collapsed ? "collapsed" : "")}>
      {CASCADE_PHASES.map((p, i) => {
        const state = i < phaseIdx ? "done" : i === phaseIdx ? "active" : "pending";
        const fill = i < phaseIdx ? 100 : i === phaseIdx ? phaseProgress : 0;
        return (
          <div key={p.id} className={"bd-phase " + state}>
            <div className="ph-num">{String(i+1).padStart(2,"0")} · {p.id.replace(/_/g," ")}</div>
            <div className="ph-label">{p.label}</div>
            <div className="ph-sub">{p.sub}</div>
            <div className="bd-phase-fill" style={{ width: fill + "%" }} />
          </div>
        );
      })}
    </div>
  );
}

// ── Main app ──
function BuilderApp() {
  const [portfolio, setPortfolio] = useState("GLOBAL_MACRO");
  const [cal, setCal] = useState(CALIBRATION_DEFAULTS);
  const [status, setStatus] = useState("IDLE");  // IDLE | RUNNING | DONE
  const [phaseIdx, setPhaseIdx] = useState(-1);
  const [phaseProgress, setPhaseProgress] = useState(0);
  const [activeTab, setActiveTab] = useState("REGIME");
  const [visited, setVisited] = useState(new Set(["REGIME"]));
  const tickRef = useRef(null);

  // Mark visited when tab is opened (post-run only for gating)
  useEffect(() => {
    if (status === "DONE") {
      setVisited(prev => {
        if (prev.has(activeTab)) return prev;
        const next = new Set(prev); next.add(activeTab); return next;
      });
    }
  }, [activeTab, status]);

  // Cascade simulation
  const runCascade = () => {
    if (status === "RUNNING") return;
    setStatus("RUNNING");
    setPhaseIdx(0);
    setPhaseProgress(0);
    setVisited(new Set());
    let phase = 0;
    let startedAt = performance.now();
    const tick = () => {
      const now = performance.now();
      const dur = CASCADE_PHASES[phase].dur;
      const elapsed = now - startedAt;
      const pct = Math.min(100, (elapsed / dur) * 100);
      setPhaseProgress(pct);
      if (elapsed >= dur) {
        phase += 1;
        if (phase >= CASCADE_PHASES.length) {
          setPhaseIdx(CASCADE_PHASES.length);
          setPhaseProgress(100);
          setStatus("DONE");
          setActiveTab("WEIGHTS");      // auto-switch
          setVisited(new Set(["WEIGHTS"]));
          return;
        }
        setPhaseIdx(phase);
        startedAt = now;
      }
      tickRef.current = requestAnimationFrame(tick);
    };
    tickRef.current = requestAnimationFrame(tick);
  };

  useEffect(() => () => tickRef.current && cancelAnimationFrame(tickRef.current), []);

  const onReset = () => {
    setStatus("IDLE");
    setPhaseIdx(-1);
    setPhaseProgress(0);
    setActiveTab("REGIME");
    setVisited(new Set(["REGIME"]));
  };

  // Pulsing tabs — based on current phase
  const pulsingTabs = useMemo(() => {
    if (status !== "RUNNING" || phaseIdx < 0 || phaseIdx >= CASCADE_PHASES.length) return new Set();
    return new Set(CASCADE_PHASES[phaseIdx].tabs || []);
  }, [status, phaseIdx]);

  // Render preview
  const renderContent = () => {
    if (status === "IDLE") {
      return (
        <div className="bd-empty">
          <div className="bd-empty-ico">◎</div>
          <div className="bd-empty-t">Portfolio Build Pipeline</div>
          <div className="bd-empty-s">
            Calibrate factor tilts and constraints on the left, then hit <strong style={{color:"var(--accent)"}}>BUILD</strong> to run the SOCP cascade:
            factor modeling → covariance shrinkage → optimization → stress / backtest → Monte Carlo → advisor synthesis.
          </div>
        </div>
      );
    }
    if (status === "RUNNING") {
      return (
        <div className="bd-empty">
          <div className="bd-empty-ico" style={{ borderColor: "var(--accent)", color: "var(--accent)", animation: "tabPulse 1s ease-in-out infinite" }}>⏱</div>
          <div className="bd-empty-t" style={{ color: "var(--accent)" }}>
            {phaseIdx >= 0 && phaseIdx < CASCADE_PHASES.length ? CASCADE_PHASES[phaseIdx].label : "Processing"}
          </div>
          <div className="bd-empty-s">
            {phaseIdx >= 0 && phaseIdx < CASCADE_PHASES.length ? CASCADE_PHASES[phaseIdx].sub : "Running cascade…"}
            <br /><br />
            tabs pulse as their dependencies resolve · auto-switch to Weights on completion
          </div>
        </div>
      );
    }
    // DONE
    const Comp = window[TABS.find(t => t.id === activeTab).comp];
    return <Comp />;
  };

  // Activation gate: need all 7 visited post-run
  const totalTabs = TABS.length;
  const visitedCount = visited.size;
  const ready = status === "DONE" && visitedCount >= totalTabs;

  return (
    <>
      <Breadcrumb portfolio={portfolio} onPortfolioChange={setPortfolio} />
      <div className="bd-shell">
        {/* LEFT */}
        <div className="bd-left">
          <ZoneA />
          <ZoneB cal={cal} setCal={setCal} />
          <ZoneC status={status} onRun={runCascade} onReset={onReset} />
        </div>

        {/* RIGHT */}
        <div className="bd-right">
          <div className="bd-tabs">
            {TABS.map(t => {
              const isPulsing = pulsingTabs.has(t.id);
              const isLocked = status === "RUNNING" && !isPulsing;
              const isVisited = visited.has(t.id) && status === "DONE";
              return (
                <button
                  key={t.id}
                  className={[
                    "bd-tab",
                    activeTab === t.id ? "active" : "",
                    isPulsing ? "pulsing" : "",
                    isLocked ? "locked" : "",
                    isVisited && activeTab !== t.id ? "visited" : "",
                  ].join(" ")}
                  disabled={isLocked}
                  onClick={() => !isLocked && setActiveTab(t.id)}
                >
                  {t.label}
                </button>
              );
            })}
          </div>

          <CascadeTimeline
            phaseIdx={phaseIdx}
            phaseProgress={phaseProgress}
            collapsed={status === "IDLE"}
          />

          <div className="bd-content">
            {renderContent()}
          </div>

          <div className="bd-activation">
            <div className="bd-act-dots">
              {TABS.map(t => (
                <div key={t.id}
                  className={"bd-act-dot " +
                    (visited.has(t.id) && status === "DONE" ? "visited " : "") +
                    (activeTab === t.id && status === "DONE" ? "active" : "")}
                  title={t.label} />
              ))}
            </div>
            <div className="bd-act-info">
              {status !== "DONE" ? (
                <>Activation gate · <strong>run cascade first</strong></>
              ) : ready ? (
                <>All tabs reviewed · <strong style={{color:"var(--up)"}}>ready to activate</strong></>
              ) : (
                <>Visit all tabs to unlock · <strong>{visitedCount}/{totalTabs}</strong> reviewed</>
              )}
            </div>
            <button className={"bd-btn-activate " + (ready ? "ready" : "")} disabled={!ready}>
              {ready ? "SEND TO COMPLIANCE ▸" : "LOCKED"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(<BuilderApp />);
