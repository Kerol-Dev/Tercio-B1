// Tercio B1 Simulator: the page. Telemetry arrives over Server-Sent Events
// from server.mjs, commands go back as JSON POSTs, in order.
import { Scope, GROUPS, CAPTURE_GROUPS } from './scope.js';
import { RotorView, drawDq } from './rotor.js';

const $ = (id) => document.getElementById(id);
const TAU = Math.PI * 2;
const S = { info: null, frame: null, cal: null, lastCalPhase: 'idle', connected: false, trail: [], frames: 0, impTarget: null };

// ---- Transport ---------------------------------------------------------------------------------------------
let queue = Promise.resolve();
function cmd(c) {
  queue = queue.then(() => fetch('/cmd', { method: 'POST', body: JSON.stringify(c) }).catch(() => {}));
  return queue;
}
function throttle(fn, ms) {
  let last = 0, timer = null, args = null;
  return (...a) => {
    args = a;
    const now = performance.now();
    if (now - last >= ms) { last = now; fn(...args); return; }
    clearTimeout(timer);
    timer = setTimeout(() => { last = performance.now(); fn(...args); }, ms - (now - last));
  };
}

function connect() {
  const es = new EventSource('/events');
  es.onopen = () => setLink(true);
  es.onerror = () => setLink(false);
  es.onmessage = (e) => {
    const m = JSON.parse(e.data);
    ({ info: onInfo, frame: onFrame, calibration: onCalibration, capture: onCapture, event: onEvent })[m.type]?.(m);
  };
}
function setLink(on) {
  S.connected = on;
  $('link').textContent = on ? 'Connected' : 'Reconnecting';
  $('link').dataset.tone = on ? 'good' : 'warn';
}

// ---- Formatting ----------------------------------------------------------------------------------------------
const f = (v, d = 2) => (Number.isFinite(v) ? v.toFixed(d) : '—');
const sig = (v, n = 3) => (Number.isFinite(v) ? Number(v.toPrecision(n)).toString() : '—');
function engineering(v, unit) {
  if (!Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1) return `${sig(v, 4)} ${unit}`;
  if (a >= 1e-3) return `${sig(v * 1e3, 4)} m${unit}`;
  if (a >= 1e-6) return `${sig(v * 1e6, 4)} µ${unit}`;
  return `${sig(v * 1e9, 4)} n${unit}`;
}
function clock(t) {
  const m = Math.floor(t / 60);
  return `${m}:${(t - m * 60).toFixed(3).padStart(6, '0')}`;
}

// ---- Info: the motor, its profile, the bench settings -----------------------------------------------------
function onInfo(m) {
  S.info = m;
  const p = m.profile, mo = m.motor;
  rotor.setMotor(mo.pp, Math.max(p.maxCurrent * 0.6, mo.ratedCurrent * 0.5));
  $('motor-name').textContent = mo.name;
  const slots = Math.round((mo.pp * 12) / 7);
  $('motor-sub').textContent = `${slots}N${mo.pp * 2}P · Kt ${sig(mo.Kt, 3)} N·m/A · ${sig(mo.Kv, 3)} rpm/V`;
  $('motors').innerHTML = m.profiles.map((q) => `
    <button class="motor-card" data-id="${q.id}" aria-pressed="${q.id === mo.id}">
      <span class="name">${q.name}${q.stored ? '<span class="chip" data-tone="good">calibrated</span>' : ''}</span>
      <span class="specs">R ${engineering(q.R, 'Ω')} · L ${engineering(q.L, 'H')} · ${q.pp} pp</span>
      <span class="specs">${sig(q.Kv, 3)} rpm/V · Kt ${sig(q.Kt, 3)} N·m/A · ${q.maxCurrent} A max</span>
    </button>`).join('');
  $('cal-current').value = p.calCurrent;
  setRange('vel', -p.maxVelocity, p.maxVelocity, p.maxVelocity / 300);
  setRange('pos-vmax', 0.1, p.maxVelocity, 0.1, Math.min(10, p.maxVelocity * 0.5));
  setRange('pos-amax', 1, p.maxAcceleration, 1, p.maxAcceleration * 0.25);
  setRange('vel-a', 1, p.maxAcceleration, 1, p.maxAcceleration * 0.25);
  setRange('tq', -p.maxTorque, p.maxTorque, p.maxTorque / 500);
  setRange('tq-vl', 0.5, p.maxVelocity, 0.5, p.maxVelocity * 0.5);
  setRange('imp-tff', -p.maxTorque, p.maxTorque, p.maxTorque / 500, 0);
  setRange('load', -p.maxTorque * 1.2, p.maxTorque * 1.2, p.maxTorque / 250, 0);
  for (const k of ['kp', 'kd', 'ki', 'kv', 'kvi']) $(`g-${k}`).value = sig(m.gains[k], 4);
  $('g-timeout').value = m.timeout;
  // bench
  checkSeg('supply-kind', m.supply.kind);
  $('volts').value = m.supply.volts;
  $('limit').value = m.supply.limit;
  $('connected').checked = m.supply.connected;
  $('limit-row').hidden = m.supply.kind !== 'bench';
  $('supply-hint').hidden = m.supply.kind !== 'bench';
  $('vds').value = String(m.vdsLevel);
  $('ambient').value = m.ambient;
  checkSeg('cooling', String(m.cooling));
  labels();
  renderSteps();
}

