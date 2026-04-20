// Builder preview tabs — render content for each of 7 tabs

const { useMemo: useMemoP } = React;

const fmtPct = (v, dp = 1) => (v >= 0 ? "+" : "") + v.toFixed(dp) + "%";

// KPI ribbon always on top
function KpiRibbon() {
  const items = [
    { l: "EXP. RETURN", v: "+9.8%", vs: "+1.6pp vs prior", up: true },
    { l: "VOL (ANN)",   v: "10.8%", vs: "−0.6pp vs prior", up: true },
    { l: "SHARPE",      v: "0.83",  vs: "+0.18 vs prior",  up: true },
    { l: "MAX DD",      v: "−14.2%",vs: "target −15%",     up: true },
    { l: "TRACK. ERR.", v: "2.8%",  vs: "budget 3.0%",     up: true },
  ];
  return (
    <div className="bd-kpis">
      {items.map((k, i) => (
        <div key={i} className="bd-kpi">
          <div className="lb">{k.l}</div>
          <div className={"vl " + (k.l === "EXP. RETURN" ? "up" : k.l === "MAX DD" ? "down" : "")}>{k.v}</div>
          <div className={"vs " + (k.up ? "up" : "")}>{k.vs}</div>
        </div>
      ))}
    </div>
  );
}

