// The motor seen from the shaft end: an outrunner bell carrying 2·p magnets
// around a fixed stator whose teeth glow with their phase current (warm:
// north, slate: south). Drawn from the simulator's truth, the real rotor
// angle and phase currents, not from what the firmware believes. The
// firmware's planner target is a ghost mark on the scale.
//
// Drag the rotor to turn it by hand: the pointer becomes a stiff spring on
// the shaft (the simulator applies the torque).

const TAU = Math.PI * 2;

// Concentrated double-layer windings: 12N14P "AabBCc aABbcC", repeated for 24N28P.
const PATTERN = [[0, 1], [0, -1], [1, -1], [1, 1], [2, 1], [2, -1], [0, -1], [0, 1], [1, 1], [1, -1], [2, -1], [2, 1]];

export class RotorView {
  constructor(canvas, { onHand }) {
    this.canvas = canvas;
    this.onHand = onHand;
    this.pp = 14;
    this.slots = 24;
    this.rated = 10;
    this.frame = null;
    this.hand = null;
    this.lastAngle = 0;
    this.blur = 0;
    this.lastSent = 0;
    canvas.addEventListener('pointerdown', (e) => this.down(e));
    canvas.addEventListener('pointermove', (e) => this.move(e));
    for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) canvas.addEventListener(ev, () => this.up());
  }

  setMotor(pp, ratedCurrent) {
    this.pp = pp;
    this.slots = Math.round((pp * 12) / 7);
    this.rated = ratedCurrent;
  }

  update(frame) {
    const a = frame.truth.angle;
    if (this.frame) {
      const turnsPerFrame = Math.abs(a - this.frame.truth.angle) / TAU;
      this.blur += (Math.min(1, Math.max(0, (turnsPerFrame - 0.03) / 0.1)) - this.blur) * 0.3;
    }
    this.frame = frame;
  }

  // ---- hand ---------------------------------------------------------------------------------------------
  geometry() {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight;
    const R = Math.min(w, h) / 2 - 14;
    return { w, h, cx: w / 2, cy: h / 2, R };
  }

  pointerAngle(e) {
    const r = this.canvas.getBoundingClientRect();
    const { cx, cy } = this.geometry();
    const x = e.clientX - r.left - cx, y = e.clientY - r.top - cy;
    return { phi: Math.atan2(-y, x), dist: Math.hypot(x, y), x: x + cx, y: y + cy };
  }

  down(e) {
    if (!this.frame) return;
    const p = this.pointerAngle(e);
    if (p.dist > this.geometry().R * 0.97) return;
    this.canvas.setPointerCapture(e.pointerId);
    this.canvas.classList.add('grabbing');
    this.hand = { phi: p.phi, total: 0, start: this.frame.truth.angle, x: p.x, y: p.y };
    this.send(true);
  }

  move(e) {
    if (!this.hand) return;
    const p = this.pointerAngle(e);
    let d = p.phi - this.hand.phi;
    if (d > Math.PI) d -= TAU;
    if (d < -Math.PI) d += TAU;
    this.hand.phi = p.phi;
    this.hand.total += d;
    this.hand.x = p.x;
    this.hand.y = p.y;
    this.send(false);
  }

  up() {
    if (!this.hand) return;
    this.hand = null;
    this.canvas.classList.remove('grabbing');
    this.onHand({ active: false });
  }

  send(force) {
    const now = performance.now();
    if (!force && now - this.lastSent < 30) return;
    this.lastSent = now;
    this.onHand({ active: true, angle: this.hand.start + this.hand.total });
  }

  // ---- drawing ------------------------------------------------------------------------------------------
  css(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }

  draw() {
    const c = this.canvas;
    const dpr = window.devicePixelRatio || 1;
    const { w, h, cx, cy, R } = this.geometry();
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
    }
    const g = c.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    if (!this.frame || R < 20) return;
    const f = this.frame;
    const a = f.truth.angle;
    const P = (r, phi) => [cx + r * Math.cos(phi), cy - r * Math.sin(phi)];
    const arc = (r0, r1, p0, p1) => {
      g.beginPath();
      g.arc(cx, cy, r1, -p0, -p1, true);
      g.arc(cx, cy, r0, -p1, -p0, false);
      g.closePath();
    };
    const ink3 = this.css('--ink-3'), line = this.css('--line'), lineStrong = this.css('--line-strong');
    const north = this.css('--north'), south = this.css('--south'), steel = this.css('--steel'), steel2 = this.css('--steel-2');
    const panel2 = this.css('--panel-2'), accent = this.css('--accent');

    // Scale ring: 10° ticks, fixed to the bench.
    g.strokeStyle = lineStrong;
    g.lineWidth = 1;
    for (let d = 0; d < 360; d += 10) {
      const phi = (d * Math.PI) / 180;
      const len = d % 90 === 0 ? 10 : d % 30 === 0 ? 7 : 4;
      const [x0, y0] = P(R, phi), [x1, y1] = P(R - len, phi);
      g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.stroke();
    }

    // Planner target (firmware frame mapped onto the true angle through the current error).
    const moving = ['Holding', 'Moving', 'Velocity', 'Impedance'].includes(f.state);
    if (moving && Number.isFinite(f.target)) {
      const phi = a + (f.target - f.pos) * TAU;
      const [tx, ty] = P(R - 1, phi);
      g.fillStyle = ink3;
      g.save();
      g.translate(tx, ty);
      g.rotate(-phi);
      g.beginPath(); g.moveTo(0, 0); g.lineTo(9, -6); g.lineTo(9, 6); g.closePath();
      g.globalAlpha = 0.85;
      g.fill();
      g.restore();
    }

    // Rotor bell and magnets.
    const rBellOut = R * 0.88, rBellIn = R * 0.79, rMagIn = R * 0.69;
    g.fillStyle = steel;
    arc(rBellIn, rBellOut, 0, TAU);
    g.fill();
    const poles = this.pp * 2;
    const gap = Math.min(0.08, (TAU / poles) * 0.12);
    if (this.blur > 0.95) {
      g.fillStyle = steel2;
      arc(rMagIn, rBellIn, 0, TAU);
      g.fill();
    } else {
      for (let k = 0; k < poles; k++) {
        const p0 = a + (k * TAU) / poles + gap / 2, p1 = a + ((k + 1) * TAU) / poles - gap / 2;
        g.fillStyle = k % 2 === 0 ? north : south;
        g.globalAlpha = 1 - this.blur * 0.8;
        arc(rMagIn, rBellIn, p0, p1);
        g.fill();
      }
      g.globalAlpha = 1;
    }
    // A mark on the bell so the rotation reads at any pole count.
    g.fillStyle = accent;
    arc(rBellIn + 2, rBellOut - 1, a - 0.035, a + 0.035);
    g.fill();
    const [mx, my] = P(rBellOut + 6, a);
    g.beginPath(); g.arc(mx, my, 3.5, 0, TAU); g.fill();

    // Stator teeth, glowing with the current through their coils.
    const cur = [f.truth.ia, f.truth.ib, f.truth.ic];
    const rToothIn = R * 0.3, rToothOut = R * 0.64, rShoe = R * 0.67;
    const pitch = TAU / this.slots;
    for (let k = 0; k < this.slots; k++) {
      const [phase, pol] = PATTERN[k % 12];
      const mmf = (pol * cur[phase]) / Math.max(this.rated, 0.1);
      const phi = k * pitch;
      // tooth body
      g.fillStyle = lineStrong;
      g.beginPath();
      const half = pitch * 0.17, shoe = pitch * 0.42;
      const pts = [P(rToothIn, phi - half * 1.4), P(rToothOut, phi - half), P(rToothOut, phi - shoe), P(rShoe, phi - shoe),
        P(rShoe, phi + shoe), P(rToothOut, phi + shoe), P(rToothOut, phi + half), P(rToothIn, phi + half * 1.4)];
      g.moveTo(...pts[0]);
      for (const p of pts.slice(1)) g.lineTo(...p);
      g.closePath();
      g.fill();
      // coil
      const glow = Math.min(1, Math.abs(mmf) * 1.4);
      g.fillStyle = mmf >= 0 ? north : south;
      g.globalAlpha = 0.18 + 0.82 * glow;
      arc(rToothIn + (rToothOut - rToothIn) * 0.12, rToothOut - (rToothOut - rToothIn) * 0.08, phi - pitch * 0.36, phi + pitch * 0.36);
      g.fill();
      g.globalAlpha = 1;
    }
    // Hub and shaft.
    g.fillStyle = panel2;
    g.strokeStyle = line;
    g.beginPath(); g.arc(cx, cy, rToothIn * 0.92, 0, TAU); g.fill(); g.stroke();
    g.fillStyle = steel2;
    g.beginPath(); g.arc(cx, cy, R * 0.07, 0, TAU); g.fill();
    // Phase legend in the hub.
    g.font = `500 ${Math.max(10, R * 0.055)}px "IBM Plex Mono", monospace`;
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillStyle = ink3;
    const amps = Math.hypot(f.id, f.iq);
    g.fillText(f.truth.bridge ? `${amps.toFixed(amps < 10 ? 2 : 1)} A` : 'bridge off', cx, cy + R * 0.15);

    // Locked rotor: a clamp across the bell.
    if (f.truth.locked) {
      g.fillStyle = this.css('--bad');
      for (const phi of [Math.PI * 0.5, Math.PI * 1.5]) {
        g.save();
        const [x, y] = P(R * 0.93, phi);
        g.translate(x, y);
        g.rotate(-phi);
        g.fillRect(-8, -14, 16, 28);
        g.restore();
      }
    }

    // The hand.
    if (this.hand) {
      const [rx, ry] = P(rBellOut, a);
      g.strokeStyle = accent;
      g.lineWidth = 2;
      g.setLineDash([4, 4]);
      g.beginPath(); g.moveTo(rx, ry); g.lineTo(this.hand.x, this.hand.y); g.stroke();
      g.setLineDash([]);
      g.fillStyle = accent;
      g.globalAlpha = 0.25;
      g.beginPath(); g.arc(this.hand.x, this.hand.y, 16, 0, TAU); g.fill();
      g.globalAlpha = 1;
    }
  }
}