function setRange(id, min, max, step, value) {
  const el = $(id);
  el.min = min; el.max = max; el.step = step;
  if (value !== undefined) el.value = value;
  else el.value = Math.min(max, Math.max(min, Number(el.value)));
}

// ---- Frames ------------------------------------------------------------------------------------------------
const STATE_TONE = { Disabled: '', Holding: 'good', Moving: 'accent', Velocity: 'accent', Torque: 'accent', Impedance: 'accent', Calibrating: 'busy', Fault: 'bad' };
const FAULTS = { 0: 'FET over-temperature', 2: 'Driver fault (nFAULT)', 4: 'Encoder lost', 6: 'Calibration failed', 8: 'Command timeout', 9: 'Bus over-voltage', 10: 'Bus under-voltage', 11: 'Over-current', 12: 'Motor over-temperature' };
const WARNINGS = { 0: 'Derating', 8: 'Regen limited' };

function onFrame(m) {
  S.frame = m;
  scope.push(m.series);
  rotor.update(m);
  if (m.calPhase !== 'idle' && m.calPhase !== 'done' && m.calPhase !== 'failed') S.lastCalPhase = m.calPhase;
  S.trail.push([m.id, m.iq]);
  if (S.trail.length > 40) S.trail.shift();
  if (S.frames++ % 3 === 0) readouts(m);
}