// ─── REGIME TAB ───
function RegimeTab() {
  const quadrants = [
    { name: "EARLY RECOVERY", g: 1, i: -1, color: "var(--up)" },
    { name: "MID CYCLE",      g: 1, i:  1, color: "#6689BC" },
    { name: "LATE CYCLE",     g:-1, i:  1, color: "var(--accent)" },
    { name: "RECESSION",      g:-1, i: -1, color: "var(--down)" },
  ];
  const W = 440, H = 320, cx = W/2, cy = H/2;
  const px = cx + REGIME_CONTEXT.growth * 80;
  const py = cy - REGIME_CONTEXT.inflation * 80;

  return (
    <>
      <KpiRibbon />
      <div className="pane">
        <h5><span>Regime Quadrant · Growth × Inflation (z-score)</span><span className="sub">current: {REGIME_CONTEXT.current.replace("_"," ")}</span></h5>
        <div className="body" style={{ display: "flex", gap: 20 }}>
          <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
            {/* quadrant fills */}
            <rect x="0" y="0" width={cx} height={cy} fill="#6689BC" opacity="0.06" />
            <rect x={cx} y="0" width={cx} height={cy} fill="var(--accent)" opacity="0.08" />
            <rect x="0" y={cy} width={cx} height={cy} fill="var(--up)" opacity="0.06" />
            <rect x={cx} y={cy} width={cx} height={cy} fill="var(--down)" opacity="0.08" />
            {/* axes */}
            <line x1="0" x2={W} y1={cy} y2={cy} stroke="var(--term-panel-edge)" />
            <line x1={cx} x2={cx} y1="0" y2={H} stroke="var(--term-panel-edge)" />
            {/* labels */}
            {quadrants.map(q => (
              <text key={q.name} x={cx + q.g*100} y={cy - q.i*100} textAnchor="middle"
                fontFamily="var(--font-mono)" fontSize="10" fontWeight="700"
                fill={q.color} letterSpacing="0.08em">{q.name}</text>
            ))}
            {/* axis labels */}
            <text x={W-6} y={cy-4} textAnchor="end" fontFamily="var(--font-mono)" fontSize="9" fill="var(--fg-muted)">GROWTH +</text>
            <text x="6" y={cy-4} fontFamily="var(--font-mono)" fontSize="9" fill="var(--fg-muted)">GROWTH −</text>
            <text x={cx+4} y="12" fontFamily="var(--font-mono)" fontSize="9" fill="var(--fg-muted)">INFL +</text>
            <text x={cx+4} y={H-4} fontFamily="var(--font-mono)" fontSize="9" fill="var(--fg-muted)">INFL −</text>
            {/* pin */}
            <circle cx={px} cy={py} r="14" fill="var(--accent)" opacity="0.2" />
            <circle cx={px} cy={py} r="8" fill="var(--accent)" stroke="var(--term-void)" strokeWidth="2" />
          </svg>
          <div style={{ flex: 1 }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.08em", color: "var(--fg-muted)", textTransform: "uppercase", marginBottom: 8, fontWeight: 700 }}>
              Global Bands · z-scores
            </div>
            {REGIME_CONTEXT.bands.map(b => {
              const leftPct = ((b.z + 2) / 4) * 100;
              const hot = b.z > 0.5, cool = b.z < -0.5;
              return (
                <div key={b.code} style={{ display: "grid", gridTemplateColumns: "70px 1fr 60px", gap: 10, alignItems: "center", padding: "5px 0", fontFamily: "var(--font-mono)", fontSize: 10 }}>
                  <div>
                    <div style={{ color: "var(--accent)", fontWeight: 700 }}>{b.code}</div>
                    <div style={{ fontSize: 8, color: "var(--fg-muted)", letterSpacing: "0.04em" }}>{b.label}</div>
                  </div>
                  <div style={{ position: "relative", height: 14, background: "var(--term-panel-raise)", borderRadius: 2 }}>
                    <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "var(--term-panel-edge)" }} />
                    <div style={{ position: "absolute", left: `calc(${leftPct}% - 3px)`, top: -1, width: 6, height: 16, background: hot ? "var(--down)" : cool ? "var(--up)" : "var(--fg-muted)", borderRadius: 1 }} />
                  </div>
                  <div style={{ textAlign: "right", fontVariantNumeric: "tabular-nums", color: hot ? "var(--down)" : cool ? "var(--up)" : "var(--fg-primary)", fontWeight: 700 }}>
                    {b.z > 0 ? "+" : ""}{b.z.toFixed(1)}σ
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
}

// ─── WEIGHTS TAB ───
function WeightsTab() {
  const maxW = Math.max(...OPTIMIZED_WEIGHTS.map(w => w.weight));
  const rows = OPTIMIZED_WEIGHTS.slice().sort((a,b) => b.weight - a.weight);
  const universeByTicker = Object.fromEntries(UNIVERSE.map(u => [u.ticker, u]));
  const total = rows.reduce((s, r) => s + r.weight, 0);

  // class aggregate
  const byClass = {};
  for (const r of rows) {
    byClass[r.cls] = (byClass[r.cls] || 0) + r.weight;
  }

  return (
    <>
      <KpiRibbon />
      <div className="pane">
        <h5><span>Optimized Weights · SOCP Output</span><span className="sub">{rows.length} positions · Σ {total.toFixed(1)}%</span></h5>
        <div className="body">
          <table className="weights-table">
            <thead>
              <tr>
                <th className="lft">Ticker</th>
                <th className="lft">Name</th>
                <th>Class</th>
                <th>Prior %</th>
                <th>Weight %</th>
                <th>Δ pp</th>
                <th style={{ width: 120 }}>Alloc</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const u = universeByTicker[r.ticker] || {};
                const d = r.weight - r.prior;
                return (
                  <tr key={r.ticker}>
                    <td className="lft tk">{r.ticker}</td>
                    <td className="lft nm">{u.name}</td>
                    <td style={{ color: "var(--fg-muted)", fontSize: 9, letterSpacing: "0.04em" }}>{r.cls}</td>
                    <td style={{ color: "var(--fg-muted)" }}>{r.prior.toFixed(1)}</td>
                    <td className="w">{r.weight.toFixed(1)}</td>
                    <td className={"delta " + (d > 0.05 ? "up" : d < -0.05 ? "down" : "")}>
                      {Math.abs(d) < 0.05 ? "—" : (d > 0 ? "+" : "") + d.toFixed(1)}
                    </td>
                    <td>
                      <span className="wbar" style={{ width: `${(r.weight / maxW) * 100}%`, background: u.color || "var(--accent)" }} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="pane">
        <h5><span>By Asset Class</span><span className="sub">aggregated</span></h5>
        <div className="body">
          {ASSET_CLASSES.map(c => {
            const w = byClass[c.id] || 0;
            return (
              <div key={c.id} style={{ display: "grid", gridTemplateColumns: "180px 1fr 50px", gap: 10, alignItems: "center", padding: "5px 0", fontFamily: "var(--font-mono)", fontSize: 11, borderBottom: "1px solid var(--term-hair)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 10, height: 10, background: c.color, borderRadius: "50%" }} />
                  <span style={{ color: "var(--fg-primary)", fontWeight: 600 }}>{c.name}</span>
                </div>
                <div style={{ height: 10, background: "var(--term-panel-raise)", borderRadius: 2, overflow: "hidden" }}>
                  <div style={{ width: `${w}%`, height: "100%", background: c.color, opacity: 0.9 }} />
                </div>
                <div style={{ textAlign: "right", color: "var(--fg-primary)", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{w.toFixed(1)}%</div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

// ─── RISK TAB ───
function RiskTab() {
  return (
    <>
      <KpiRibbon />
      <div className="pane">
        <h5><span>Factor Exposures (β)</span><span className="sub">portfolio · target · bench</span></h5>
        <div className="body">
          {FACTOR_EXPOSURES.map(f => {
            const portPct = ((f.portfolio + 1.5) / 3) * 100;
            const targPct = ((f.target + 1.5) / 3) * 100;
            const barLeft = f.portfolio >= 0 ? 50 : 50 + (f.portfolio / 1.5) * 50;
            const barW = Math.abs(f.portfolio / 1.5) * 50;
            return (
              <div key={f.factor} className="factor-row">
                <div className="fr-nm">{f.factor}</div>
                <div className="fr-bar">
                  <div className="mid" />
                  <div className="port" style={{ left: `${barLeft}%`, width: `${barW}%` }} />
                  <div className="target" style={{ left: `calc(${targPct}% - 1px)` }} title={`target ${f.target}`} />
                </div>
                <div className="fr-v port">{f.portfolio > 0 ? "+" : ""}{f.portfolio.toFixed(2)}</div>
                <div className="fr-v target">tgt {f.target > 0 ? "+" : ""}{f.target.toFixed(2)}</div>
              </div>
            );
          })}
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "var(--fg-muted)", marginTop: 8, letterSpacing: "0.04em" }}>
            scale: −1.5σ ←→ +1.5σ · green pin marks target
          </div>
        </div>
      </div>
      <div className="pane">
        <h5><span>Risk Decomposition · Contribution to Volatility</span><span className="sub">covariance: Ledoit-Wolf shrinkage · 36M window</span></h5>
        <div className="body">
          <div className="risk-bar-container">
            {RISK_DECOMP.map(r => (
              <div key={r.source} className="risk-bar-seg" style={{ width: `${r.pct}%`, background: r.color }} title={`${r.source} · ${r.pct}%`} />
            ))}
          </div>
          <div className="risk-legend">
            {RISK_DECOMP.map(r => (
              <div key={r.source} className="row">
                <span className="dot" style={{ background: r.color }} />
                <span className="nm">{r.source}</span>
                <span className="pc">{r.pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

// ─── STRESS TAB ───
function StressTab() {
  return (
    <>
      <KpiRibbon />
      <div className="pane">
        <h5><span>Historical Stress Tests</span><span className="sub">8 scenarios · portfolio P&L</span></h5>
        <div className="body">
          <div className="stress-grid">
            {STRESS_SCENARIOS.map(s => {
              const kind = s.prob === "TAIL" ? "tail" : s.prob === "UPSIDE" ? "upside" : s.prob === "MOD" ? "mod" : "";
              return (
                <div key={s.id} className={"stress-card " + kind}>
                  <div className="sh">
                    <span className="snm">{s.name}</span>
                    <span className={"spnl " + (s.pnl >= 0 ? "up" : "down")}>{fmtPct(s.pnl, 1)}</span>
                  </div>
                  <div>
                    <span className={"sprob " + kind}>{s.prob}</span>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--fg-muted)" }}>worst: <span style={{ color: "var(--accent)", fontWeight: 700 }}>{s.worst}</span></span>
                  </div>
                  <div className="snote">{s.note}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </>
  );
}

// ─── BACKTEST TAB ───
function BacktestTab() {
  const W = 720, H = 240, pad = { t: 12, r: 14, b: 24, l: 44 };
  const all = [...BACKTEST_OPTIMIZED, ...BACKTEST_PRIOR, ...BACKTEST_BENCH];
  const min = Math.min(...all), max = Math.max(...all);
  const n = BACKTEST_OPTIMIZED.length;
  const x = (i) => pad.l + (i / (n - 1)) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (v - min) / (max - min)) * (H - pad.t - pad.b);
  const path = (s) => s.map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const series = [
    { p: path(BACKTEST_BENCH), c: "var(--fg-muted)", d: "3 3", l: "EQW Bench" },
    { p: path(BACKTEST_PRIOR), c: "#9FB4D6", d: "0", l: "Prior" },
    { p: path(BACKTEST_OPTIMIZED), c: "var(--accent)", d: "0", l: "Optimized" },
  ];
  const months = ["Nov'20", "Nov'21", "Nov'22", "Nov'23", "Nov'24", "Nov'25"];

  const dd = useMemoP(() => {
    let peak = -Infinity;
    return BACKTEST_OPTIMIZED.map(v => { peak = Math.max(peak, v); return -((peak - v) / peak) * 100; });
  }, []);
  const ddMin = Math.min(...dd);

  return (
    <>
      <KpiRibbon />
      <div className="pane">
        <h5><span>Equity Curve · 5Y monthly</span><span className="sub">optimized · prior · equal-weight bench</span></h5>
        <div className="body">
          <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }}>
            {[0, 0.25, 0.5, 0.75, 1].map(t => {
              const yy = pad.t + t * (H - pad.t - pad.b);
              const val = max - t * (max - min);
              return (
                <g key={t}>
                  <line x1={pad.l} x2={W-pad.r} y1={yy} y2={yy} stroke="var(--term-hair)" />
                  <text x={pad.l - 6} y={yy + 3} textAnchor="end" fontFamily="var(--font-mono)" fontSize="9" fill="var(--fg-muted)">{val.toFixed(0)}</text>
                </g>
              );
            })}
            <line x1={pad.l} x2={W-pad.r} y1={y(100)} y2={y(100)} stroke="var(--term-panel-edge)" strokeDasharray="2 4" />
            {series.map((s, i) => <path key={i} d={s.p} fill="none" stroke={s.c} strokeWidth="1.6" strokeDasharray={s.d} />)}
            {months.map((m, i) => (
              <text key={m} x={pad.l + (i / 5) * (W - pad.l - pad.r)} y={H-6} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9" fill="var(--fg-muted)">{m}</text>
            ))}
            <g transform={`translate(${W-pad.r-180},${pad.t+4})`}>
              {series.map((s, i) => (
                <g key={i} transform={`translate(0,${i*13})`}>
                  <line x1="0" x2="14" y1="4" y2="4" stroke={s.c} strokeDasharray={s.d} strokeWidth="1.6" />
                  <text x="18" y="7" fontFamily="var(--font-mono)" fontSize="9" fill="var(--fg-secondary)">{s.l}</text>
                </g>
              ))}
            </g>
          </svg>
        </div>
      </div>
      <div className="pane">
        <h5><span>Drawdown · Optimized</span><span className="sub">max {ddMin.toFixed(1)}%</span></h5>
        <div className="body">
          <svg width="100%" height="130" viewBox="0 0 720 130" style={{ display: "block" }}>
            <defs>
              <linearGradient id="bddgrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--down)" stopOpacity="0.08" />
                <stop offset="100%" stopColor="var(--down)" stopOpacity="0.4" />
              </linearGradient>
            </defs>
            {[0, -5, -10, -15].map(t => {
              const yy = 12 + ((-t)/(-ddMin)) * 94;
              return (
                <g key={t}>
                  <line x1={pad.l} x2={720-pad.r} y1={yy} y2={yy} stroke="var(--term-hair)" />
                  <text x={pad.l-6} y={yy+3} textAnchor="end" fontFamily="var(--font-mono)" fontSize="9" fill="var(--fg-muted)">{t}%</text>
                </g>
              );
            })}
            <path d={dd.map((v, i) => {
              const xx = pad.l + (i/(dd.length-1)) * (720 - pad.l - pad.r);
              const yy = 12 + ((-v)/(-ddMin)) * 94;
              return `${i===0?"M":"L"} ${xx.toFixed(1)} ${yy.toFixed(1)}`;
            }).join(" ") + ` L ${720-pad.r} 110 L ${pad.l} 110 Z`} fill="url(#bddgrad)" />
            <path d={dd.map((v, i) => {
              const xx = pad.l + (i/(dd.length-1)) * (720 - pad.l - pad.r);
              const yy = 12 + ((-v)/(-ddMin)) * 94;
              return `${i===0?"M":"L"} ${xx.toFixed(1)} ${yy.toFixed(1)}`;
            }).join(" ")} fill="none" stroke="var(--down)" strokeWidth="1.3" />
          </svg>
        </div>
      </div>
    </>
  );
}

// ─── MONTE CARLO TAB ───
function MonteCarloTab() {
  const { percentiles, probLoss, p5, p50, p95 } = MONTE_CARLO;
  const W = 720, H = 260, pad = { t: 14, r: 14, b: 24, l: 44 };
  const all = percentiles.flat();
  const min = Math.min(...all), max = Math.max(...all);
  const steps = percentiles[0].length;
  const x = (i) => pad.l + (i/(steps-1)) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (v-min)/(max-min)) * (H - pad.t - pad.b);

  const pathFromArray = (arr) => arr.map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
  const bandPath = (hi, lo) => {
    const up = hi.map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
    const dn = lo.map((v, i) => `L ${x(lo.length-1-i).toFixed(1)} ${y(lo[lo.length-1-i]).toFixed(1)}`).reverse().join(" ");
    return up + " " + dn + " Z";
  };

  return (
    <>
      <KpiRibbon />
      <div className="mc-metrics">
        <div className="mc-metric"><div className="l">Prob. of Loss</div><div className={"v " + (probLoss < 25 ? "up" : "down")}>{probLoss.toFixed(1)}%</div></div>
        <div className="mc-metric"><div className="l">P5 Terminal</div><div className="v down">{p5.toFixed(0)}</div></div>
        <div className="mc-metric"><div className="l">P50 Terminal</div><div className="v acc">{p50.toFixed(0)}</div></div>
        <div className="mc-metric"><div className="l">P95 Terminal</div><div className="v up">{p95.toFixed(0)}</div></div>
      </div>
      <div className="pane">
        <h5><span>Monte Carlo Fan Chart · 10Y horizon</span><span className="sub">2,000 simulations · log-normal returns</span></h5>
        <div className="body">
          <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: "block" }}>
            {[0, 0.25, 0.5, 0.75, 1].map(t => {
              const yy = pad.t + t * (H - pad.t - pad.b);
              const val = max - t * (max - min);
              return (
                <g key={t}>
                  <line x1={pad.l} x2={W-pad.r} y1={yy} y2={yy} stroke="var(--term-hair)" />
                  <text x={pad.l-6} y={yy+3} textAnchor="end" fontFamily="var(--font-mono)" fontSize="9" fill="var(--fg-muted)">{val.toFixed(0)}</text>
                </g>
              );
            })}
            <line x1={pad.l} x2={W-pad.r} y1={y(100)} y2={y(100)} stroke="var(--term-panel-edge)" strokeDasharray="2 4" />
            {/* outer band p5-p95 */}
            <path d={bandPath(percentiles[4], percentiles[0])} fill="var(--accent)" opacity="0.1" />
            {/* inner band p25-p75 */}
            <path d={bandPath(percentiles[3], percentiles[1])} fill="var(--accent)" opacity="0.2" />
            {/* median */}
            <path d={pathFromArray(percentiles[2])} fill="none" stroke="var(--accent)" strokeWidth="1.8" />
            {/* extremes */}
            <path d={pathFromArray(percentiles[0])} fill="none" stroke="var(--down)" strokeWidth="1" strokeDasharray="2 3" />
            <path d={pathFromArray(percentiles[4])} fill="none" stroke="var(--up)" strokeWidth="1" strokeDasharray="2 3" />
            {/* year labels */}
            {[0,2,4,6,8,10].map(yr => (
              <text key={yr} x={pad.l + (yr/10) * (W - pad.l - pad.r)} y={H-6} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9" fill="var(--fg-muted)">Y{yr}</text>
            ))}
          </svg>
        </div>
      </div>
    </>
  );
}

// ─── ADVISOR TAB ───
function AdvisorTab() {
  return (
    <>
      <KpiRibbon />
      <div className="pane">
        <h5><span>Portfolio Advisor</span><span className="sub">{ADVISOR_INSIGHTS.length} insights · auto-generated from optimization trace</span></h5>
        <div className="body">
          {ADVISOR_INSIGHTS.map((a, i) => {
            const cls = a.severity.toLowerCase();
            return (
              <div key={i} className={"advisor-card " + cls}>
                <div className="ah">
                  <span className={"asev " + cls}>{a.severity}</span>
                  <span className="atag">{a.tag}</span>
                </div>
                <div className="atit">{a.title}</div>
                <div className="abody">{a.body}</div>
                <div className="aacts">
                  {a.actions.map((act, j) => <button key={j} className="aact">{act}</button>)}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

Object.assign(window, {
  RegimeTab, WeightsTab, RiskTab, StressTab, BacktestTab, MonteCarloTab, AdvisorTab,
});
