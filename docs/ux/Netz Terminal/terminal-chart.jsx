// Chart components — SVG candlestick + sparkline

const { useEffect, useRef, useMemo, useState } = React;

// ---------- Sparkline (watchlist) ----------
function Sparkline({ data, color, width = 48, height = 16 }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1" />
    </svg>
  );
}

// ---------- Candlestick chart ----------
function CandleChart({ bars, liveTick, ticker, onHoverBar }) {
  const wrapRef = useRef(null);
  const [size, setSize] = useState({ w: 800, h: 360 });
  const [hoverX, setHoverX] = useState(null);

  useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        const r = e.contentRect;
        setSize({ w: Math.max(300, r.width), h: Math.max(200, r.height) });
      }
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  // Append live tick to last candle
  const effective = useMemo(() => {
    if (!bars || !bars.length) return [];
    if (!liveTick) return bars;
    const copy = bars.slice();
    const last = { ...copy[copy.length - 1] };
    last.c = liveTick.price;
    if (liveTick.price > last.h) last.h = liveTick.price;
    if (liveTick.price < last.l) last.l = liveTick.price;
    copy[copy.length - 1] = last;
    return copy;
  }, [bars, liveTick]);

  const { w, h } = size;
  const padL = 8, padR = 58, padT = 20, padB = 30;
  const chartW = Math.max(100, w - padL - padR);
  const chartH = Math.max(100, h - padT - padB);

  if (!effective.length) {
    return (
      <div ref={wrapRef} style={{ width: "100%", height: "100%", position: "relative" }}>
        <div className="splash-empty">No data · {ticker || "—"}</div>
      </div>
    );
  }

  // Take last N bars to fit nicely
  const maxBars = Math.floor(chartW / 8);
  const visible = effective.slice(-maxBars);
  const lows = visible.map(b => b.l);
  const highs = visible.map(b => b.h);
  const minP = Math.min(...lows);
  const maxP = Math.max(...highs);
  const pad = (maxP - minP) * 0.08 || 1;
  const yMin = minP - pad;
  const yMax = maxP + pad;
  const yRange = yMax - yMin || 1;

  const barW = chartW / visible.length;
  const candleW = Math.max(1.5, Math.min(6, barW * 0.65));

  const yOf = p => padT + chartH - ((p - yMin) / yRange) * chartH;
  const xOf = i => padL + i * barW + barW / 2;

  // Y-axis ticks
  const yTicks = 5;
  const tickValues = Array.from({ length: yTicks }, (_, i) => yMin + (yRange * i) / (yTicks - 1));

  // X-axis labels: show every Nth bar as date
  const xLabelEvery = Math.max(1, Math.floor(visible.length / 6));

  // Last price line
  const lastBar = visible[visible.length - 1];
  const lastPrice = liveTick ? liveTick.price : lastBar.c;
  const firstClose = visible[0].c;
  const chgAbs = lastPrice - firstClose;
  const chgPct = (chgAbs / firstClose) * 100;
  const lineColor = chgAbs >= 0 ? "var(--up)" : "var(--down)";

  // Build line path (for area under curve)
  const linePts = visible.map((b, i) => `${xOf(i).toFixed(1)},${yOf(b.c).toFixed(1)}`).join(" ");
  const areaPath = `M ${xOf(0)},${padT + chartH} L ${visible.map((b, i) => `${xOf(i).toFixed(1)},${yOf(b.c).toFixed(1)}`).join(" L ")} L ${xOf(visible.length - 1)},${padT + chartH} Z`;

  // Hover crosshair
  const hoverIdx = hoverX != null ? Math.max(0, Math.min(visible.length - 1, Math.floor((hoverX - padL) / barW))) : null;
  const hoverBar = hoverIdx != null ? visible[hoverIdx] : null;

  const fmtDate = t => {
    const d = new Date(t * 1000);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };

  return (
    <div ref={wrapRef} style={{ width: "100%", height: "100%", position: "relative" }}>
      <div className="pattern-bg" />
      <svg
        width={w} height={h}
        style={{ display: "block", position: "absolute", inset: 0 }}
        onMouseMove={e => {
          const rect = e.currentTarget.getBoundingClientRect();
          setHoverX(e.clientX - rect.left);
        }}
        onMouseLeave={() => setHoverX(null)}
      >
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={chgAbs >= 0 ? "#3DD39A" : "#FF5C7A"} stopOpacity="0.22" />
            <stop offset="100%" stopColor={chgAbs >= 0 ? "#3DD39A" : "#FF5C7A"} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Gridlines — horizontal */}
        {tickValues.map((v, i) => (
          <g key={`gy${i}`}>
            <line
              x1={padL} x2={padL + chartW}
              y1={yOf(v)} y2={yOf(v)}
              stroke="rgba(102,137,188,0.08)"
              strokeDasharray="2 3"
            />
            <text
              x={padL + chartW + 6}
              y={yOf(v) + 3}
              fill="var(--fg-tertiary)"
              fontSize="9"
              fontFamily="var(--font-mono)"
            >
              {v.toFixed(2)}
            </text>
          </g>
        ))}

        {/* Area under curve */}
        <path d={areaPath} fill="url(#areaGrad)" />

        {/* Candles */}
        {visible.map((b, i) => {
          const up = b.c >= b.o;
          const cx = xOf(i);
          const yO = yOf(b.o);
          const yC = yOf(b.c);
          const yH = yOf(b.h);
          const yL = yOf(b.l);
          const bodyTop = Math.min(yO, yC);
          const bodyH = Math.max(1, Math.abs(yC - yO));
          const fill = up ? "var(--up)" : "var(--down)";
          return (
            <g key={i}>
              <line x1={cx} x2={cx} y1={yH} y2={yL} stroke={fill} strokeWidth="1" opacity="0.85" />
              <rect
                x={cx - candleW / 2}
                y={bodyTop}
                width={candleW}
                height={bodyH}
                fill={fill}
                opacity={up ? 0.65 : 0.85}
              />
            </g>
          );
        })}

        {/* Line overlay */}
        <polyline
          points={linePts}
          fill="none"
          stroke={lineColor}
          strokeWidth="1.25"
          opacity="0.75"
        />

        {/* Last price horizontal line */}
        <line
          x1={padL} x2={padL + chartW}
          y1={yOf(lastPrice)} y2={yOf(lastPrice)}
          stroke="var(--accent)"
          strokeDasharray="3 3"
          strokeWidth="1"
          opacity="0.7"
        />
        <rect
          x={padL + chartW + 1}
          y={yOf(lastPrice) - 7}
          width={52}
          height={14}
          fill="var(--accent)"
        />
        <text
          x={padL + chartW + 5}
          y={yOf(lastPrice) + 3}
          fill="var(--term-void)"
          fontSize="9.5"
          fontFamily="var(--font-mono)"
          fontWeight="700"
        >
          {lastPrice.toFixed(2)}
        </text>

        {/* Pulsing last-tick dot */}
        <circle
          cx={xOf(visible.length - 1)}
          cy={yOf(lastPrice)}
          r="3.5"
          fill="var(--accent)"
        >
          <animate attributeName="r" values="3;7;3" dur="1.6s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="1;0.2;1" dur="1.6s" repeatCount="indefinite" />
        </circle>
        <circle
          cx={xOf(visible.length - 1)}
          cy={yOf(lastPrice)}
          r="2.5"
          fill="var(--accent)"
        />

        {/* Hover crosshair */}
        {hoverBar && hoverIdx != null && (
          <g>
            <line
              x1={xOf(hoverIdx)} x2={xOf(hoverIdx)}
              y1={padT} y2={padT + chartH}
              stroke="var(--fg-tertiary)"
              strokeDasharray="2 3"
              opacity="0.5"
            />
            <line
              x1={padL} x2={padL + chartW}
              y1={yOf(hoverBar.c)} y2={yOf(hoverBar.c)}
              stroke="var(--fg-tertiary)"
              strokeDasharray="2 3"
              opacity="0.5"
            />
            <rect
              x={Math.min(xOf(hoverIdx) + 8, padL + chartW - 140)}
              y={padT + 6}
              width={134}
              height={58}
              fill="rgba(5,8,26,0.95)"
              stroke="var(--term-panel-edge)"
            />
            <g fontFamily="var(--font-mono)" fontSize="9.5" fill="var(--fg-secondary)">
              <text x={Math.min(xOf(hoverIdx) + 16, padL + chartW - 132)} y={padT + 18} fontWeight="600" fill="var(--accent)">
                {fmtDate(hoverBar.t)}
              </text>
              <text x={Math.min(xOf(hoverIdx) + 16, padL + chartW - 132)} y={padT + 30}>O {hoverBar.o.toFixed(2)}</text>
              <text x={Math.min(xOf(hoverIdx) + 76, padL + chartW - 72)} y={padT + 30}>H {hoverBar.h.toFixed(2)}</text>
              <text x={Math.min(xOf(hoverIdx) + 16, padL + chartW - 132)} y={padT + 42}>L {hoverBar.l.toFixed(2)}</text>
              <text x={Math.min(xOf(hoverIdx) + 76, padL + chartW - 72)} y={padT + 42}>C {hoverBar.c.toFixed(2)}</text>
              <text x={Math.min(xOf(hoverIdx) + 16, padL + chartW - 132)} y={padT + 54} fill="var(--fg-muted)">V {(hoverBar.v / 1e6).toFixed(2)}M</text>
            </g>
          </g>
        )}

        {/* X-axis labels */}
        {visible.map((b, i) => (
          i % xLabelEvery === 0 && (
            <text
              key={`xl${i}`}
              x={xOf(i)}
              y={padT + chartH + 14}
              textAnchor="middle"
              fill="var(--fg-muted)"
              fontSize="9"
              fontFamily="var(--font-mono)"
            >
              {fmtDate(b.t)}
            </text>
          )
        ))}

        {/* Ticker watermark */}
        <text
          x={padL + 8}
          y={padT + 14}
          fill="var(--fg-dim)"
          fontSize="10"
          fontFamily="var(--font-mono)"
          letterSpacing="0.1em"
          opacity="0.7"
        >
          {ticker} · Daily
        </text>
      </svg>
    </div>
  );
}

Object.assign(window, { Sparkline, CandleChart });