function readouts(m) {
  const t = m.truth;
  $('clock').textContent = clock(m.time);
  $('run').textContent = m.paused ? 'Paused' : `${f(m.realtime, 2)}× real time`;
  $('run').dataset.tone = m.paused ? 'warn' : m.realtime > 0.9 * m.speed || m.speed > 50 ? 'good' : 'warn';
  $('pause-icon').innerHTML = m.paused ? '<path d="M8 5v14l11-7z"/>' : '<path d="M7 5h3v14H7zM14 5h3v14h-3z"/>';
  $('pause').setAttribute('aria-label', m.paused ? 'Resume the simulation' : 'Pause the simulation');

  const turnFrac = ((m.pos % 1) + 1) % 1;
  $('r-pos').textContent = `${f(m.pos, 4)} turns`;
  $('r-pos2').textContent = `${f(turnFrac * 360, 1)}° in the turn`;
  $('r-vel').textContent = `${f(m.vel, 2)} turns/s`;
  $('r-vel2').textContent = `${f(m.vel * 60, 0)} rpm · true ${f((t.omega / TAU) * 60, 0)}`;
  $('r-tq').textContent = `${f(m.torque, 3)} N·m`;
  $('r-tq2').textContent = `true ${f(t.torque, 3)} · load ${f(t.load, 3)}`;
  $('r-iq').textContent = `${f(m.iq, 2)} A`;
  $('r-id').textContent = `id ${f(m.id, 2)} A · ref ${f(m.iqRef, 2)} A`;
  $('r-bus').textContent = `${f(t.vbus, 2)} V`;
  $('r-bus2').textContent = `${f(t.isup, 2)} A from supply`;
  $('r-loss').textContent = `${f(t.loss, 2)} W`;
  $('r-loss2').textContent = `winding R ${engineering(t.R, 'Ω')}${m.derate < 1 ? ` · derate ${f(m.derate * 100, 0)} %` : ''}`;
  temp('tfet', m.tfet, t.tboard);
  temp('tmot', m.tmot, t.tmotor);
  $('supply-read').textContent = `${f(t.vbus, 1)} V · ${f(t.isup, 2)} A`;
  // Switches follow the simulator (it outlives a page reload).
  if (document.activeElement !== $('magnet')) $('magnet').checked = t.magnet;
  if (document.activeElement !== $('locked')) $('locked').checked = t.locked;
  $('load-read').textContent = `${f(t.load, 3)} N·m`;

  // Joint state.
  $('state').textContent = m.state;
  $('state-dot').dataset.tone = STATE_TONE[m.state] ?? '';
  const cal = $('cal-chip');
  cal.textContent = m.calibrated ? 'Calibrated' : m.state === 'Calibrating' ? 'Calibrating' : 'Not calibrated';
  cal.dataset.tone = m.calibrated ? 'good' : m.state === 'Calibrating' ? 'busy' : 'warn';
  const on = !['Disabled', 'Fault', 'Calibrating'].includes(m.state);
  $('enable').disabled = on || !m.calibrated || m.state !== 'Disabled';
  $('enable').textContent = on ? 'Enabled' : 'Enable';
  $('stop').disabled = !on;
  $('calibrate').disabled = m.state === 'Calibrating' || m.state === 'Fault';
  $('calibrate').textContent = m.state === 'Calibrating' ? 'Calibrating…' : m.calibrated ? 'Recalibrate' : 'Calibrate';
  const faultChips = Object.entries(FAULTS).filter(([b]) => m.faults & (1 << b)).map(([, n]) => `<span class="chip" data-tone="bad">${n}</span>`);
  const warnChips = Object.entries(WARNINGS).filter(([b]) => m.warnings & (1 << b)).map(([, n]) => `<span class="chip" data-tone="warn">${n}</span>`);
  if (!t.magnet) warnChips.push('<span class="chip" data-tone="warn">No magnet</span>');
  if (t.driverFault) warnChips.push('<span class="chip" data-tone="bad">nFAULT low</span>');
  const html = faultChips.concat(warnChips).join('') + (m.faults ? '<button class="btn btn-secondary" id="clear" type="button">Clear faults</button>' : '');
  if (html !== S.faultHtml) { $('faults').innerHTML = html; S.faultHtml = html; }
  if (m.state === 'Calibrating' || S.calPhaseShown !== m.calPhase) { renderSteps(); S.calPhaseShown = m.calPhase; }
}

function temp(id, fw, truth) {
  $(`r-${id}`).textContent = `${f(fw, 1)} °C`;
  const bar = $(`b-${id}`);
  bar.style.width = `${Math.min(100, Math.max(0, ((truth - 0) / 120) * 100))}%`;
  bar.style.background = truth > 100 ? 'var(--bad)' : truth > 75 ? 'var(--warn)' : 'var(--good)';
}

// ---- Calibration ----------------------------------------------------------------------------------------
const STEPS = [
  ['offsets', 'Sense offsets'],
  ['resistance', 'Resistance'],
  ['inductance', 'Inductance'],
  ['polePairs', 'Pole pairs · direction'],
  ['encoderOffset', 'Encoder offset'],
  ['fluxLinkage', 'Flux linkage · Kt'],
];
function onCalibration(m) {
  S.cal = m;
  renderSteps();
}
function compare(found, truth, fmtv) {
  if (!found) return '';
  const err = truth ? Math.abs(found - truth) / Math.abs(truth) : 0;
  return `${fmtv(found)} <em>· true ${fmtv(truth)}</em> <span class="${err < 0.05 ? 'ok' : 'off'}">${err < 0.05 ? '✓' : `${f(err * 100, 1)} %`}</span>`;
}
function renderSteps() {
  const phase = S.frame?.calPhase ?? 'idle';
  const cal = S.cal;
  const active = STEPS.findIndex(([k]) => k === phase);
  const failedAt = phase === 'failed' ? STEPS.findIndex(([k]) => k === S.lastCalPhase) : -1;
  const done = phase === 'done' || (S.frame?.calibrated && phase === 'idle');
  const fd = cal?.found ?? {}, tr = cal?.truth ?? {};
  const value = {
    offsets: fd.offsets && fd.offsets[0] ? `${fd.offsets.map((x) => x.toFixed(0)).join(' · ')} <em>codes</em>` : '',
    resistance: compare(fd.R, tr.R, (v) => engineering(v, 'Ω')),
    inductance: compare(fd.L, tr.L, (v) => engineering(v, 'H')),
    polePairs: fd.pp ? `${fd.pp} · ${fd.dir > 0 ? 'fwd' : 'rev'} <em>· true ${tr.pp} · ${tr.dir > 0 ? 'fwd' : 'rev'}</em> <span class="${fd.pp === tr.pp && fd.dir === tr.dir ? 'ok' : 'off'}">${fd.pp === tr.pp && fd.dir === tr.dir ? '✓' : '✗'}</span>` : '',
    encoderOffset: fd.pp ? (() => {
      if (!fd.offset && !(phase === 'fluxLinkage' || phase === 'done' || done)) return '';
      let e = fd.offset - tr.offset; e = ((e + 540) % 360) - 180;
      return `${f(fd.offset, 1)}° <em>· error ${f(e, 2)}° el.</em> <span class="${Math.abs(e) < 3 ? 'ok' : 'off'}">${Math.abs(e) < 3 ? '✓' : '✗'}</span>`;
    })() : '',
    fluxLinkage: compare(fd.lambda, tr.lambda, (v) => engineering(v, 'Wb')),
  };
  $('steps').innerHTML = STEPS.map(([k, name], i) => {
    let s = 'pending';
    if (done) s = 'done';
    else if (failedAt >= 0) s = i < failedAt ? 'done' : i === failedAt ? 'failed' : 'pending';
    else if (active >= 0) s = i < active ? 'done' : i === active ? 'active' : 'pending';
    return `<li data-s="${s}"><span class="ico"></span><span>${name}</span><span class="val">${s === 'pending' || s === 'active' && !value[k] ? '' : value[k]}</span></li>`;
  }).join('');
  const st = $('cal-state');
  st.textContent = done ? 'Stored' : phase === 'failed' ? 'Failed' : active >= 0 ? `${active + 1} / ${STEPS.length}` : 'Not run';
  st.dataset.tone = done ? 'good' : phase === 'failed' ? 'bad' : active >= 0 ? 'busy' : 'warn';
}

