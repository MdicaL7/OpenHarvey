import { writeFileSync, mkdirSync } from 'fs';
import { spawn } from 'child_process';
import http from 'http';
import { fileURLToPath } from 'url';
import path from 'path';

const ARTIFACT_DIR = '/Users/dicam/.gemini/antigravity/brain/ac4f70cc-efd8-4be2-b1a9-3ba4c609e9e3';
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 8765;
const CDP_PORT = 9222;

mkdirSync(ARTIFACT_DIR, { recursive: true });

// Use basic http server
import fs from 'fs';

const mimeTypes = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.mjs': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.svg': 'image/svg+xml'
};

const server = http.createServer((req, res) => {
  const urlPath = req.url.split('?')[0];
  const filePath = path.join(process.cwd(), urlPath);
  if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
    const ext = path.extname(filePath);
    res.writeHead(200, { 'Content-Type': mimeTypes[ext] || 'text/plain' });
    fs.createReadStream(filePath).pipe(res);
  } else {
    res.writeHead(404);
    res.end('Not found');
  }
});

server.listen(PORT, '127.0.0.1');
console.log(`Static server running on port ${PORT}`);

// Launch Chrome
const chromeProc = spawn(CHROME, [
  '--headless=new',
  '--disable-gpu',
  `--remote-debugging-port=${CDP_PORT}`,
  '--window-size=1280,1800',
  'about:blank'
], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));
await sleep(1500);

async function getCDPTarget() {
  const res = await fetch(`http://127.0.0.1:${CDP_PORT}/json/list`);
  const list = await res.json();
  return list.find(t => t.type === 'page') || list[0];
}

class CDPClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.id = 0;
    this.callbacks = new Map();
    this.ws.onmessage = e => {
      const data = JSON.parse(e.data);
      if (data.id && this.callbacks.has(data.id)) {
        this.callbacks.get(data.id)(data);
        this.callbacks.delete(data.id);
      }
    };
  }

  async open() {
    if (this.ws.readyState === WebSocket.OPEN) return;
    return new Promise((resolve, reject) => {
      this.ws.onopen = resolve;
      this.ws.onerror = reject;
    });
  }

  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      this.callbacks.set(id, res => {
        if (res.error) reject(new Error(res.error.message));
        else resolve(res.result);
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    this.ws.close();
  }
}

const target = await getCDPTarget();
const client = new CDPClient(target.webSocketDebuggerUrl);
await client.open();
await client.send('Page.enable');
await client.send('Runtime.enable');

async function captureScreenshot(url, outputPath, waitSelector, evaluateCode = null) {
  console.log(`Navigating to ${url}...`);
  await client.send('Page.navigate', { url });
  
  // Wait for selector and rendering
  for (let i = 0; i < 40; i++) {
    await sleep(200);
    const check = await client.send('Runtime.evaluate', {
      expression: `!!document.querySelector('${waitSelector}')`
    });
    if (check.result?.value) break;
  }
  
  if (evaluateCode) {
    await client.send('Runtime.evaluate', { expression: evaluateCode });
  }

  await sleep(1000); // ensure fonts and animations settle

  console.log(`Capturing to ${outputPath}...`);
  const result = await client.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: true
  });

  const buffer = Buffer.from(result.data, 'base64');
  writeFileSync(outputPath, buffer);
  console.log(`Saved ${outputPath} (${buffer.length} bytes)`);
}

try {
  // 1. Overview
  await client.send('Emulation.setDeviceMetricsOverride', {
    width: 1280,
    height: 1800,
    deviceScaleFactor: 2,
    mobile: false
  });
  await captureScreenshot(
    `http://127.0.0.1:${PORT}/scripts/visual_preview.html`,
    path.join(ARTIFACT_DIR, 'unified_references_overview.png'),
    '.scenario-card'
  );

  // 2. Case detail modal
  await client.send('Emulation.setDeviceMetricsOverride', {
    width: 1280,
    height: 1000,
    deviceScaleFactor: 2,
    mobile: false
  });
  await captureScreenshot(
    `http://127.0.0.1:${PORT}/scripts/visual_preview.html?modal=case`,
    path.join(ARTIFACT_DIR, 'unified_references_modal.png'),
    '.reference-detail-dialog[open]'
  );

  // 3. Preference detail modal
  await captureScreenshot(
    `http://127.0.0.1:${PORT}/scripts/visual_preview.html?modal=pref`,
    path.join(ARTIFACT_DIR, 'unified_references_pref_modal.png'),
    '.reference-detail-dialog[open]'
  );

} finally {
  client.close();
  chromeProc.kill();
  server.close();
  console.log('Finished capturing screenshots.');
}