// The current vector in the rotor frame: d right, q up, with its reference.
export function drawDq(canvas, frame, maxCurrent, trail) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
  const g = canvas.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const cx = w / 2, cy = h / 2, r = Math.min(w, h) / 2 - 10;
  g.strokeStyle = css('--line-strong');
  g.lineWidth = 1;
  g.beginPath(); g.arc(cx, cy, r, 0, TAU); g.stroke();
  g.beginPath(); g.moveTo(cx - r, cy); g.lineTo(cx + r, cy); g.moveTo(cx, cy - r); g.lineTo(cx, cy + r); g.stroke();
  g.fillStyle = css('--ink-3');
  g.font = '10px "IBM Plex Mono", monospace';
  g.textAlign = 'left';
  g.fillText('d', cx + r - 8, cy - 5);
  g.fillText('q', cx + 4, cy - r + 9);
  if (!frame) return;
  const s = r / Math.max(maxCurrent, 0.1);
  g.fillStyle = css('--tr-ref');
  g.beginPath(); g.arc(cx, cy - frame.iqRef * s, 3, 0, TAU); g.fill();
  g.strokeStyle = css('--tr-1');
  g.globalAlpha = 0.35;
  g.beginPath();
  trail.forEach(([d, q], i) => (i ? g.lineTo(cx + d * s, cy - q * s) : g.moveTo(cx + d * s, cy - q * s)));
  g.stroke();
  g.globalAlpha = 1;
  g.lineWidth = 2;
  g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + frame.id * s, cy - frame.iq * s); g.stroke();
  g.fillStyle = css('--tr-1');
  g.beginPath(); g.arc(cx + frame.id * s, cy - frame.iq * s, 3.5, 0, TAU); g.fill();
}
