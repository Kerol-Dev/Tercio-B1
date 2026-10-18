#!/usr/bin/env node
// Tercio B1 simulator: web bridge.
//
// Runs the simulator process (the firmware's Joint and FocCore on the
// simulated bench, src/simulator/main.cpp), serves the UI from ./public,
// streams the simulator's JSON lines to the browser over Server-Sent Events
// and forwards the browser's commands to its stdin.
//
//   node firmware/simulator/server.mjs [--port 8770]
//
// The simulator binary is rebuilt with PlatformIO when a source file is newer.
import http from 'node:http';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, extname, join, resolve } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const firmware = resolve(here, '..');
const publicDir = join(here, 'public');
const binary = join(firmware, '.pio', 'build', 'simulator', 'program');
const portArg = process.argv.indexOf('--port');
const port = Number(portArg > 0 ? process.argv[portArg + 1] : process.env.PORT || 8770);

// ---- Build ------------------------------------------------------------------------------------------------

function newestSource(dir) {
  let newest = 0;
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) newest = Math.max(newest, newestSource(p));
    else if (/\.(cpp|h)$/.test(entry.name)) newest = Math.max(newest, statSync(p).mtimeMs);
  }
  return newest;
}

function build() {
  const stale = !existsSync(binary) || newestSource(join(firmware, 'src')) > statSync(binary).mtimeMs;
  if (!stale) return;
  const pio = [process.env.PIO, join(homedir(), '.platformio', 'penv', 'bin', 'pio'), 'pio'].find(
    (p) => p && (p === 'pio' || existsSync(p)),
  );
  console.log(`building the simulator (${pio} run -e simulator)…`);
  const r = spawnSync(pio, ['run', '-e', 'simulator', '-d', firmware], { stdio: 'inherit' });
  if (r.status !== 0) {
    console.error('build failed');
    process.exit(1);
  }
}

// ---- Simulator process ----------------------------------------------------------------------------------

const clients = new Set();
let sim = null;
let lastInfo = null;
let lastCalibration = null;

function broadcast(line) {
  for (const res of clients) res.write(`data: ${line}\n\n`);
}

function start() {
  sim = spawn(binary, [], { stdio: ['pipe', 'pipe', 'inherit'] });
  let pending = '';
  sim.stdout.setEncoding('utf8');
  sim.stdout.on('data', (chunk) => {
    pending += chunk;
    let nl;
    while ((nl = pending.indexOf('\n')) >= 0) {
      const line = pending.slice(0, nl);
      pending = pending.slice(nl + 1);
      if (!line) continue;
      if (line.startsWith('{"type":"info"')) lastInfo = line;
      else if (line.startsWith('{"type":"calibration"')) lastCalibration = line;
      broadcast(line);
    }
  });
  sim.on('exit', (code, signal) => {
    broadcast(JSON.stringify({ type: 'event', level: 'bad', text: `Simulator stopped (${signal || code}); restarting.` }));
    sim = null;
    setTimeout(start, 1000);
  });
}

function send(command) {
  if (sim && sim.stdin.writable) sim.stdin.write(`${JSON.stringify(command)}\n`);
}

// ---- HTTP ---------------------------------------------------------------------------------------------------

const types = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.json': 'application/json',
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname === '/events') {
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-store', connection: 'keep-alive' });
    res.write('retry: 1000\n\n');
    if (lastInfo) res.write(`data: ${lastInfo}\n\n`);
    if (lastCalibration) res.write(`data: ${lastCalibration}\n\n`);
    clients.add(res);
    req.on('close', () => clients.delete(res));
    return;
  }
  if (url.pathname === '/cmd' && req.method === 'POST') {
    let body = '';
    req.on('data', (c) => {
      body += c;
      if (body.length > 1e5) req.destroy();
    });
    req.on('end', () => {
      try {
        const command = JSON.parse(body);
        if (typeof command.cmd !== 'string') throw new Error('no cmd');
        send(command);
        res.writeHead(204).end();
      } catch {
        res.writeHead(400).end('bad command');
      }
    });
    return;
  }
  let path = decodeURIComponent(url.pathname);
  if (path.endsWith('/')) path += 'index.html';
  const file = resolve(publicDir, `.${path}`);
  if (!file.startsWith(publicDir) || !existsSync(file) || statSync(file).isDirectory()) {
    res.writeHead(404).end('not found');
    return;
  }
  res.writeHead(200, { 'content-type': types[extname(file)] || 'application/octet-stream', 'cache-control': 'no-store' });
  res.end(readFileSync(file));
});

build();
start();
server.listen(port, '127.0.0.1', () => console.log(`Tercio B1 simulator: http://127.0.0.1:${port}/`));
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    if (sim) sim.kill();
    process.exit(0);
  });
}
