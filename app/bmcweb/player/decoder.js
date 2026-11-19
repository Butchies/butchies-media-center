/* Butchies Web-Player – Worker: liest die Originaldatei per Range direkt vom NAS und entschlüsselt
   Bild + Ton mit dem FFmpeg-WebAssembly-Kern. Ergebnisse gehen als Nachrichten an die Seite. */
'use strict';
let M = null, url = '', size = 0, opened = false, running = false, ended = false;
let vInFlight = 0, clock = 0, lastAudio = -1, target = -1, atarget = -1, gen = 0;
const CH = 4 << 20;                 // 4 MB je Abruf
const cache = new Map();            // Blocknummer -> Uint8Array
const MAXV = 30, AUDIO_AHEAD = 3;   // max. Bilder unterwegs, Sekunden Ton im Voraus

function fetchBlock(n) {
  if (cache.has(n)) { const b = cache.get(n); cache.delete(n); cache.set(n, b); return b; }
  const a = n * CH, b = Math.min(size, a + CH) - 1;
  for (let attempt = 0; attempt < 4; attempt++) {
    const x = new XMLHttpRequest();
    x.open('GET', url, false);
    x.responseType = 'arraybuffer';
    x.setRequestHeader('Range', 'bytes=' + a + '-' + b);
    try { x.send(); } catch (e) { continue; }
    if ((x.status === 206 || x.status === 200) && x.response) {
      let buf = new Uint8Array(x.response);
      if (x.status === 200 && buf.length > b - a + 1) buf = buf.subarray(a, b + 1);
      cache.set(n, buf);
      while (cache.size > 12) cache.delete(cache.keys().next().value);
      return buf;
    }
  }
  return null;
}

function bmcRead(pos, ptr, len) {
  let done = 0;
  while (done < len && pos + done < size) {
    const p = pos + done, n = Math.floor(p / CH), blk = fetchBlock(n);
    if (!blk) break;
    const off = p - n * CH, take = Math.min(len - done, blk.length - off);
    if (take <= 0) break;
    M.HEAPU8.set(blk.subarray(off, off + take), ptr + done);
    done += take;
  }
  return done;
}

function copyPlane(ptr, stride, rowBytes, rows) {
  const out = new Uint8Array(rowBytes * rows), H = M.HEAPU8;
  if (stride === rowBytes) out.set(H.subarray(ptr, ptr + rowBytes * rows));
  else for (let y = 0; y < rows; y++) out.set(H.subarray(ptr + y * stride, ptr + y * stride + rowBytes), y * rowBytes);
  return out;
}

function sendVideo() {
  const w = M._bmc_v_width(), h = M._bmc_v_height(), bits = M._bmc_v_bits(), bpp = bits > 8 ? 2 : 1;
  const pts = M._bmc_v_pts();
  if (target >= 0 && pts >= 0 && pts < target - 0.05) return false;   // nach dem Spulen: vor dem Ziel verwerfen
  const cw = (w + 1) >> 1, chh = (h + 1) >> 1;
  const y = copyPlane(M._bmc_v_data(0), M._bmc_v_linesize(0), w * bpp, h);
  const u = copyPlane(M._bmc_v_data(1), M._bmc_v_linesize(1), cw * bpp, chh);
  const v = copyPlane(M._bmc_v_data(2), M._bmc_v_linesize(2), cw * bpp, chh);
  postMessage({ t: 'v', gen, pts, w, h, bits, matrix: M._bmc_v_matrix(), range: M._bmc_v_range(), y, u, v },
              [y.buffer, u.buffer, v.buffer]);
  vInFlight++;
  return true;
}

function sendAudio() {
  const n = M._bmc_a_samples(), pts = M._bmc_a_pts();
  if (atarget >= 0 && pts >= 0 && pts + n / 48000 < atarget) return;
  atarget = -1;
  const p = M._bmc_a_data() >> 2;
  const pcm = M.HEAPF32.slice(p, p + n * 2);
  lastAudio = pts + n / 48000;
  postMessage({ t: 'a', gen, pts, pcm }, [pcm.buffer]);
}

function pump() {
  if (!opened || !running || ended) return;
  const t0 = performance.now();
  while (performance.now() - t0 < 40) {
    const hasAudio = info.audio >= 0;
    const needAudio = hasAudio && (lastAudio < 0 || lastAudio - clock < AUDIO_AHEAD);
    if (vInFlight >= MAXV && !needAudio) break;
    if (vInFlight >= MAXV * 2) break;
    const r = M._bmc_step();
    if (r === 1) { if (sendVideo() && target >= 0) target = -1; }
    else if (r === 2) sendAudio();
    else if (r === -1) { ended = true; postMessage({ t: 'end', gen }); break; }
    else if (r < -1) { postMessage({ t: 'err', msg: 'Entschlüsseln fehlgeschlagen (' + r + ')' }); ended = true; break; }
  }
  setTimeout(pump, vInFlight >= MAXV ? 15 : 0);
}

let info = null;
onmessage = async (e) => {
  const m = e.data;
  if (m.t === 'open') {
    url = m.url;
    try {
      const h = new XMLHttpRequest();
      h.open('GET', url, false);
      h.responseType = 'arraybuffer';
      h.setRequestHeader('Range', 'bytes=0-0');
      h.send();
      const cr = h.getResponseHeader('Content-Range');
      size = cr ? parseInt(cr.split('/')[1], 10) : parseInt(h.getResponseHeader('Content-Length') || '0', 10);
      if (!size) throw new Error('Dateigröße unbekannt (HTTP ' + h.status + ')');
      importScripts(m.core);
      M = await BmcCore({
        bmcRead, bmcSize: () => size,
        locateFile: (f) => m.base + f,
        mainScriptUrlOrBlob: m.core,
        print: () => {}, printErr: (s) => { if (/error/i.test(s)) console.warn('[bmc]', s); },
      });
      const r = M._bmc_open(m.threads || 1);
      if (r < 0) throw new Error('Datei kann nicht geöffnet werden (' + r + ')');
      info = JSON.parse(M.UTF8ToString(M._bmc_info()));
      opened = true;
      postMessage({ t: 'info', info });
      if (m.start > 0) { target = atarget = m.start; M._bmc_seek(m.start); lastAudio = -1; }
      if (running) pump();
    } catch (err) {
      postMessage({ t: 'err', msg: String(err && err.message || err) });
    }
  } else if (m.t === 'run') {
    running = m.on; if (running) pump();
  } else if (m.t === 'clock') {
    clock = m.clock; vInFlight = Math.max(0, vInFlight - (m.consumed || 0));
  } else if (m.t === 'seek') {
    gen = m.gen; target = atarget = m.to; ended = false; vInFlight = 0; lastAudio = -1; clock = m.to;
    M._bmc_seek(Math.max(0, m.to - 0.01));
    if (running) pump();
  } else if (m.t === 'audio') {
    gen = m.gen; M._bmc_set_audio(m.index); target = atarget = m.at; ended = false; vInFlight = 0; lastAudio = -1;
    M._bmc_seek(Math.max(0, m.at - 0.01));
    info.audio = m.index;
    if (running) pump();
  }
};
