// Scope: the 1 kHz telemetry stream in a ring buffer (30 s), drawn on a
// canvas with min/max decimation per pixel column; or one 30 kHz capture
// (every PWM period of a short window).

const CAPACITY = 32768;

export const GROUPS = {
  current: { label: 'Current', unit: 'A', traces: [
    { k: 'iq', name: 'iq', color: '--tr-1' },
    { k: 'iqRef', name: 'iq ref', color: '--tr-ref', dash: true },
    { k: 'id', name: 'id', color: '--tr-2' },
  ] },
  position: { label: 'Position', unit: 'turns', traces: [
    { k: 'pos', name: 'position', color: '--tr-1' },
    { k: 'target', name: 'planner', color: '--tr-ref', dash: true },
  ] },
  velocity: { label: 'Velocity', unit: 'turns/s', traces: [
    { k: 'vel', name: 'velocity', color: '--tr-1' },
    { k: 'tvel', name: 'planner', color: '--tr-ref', dash: true },
  ] },
  torque: { label: 'Torque', unit: 'N·m', traces: [
    { k: 'torque', name: 'firmware Kt·iq', color: '--tr-1' },
    { k: 'torqueTrue', name: 'true', color: '--tr-3', dash: true },
  ] },
  voltage: { label: 'Voltage', unit: 'V', traces: [
    { k: 'vq', name: 'vq', color: '--tr-1' },
    { k: 'vd', name: 'vd', color: '--tr-2' },
  ] },
  bus: { label: 'Bus', unit: 'V', traces: [{ k: 'vbus', name: 'V bus', color: '--tr-4' }] },
  supply: { label: 'Supply', unit: 'A', traces: [
    { k: 'isup', name: 'from supply', color: '--tr-4' },
    { k: 'ibus', name: 'firmware estimate', color: '--tr-ref', dash: true },
  ] },
  thermal: { label: 'Thermal', unit: '°C', traces: [
    { k: 'tfet', name: 'FET', color: '--tr-2' },
    { k: 'tmot', name: 'winding', color: '--tr-4' },
  ] },
};

export const CAPTURE_GROUPS = {
  phases: { label: 'Phase currents', unit: 'A', traces: [
    { k: 'ia', name: 'ia', color: '--tr-1' }, { k: 'ib', name: 'ib', color: '--tr-2' }, { k: 'ic', name: 'ic', color: '--tr-3' },
    { k: 'ma', name: 'ADC a', color: '--tr-1', dots: true }, { k: 'mb', name: 'ADC b', color: '--tr-2', dots: true },
    { k: 'mc', name: 'ADC c', color: '--tr-3', dots: true },
  ] },
  dq: { label: 'dq', unit: 'A', traces: [
    { k: 'iq', name: 'iq', color: '--tr-1' }, { k: 'iqRef', name: 'iq ref', color: '--tr-ref', dash: true },
    { k: 'id', name: 'id', color: '--tr-2' },
  ] },
  duty: { label: 'Duties', unit: '', traces: [
    { k: 'da', name: 'A', color: '--tr-1' }, { k: 'db', name: 'B', color: '--tr-2' }, { k: 'dc', name: 'C', color: '--tr-3' },
  ] },
  volts: { label: 'Voltage', unit: 'V', traces: [
    { k: 'vq', name: 'vq', color: '--tr-1' }, { k: 'vd', name: 'vd', color: '--tr-2' },
  ] },
};

const KEYS = ['t', ...new Set(Object.values(GROUPS).flatMap((g) => g.traces.map((t) => t.k)))];