// ---- Capture ---------------------------------------------------------------------------------------------
function onCapture(m) {
  scope.capture = m;
  $('capture').textContent = 'Back to live';
  buildGroups();
}

// ---- Events ----------------------------------------------------------------------------------------------
function onEvent(m) {
  const li = document.createElement('li');
  li.dataset.level = m.level;
  li.innerHTML = `<time>${S.frame ? clock(S.frame.time).slice(0, -2) : '—'}</time><span></span>`;
  li.lastChild.textContent = m.text;
  const log = $('log');
  log.prepend(li);
  while (log.children.length > 80) log.lastChild.remove();
}

// ---- Commands from the joint panel ------------------------------------------------------------------------
async function ensureEnabled() {
  const st = S.frame?.state;
  if (st === 'Disabled' && S.frame.calibrated) await cmd({ cmd: 'enable' });
}
function labels() {
  const v = (id) => { const x = Number($(id).value); return Math.abs(x) < 1e-9 ? 0 : x; };  // range steps leave ±1e-16
  $('volts-v').textContent = `${v('volts')} V`;
  $('limit-v').textContent = `${v('limit').toFixed(1)} A`;
  $('load-v').textContent = `${v('load').toFixed(3)} N·m`;
  $('brake-v').textContent = v('brake') ? `${v('brake')} %` : 'off';
  $('ambient-v').textContent = `${v('ambient')} °C`;
  $('pos-vmax-v').textContent = `${v('pos-vmax').toFixed(1)} turns/s`;
  $('pos-amax-v').textContent = `${v('pos-amax').toFixed(0)} turns/s²`;
  $('vel-v').textContent = `${v('vel').toFixed(2)} turns/s`;
  $('vel-a-v').textContent = `${v('vel-a').toFixed(0)} turns/s²`;
  $('tq-v').textContent = `${v('tq').toFixed(3)} N·m`;
  $('tq-vl-v').textContent = `${v('tq-vl').toFixed(1)} turns/s`;
  const [kp, kd] = impGains();
  $('imp-kp-v').textContent = `${sig(kp, 3)} N·m/turn`;
  $('imp-kd-v').textContent = `${sig(kd, 3)} N·m·s/turn`;
  $('imp-tff-v').textContent = `${v('imp-tff').toFixed(3)} N·m`;
}
function impGains() {
  const g = S.info?.gains ?? { kp: 1, kd: 0.01 };
  return [(Number($('imp-kp').value) / 100) * g.kp * 3, (Number($('imp-kd').value) / 100) * g.kd * 3];
}
const sendVelocity = throttle(() => cmd({ cmd: 'velocity', value: Number($('vel').value), accel: Number($('vel-a').value) }), 50);
const sendTorque = throttle(() => cmd({ cmd: 'torque', value: Number($('tq').value), maxVelocity: Number($('tq-vl').value) }), 50);
const sendImpedance = throttle(() => {
  if (S.impTarget === null) return;
  const [kp, kd] = impGains();
  cmd({ cmd: 'impedance', position: S.impTarget, velocity: 0, kp, kd, torque: Number($('imp-tff').value) });
}, 50);
async function move(target) {
  await ensureEnabled();
  $('pos-target').value = Number(target.toFixed(4));
  cmd({ cmd: 'move', position: target, velocity: Number($('pos-vmax').value), accel: Number($('pos-amax').value) });
}