function niceStep(span, target) {
  const raw = span / target;
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

function fmt(v, step) {
  const d = Math.max(0, Math.min(6, -Math.floor(Math.log10(step) + 1e-9)));
  return v.toFixed(d);
}

export class Scope {
  constructor(canvas, legend) {
    this.canvas = canvas;
    this.legend = legend;
    this.buf = Object.fromEntries(KEYS.map((k) => [k, new Float64Array(CAPACITY)]));
    this.head = 0;
    this.count = 0;
    this.group = 'current';
    this.window = 5;
    this.frozen = false;
    this.frozenAt = null;
    this.capture = null;
    this.captureGroup = 'phases';
    this.hover = null;
    canvas.addEventListener('pointermove', (e) => {
      const r = canvas.getBoundingClientRect();
      this.hover = (e.clientX - r.left) / r.width;
    });
    canvas.addEventListener('pointerleave', () => { this.hover = null; });
  }

  push(series) {
    const n = series.t.length;
    for (let i = 0; i < n; i++) {
      for (const k of KEYS) {
        const v = series[k] ? series[k][i] : NaN;
        this.buf[k][this.head] = v === null ? NaN : v;
      }
      this.head = (this.head + 1) % CAPACITY;
      this.count = Math.min(this.count + 1, CAPACITY);
    }
  }

  clear() { this.head = 0; this.count = 0; }

  latest(k) {
    if (!this.count) return NaN;
    return this.buf[k][(this.head - 1 + CAPACITY) % CAPACITY];
  }

  setFrozen(on) {
    this.frozen = on;
    this.frozenAt = on ? { head: this.head, count: this.count } : null;
  }

  // ---- drawing --------------------------------------------------------------------------------------------
  css(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

  draw() {
    const c = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
    }
    const g = c.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const view = this.capture ? this.captureView() : this.liveView();
    if (!view) {
      g.fillStyle = this.css('--ink-3');
      g.font = '13px "IBM Plex Sans", system-ui';
      g.textAlign = 'center';
      g.fillText('Waiting for the simulator…', w / 2, h / 2);
      return;
    }
    this.render(g, w, h, view);
  }

  liveView() {
    if (this.count < 2) return null;
    const head = this.frozen ? this.frozenAt.head : this.head;
    const count = this.frozen ? this.frozenAt.count : this.count;
    const t = this.buf.t;
    const last = (head - 1 + CAPACITY) % CAPACITY;
    const tEnd = t[last];
    const tStart = tEnd - this.window;
    // Walk back to the first sample in the window.
    let n = 0;
    while (n < count - 1 && t[(last - n - 1 + CAPACITY) % CAPACITY] >= tStart) n++;
    const first = (last - n + CAPACITY) % CAPACITY;
    const len = n + 1;
    const group = GROUPS[this.group];
    return {
      group, len, x0: tStart, x1: tEnd, xUnit: 's', xRel: true,
      x: (i) => t[(first + i) % CAPACITY],
      y: (k, i) => this.buf[k][(first + i) % CAPACITY],
    };
  }

  captureView() {
    const cap = this.capture;
    const group = CAPTURE_GROUPS[this.captureGroup];
    const len = cap.ia.length;
    const dtMs = cap.dt * 1000;
    return {
      group, len, x0: 0, x1: (len - 1) * dtMs, xUnit: 'ms', xRel: false,
      x: (i) => i * dtMs,
      y: (k, i) => (cap[k] ? cap[k][i] : NaN),
    };
  }

  render(g, w, h, v) {
    const left = 56, right = 12, top = 10, bottom = 24;
    const pw = w - left - right, ph = h - top - bottom;
    const traces = v.group.traces;
    // Y range over the visible samples.
    let lo = Infinity, hi = -Infinity;
    for (const tr of traces) {
      for (let i = 0; i < v.len; i++) {
        const y = v.y(tr.k, i);
        if (Number.isFinite(y)) { lo = Math.min(lo, y); hi = Math.max(hi, y); }
      }
    }
    if (!Number.isFinite(lo)) { lo = -1; hi = 1; }
    const minSpan = { A: 0.2, 'turns': 0.01, 'turns/s': 0.2, 'N·m': 0.01, V: 0.5, '°C': 2, '': 0.1 }[v.group.unit] ?? 0.1;
    if (hi - lo < minSpan) { const mid = (hi + lo) / 2; lo = mid - minSpan / 2; hi = mid + minSpan / 2; }
    const pad = (hi - lo) * 0.08;
    lo -= pad; hi += pad;
    const step = niceStep(hi - lo, Math.max(3, Math.round(ph / 50)));
    const X = (x) => left + ((x - v.x0) / (v.x1 - v.x0 || 1)) * pw;
    const Y = (y) => top + (1 - (y - lo) / (hi - lo)) * ph;

    // Grid and labels.
    g.font = '11px "IBM Plex Mono", ui-monospace, monospace';
    g.strokeStyle = this.css('--line');
    g.fillStyle = this.css('--ink-3');
    g.lineWidth = 1;
    g.textAlign = 'right';
    g.textBaseline = 'middle';
    for (let y = Math.ceil(lo / step) * step; y <= hi; y += step) {
      const py = Math.round(Y(y)) + 0.5;
      g.beginPath(); g.moveTo(left, py); g.lineTo(left + pw, py); g.stroke();
      g.fillText(fmt(y, step), left - 8, py);
    }
    if (lo < 0 && hi > 0) {
      g.strokeStyle = this.css('--line-strong');
      const py = Math.round(Y(0)) + 0.5;
      g.beginPath(); g.moveTo(left, py); g.lineTo(left + pw, py); g.stroke();
    }
    g.textAlign = 'center';
    g.textBaseline = 'top';
    g.strokeStyle = this.css('--line');
    const span = v.x1 - v.x0;
    const xs = niceStep(span, Math.max(3, Math.round(pw / 110)));
    for (let x = Math.ceil(v.x0 / xs) * xs; x <= v.x1 + 1e-9; x += xs) {
      const px = Math.round(X(x)) + 0.5;
      g.beginPath(); g.moveTo(px, top); g.lineTo(px, top + ph); g.stroke();
      const label = v.xRel ? `${fmt(x - v.x1, xs)} s` : `${fmt(x, xs)} ${v.xUnit}`;
      g.fillText(label, px, top + ph + 6);
    }
    g.textAlign = 'left';
    g.textBaseline = 'top';
    g.fillText(v.group.unit, 6, top);

    // Traces.
    g.save();
    g.beginPath(); g.rect(left, top, pw, ph); g.clip();
    for (const tr of traces) {
      g.strokeStyle = this.css(tr.color);
      g.fillStyle = g.strokeStyle;
      g.lineWidth = tr.dash ? 1.25 : 1.6;
      g.setLineDash(tr.dash ? [5, 4] : []);
      if (tr.dots) {
        for (let i = 0; i < v.len; i++) {
          const y = v.y(tr.k, i);
          if (Number.isFinite(y)) g.fillRect(X(v.x(i)) - 1.5, Y(y) - 1.5, 3, 3);
        }
        continue;
      }
      g.beginPath();
      const perPx = v.len / pw;
      if (perPx > 2) {
        // min/max per pixel column
        let col = -1, mn = 0, mx = 0, started = false;
        for (let i = 0; i < v.len; i++) {
          const y = v.y(tr.k, i);
          if (!Number.isFinite(y)) continue;
          const px = Math.floor(X(v.x(i)));
          if (px !== col) {
            if (col >= 0) {
              if (!started) { g.moveTo(col, Y(mn)); started = true; } else g.lineTo(col, Y(mn));
              g.lineTo(col, Y(mx));
            }
            col = px; mn = mx = y;
          } else { mn = Math.min(mn, y); mx = Math.max(mx, y); }
        }
        if (col >= 0) { if (!started) g.moveTo(col, Y(mn)); else g.lineTo(col, Y(mn)); g.lineTo(col, Y(mx)); }
      } else {
        let started = false;
        for (let i = 0; i < v.len; i++) {
          const y = v.y(tr.k, i);
          if (!Number.isFinite(y)) { started = false; continue; }
          if (!started) { g.moveTo(X(v.x(i)), Y(y)); started = true; } else g.lineTo(X(v.x(i)), Y(y));
        }
      }
      g.stroke();
    }
    g.restore();
    g.setLineDash([]);

    // Hover cursor.
    let at = v.len - 1;
    if (this.hover !== null) {
      const px = this.hover * w;
      if (px >= left && px <= left + pw) {
        const xv = v.x0 + ((px - left) / pw) * (v.x1 - v.x0);
        let lo2 = 0, hi2 = v.len - 1;
        while (hi2 - lo2 > 1) { const m = (lo2 + hi2) >> 1; if (v.x(m) < xv) lo2 = m; else hi2 = m; }
        at = hi2;
        g.strokeStyle = this.css('--ink-3');
        g.setLineDash([3, 3]);
        g.beginPath(); g.moveTo(Math.round(px) + 0.5, top); g.lineTo(Math.round(px) + 0.5, top + ph); g.stroke();
        g.setLineDash([]);
      }
    }
    this.renderLegend(traces, (k) => v.y(k, at), v.group.unit);
  }

  renderLegend(traces, value, unit) {
    const html = traces
      .filter((tr) => !tr.dots)
      .map((tr) => {
        const val = value(tr.k);
        const color = this.css(tr.color);
        const txt = Number.isFinite(val) ? (Math.abs(val) >= 100 ? val.toFixed(1) : Math.abs(val) >= 10 ? val.toFixed(2) : val.toFixed(3)) : '—';
        return `<span><i class="${tr.dash ? 'dash' : ''}" style="background:${color};color:${color}"></i>${tr.name} <b>${txt}</b></span>`;
      })
      .join('') + (unit ? `<span class="muted">${unit}</span>` : '');
    if (html !== this.legendHtml) {
      this.legend.innerHTML = html;
      this.legendHtml = html;
    }
  }
}