// ---- Wiring ----------------------------------------------------------------------------------------------
function checkSeg(id, value) {
  for (const b of $(id).querySelectorAll('button')) b.setAttribute('aria-checked', String(b.dataset.v === value));
}
function seg(id, onPick) {
  $(id).addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    checkSeg(id, b.dataset.v);
    onPick(b.dataset.v);
  });
}

function buildGroups() {
  const groups = scope.capture ? CAPTURE_GROUPS : GROUPS;
  const current = scope.capture ? scope.captureGroup : scope.group;
  $('scope-group').innerHTML = Object.entries(groups).map(([k, g]) => `<button role="radio" data-v="${k}" aria-checked="${k === current}">${g.label}</button>`).join('');
  $('scope-window').hidden = !!scope.capture;
  $('freeze').hidden = !!scope.capture;
}

const scope = new Scope($('scope'), $('legend'));
const rotor = new RotorView($('rotor'), { onHand: (h) => cmd({ cmd: 'hand', ...h, active: h.active ? 1 : 0 }) });

function wire() {
  buildGroups();
  seg('scope-group', (v) => { if (scope.capture) scope.captureGroup = v; else scope.group = v; });
  seg('scope-window', (v) => { scope.window = Number(v); });
  $('freeze').onclick = () => { scope.setFrozen(!scope.frozen); $('freeze').dataset.active = String(scope.frozen); $('freeze').textContent = scope.frozen ? 'Frozen' : 'Freeze'; };
  $('capture').onclick = () => {
    if (scope.capture) { scope.capture = null; $('capture').textContent = 'Capture 30 kHz'; buildGroups(); return; }
    $('capture').textContent = 'Capturing…';
    cmd({ cmd: 'capture', ms: 20 });
  };
  seg('speed', (v) => cmd({ cmd: 'speed', value: Number(v) }));
  $('pause').onclick = () => cmd({ cmd: 'pause', value: S.frame?.paused ? 0 : 1 });
  $('theme').onclick = () => {
    const order = ['system', 'light', 'dark'];
    let cur = 'system';
    try { cur = localStorage.getItem('tercio.sim.theme') || 'system'; } catch {}
    const next = order[(order.indexOf(cur) + 1) % 3];
    applyTheme(next);
    try { localStorage.setItem('tercio.sim.theme', next); } catch {}
  };

  // bench
  $('motors').addEventListener('click', (e) => {
    const b = e.target.closest('.motor-card');
    if (b && b.dataset.id !== S.info?.motor.id) { scope.clear(); cmd({ cmd: 'motor', id: b.dataset.id }); }
  });
  $('forget').onclick = () => cmd({ cmd: 'forget' });
  seg('supply-kind', (v) => cmd({ cmd: 'supply', kind: v }));
  const supply = throttle(() => cmd({ cmd: 'supply', volts: Number($('volts').value), limit: Number($('limit').value) }), 120);
  for (const id of ['volts', 'limit']) $(id).addEventListener('input', () => { labels(); supply(); });
  $('connected').onchange = () => cmd({ cmd: 'supply', connected: $('connected').checked ? 1 : 0 });
  $('unplug').onclick = () => { $('connected').checked = false; cmd({ cmd: 'supply', connected: 0 }); };
  const load = throttle(() => {
    const p = S.info?.profile ?? { maxTorque: 1, maxVelocity: 10 };
    const b = Number($('brake').value) / 100;
    cmd({ cmd: 'load', torque: Number($('load').value), brake: (b * b * p.maxTorque) / (0.2 * p.maxVelocity * TAU) });
  }, 80);
  for (const id of ['load', 'brake']) $(id).addEventListener('input', () => { labels(); load(); });
  $('flywheel').onchange = () => cmd({ cmd: 'load', inertia: $('flywheel').checked ? 20 * (S.info?.motor.J ?? 1e-4) : 0 });
  $('locked').onchange = () => cmd({ cmd: 'load', locked: $('locked').checked ? 1 : 0 });
  $('ambient').addEventListener('input', throttle(() => { labels(); cmd({ cmd: 'environment', ambient: Number($('ambient').value) }); }, 120));
  seg('cooling', (v) => cmd({ cmd: 'environment', cooling: Number(v) }));
  $('magnet').onchange = () => cmd({ cmd: 'magnet', present: $('magnet').checked ? 1 : 0 });
  $('slip').onclick = () => cmd({ cmd: 'slip', turns: 10 / 360 });
  $('vds').onchange = () => cmd({ cmd: 'vds', volts: Number($('vds').value) });

  // joint
  $('enable').onclick = () => cmd({ cmd: 'enable' });
  $('disable').onclick = () => cmd({ cmd: 'disable' });
  $('stop').onclick = () => cmd({ cmd: 'stop' });
  $('faults').addEventListener('click', (e) => { if (e.target.id === 'clear') cmd({ cmd: 'clear' }); });
  $('calibrate').onclick = () => { S.cal = null; S.lastCalPhase = 'idle'; cmd({ cmd: 'calibrate', current: Number($('cal-current').value) }); };
  $('modes').addEventListener('click', (e) => {
    const b = e.target.closest('[role="tab"]');
    if (!b) return;
    for (const t of $('modes').children) t.setAttribute('aria-selected', String(t === b));
    for (const p of document.querySelectorAll('.mode')) p.hidden = p.dataset.mode !== b.dataset.mode;
  });
  $('pos-go').onclick = () => move(Number($('pos-target').value));
  $('pos-target').addEventListener('keydown', (e) => { if (e.key === 'Enter') move(Number($('pos-target').value)); });
  document.querySelector('.jog').addEventListener('click', (e) => {
    const b = e.target.closest('[data-jog]');
    if (!b || !S.frame) return;
    const base = ['Moving', 'Holding'].includes(S.frame.state) ? S.frame.target : S.frame.pos;
    move(base + Number(b.dataset.jog));
  });
  for (const id of ['pos-vmax', 'pos-amax', 'vel-a', 'tq-vl']) $(id).addEventListener('input', labels);
  $('vel').addEventListener('input', async () => { labels(); await ensureEnabled(); sendVelocity(); });
  $('vel-zero').onclick = () => { $('vel').value = 0; labels(); sendVelocity(); };
  $('tq').addEventListener('input', async () => { labels(); await ensureEnabled(); sendTorque(); });
  $('tq-zero').onclick = () => { $('tq').value = 0; labels(); sendTorque(); };
  for (const id of ['imp-kp', 'imp-kd', 'imp-tff']) $(id).addEventListener('input', () => { labels(); sendImpedance(); });
  $('imp-engage').onclick = async () => { await ensureEnabled(); S.impTarget = S.frame?.pos ?? 0; sendImpedance(); };
  $('g-apply').onclick = () => {
    const g = {};
    for (const k of ['kp', 'kd', 'ki', 'kv', 'kvi']) g[k] = Number($(`g-${k}`).value);
    cmd({ cmd: 'gains', ...g });
    cmd({ cmd: 'timeout', seconds: Number($('g-timeout').value) });
  };
  $('g-reset').onclick = () => cmd({ cmd: 'motor', id: S.info?.motor.id });
  $('log-clear').onclick = () => { $('log').innerHTML = ''; };

  document.addEventListener('keydown', (e) => {
    if (e.target.matches('input, select, textarea')) return;
    if (e.key === 'Escape') cmd({ cmd: 'disable' });
    else if (e.key === 'p' || e.key === 'P') $('pause').click();
    else if (e.key === 'f' || e.key === 'F') $('freeze').click();
  });
  // The deadman's other half: a heartbeat while this page is visible.
  setInterval(() => { if (S.connected && document.visibilityState === 'visible') cmd({ cmd: 'heartbeat' }); }, 250);
  labels();
}

function applyTheme(t) {
  if (t === 'system') delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
}
try { applyTheme(localStorage.getItem('tercio.sim.theme') || 'system'); } catch {}

function loop() {
  rotor.draw();
  scope.draw();
  drawDq($('dq'), S.frame, S.info?.profile.maxCurrent ?? 10, S.trail);
  requestAnimationFrame(loop);
}

wire();
connect();
requestAnimationFrame(loop);
