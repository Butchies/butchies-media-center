/* Butchies-Player – spielt jeden Film im Browser ab (x265/HEVC, H.264, Kino-Ton …).
   Das NAS schickt die Originaldatei (Direct Stream), entschlüsselt wird auf diesem Gerät (WebAssembly). */
(function () {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const qs = new URLSearchParams(location.search);
  const itemId = (qs.get('id') || '').replace(/[^0-9a-f]/gi, '');
  const TICKS = 1e7;

  // ---------- Anmeldung (wie die Jellyfin-Oberfläche) ----------
  function creds() {
    try {
      const c = JSON.parse(localStorage.getItem('jellyfin_credentials') || '{}');
      const s = (c.Servers || []).find((x) => x.AccessToken) || {};
      return { token: s.AccessToken || '', user: s.UserId || '' };
    } catch (e) { return { token: '', user: '' }; }
  }
  const C = creds();
  let devId = '';
  try { devId = localStorage.getItem('_deviceId2') || ''; } catch (e) {}
  if (!devId) devId = 'bmcplayer-' + Math.random().toString(36).slice(2);
  const AUTH = 'MediaBrowser Client="Butchies-Player", Device="Browser", DeviceId="' + devId + '", Version="1.0.0", Token="' + C.token + '"';
  const api = (path, opt) => fetch(path, Object.assign({ headers: { 'Authorization': AUTH, 'Content-Type': 'application/json' } }, opt || {}))
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.status === 204 ? null : r.json(); });

  // ---------- Anzeige-Helfer ----------
  const fmt = (s) => {
    s = Math.max(0, Math.floor(s || 0));
    const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, x = s % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0');
  };
  function spinner(on, text) { $('#spinner').hidden = !on; if (text) $('#spinText').textContent = text; }
  function fail(msg, title) {
    spinner(false);
    $('#errTitle').textContent = title || 'Abspielen nicht möglich';
    $('#errText').textContent = msg;
    $('#error').hidden = false;
  }
  function leave() {
    stopReport();
    try { worker && worker.terminate(); } catch (e) {}
    location.replace('/web/#/details?id=' + itemId);
  }
  $('#errBack').onclick = leave;
  $('#back').onclick = leave;
  $('#stop').onclick = leave;

  if (!itemId || !C.token) { fail('Bitte zuerst im Media Center anmelden und den Film dort auswählen.'); return; }

  // ---------- Bild (WebGL, YUV -> RGB auf der Grafikkarte) ----------
  const cv = $('#screen');
  const gl = cv.getContext('webgl', { alpha: false, antialias: false, preserveDrawingBuffer: false, powerPreference: 'high-performance' });
  if (!gl) { fail('Dein Browser unterstützt kein WebGL.'); return; }
  const vs = 'attribute vec2 p;varying vec2 t;void main(){t=vec2((p.x+1.0)/2.0,(1.0-p.y)/2.0);gl_Position=vec4(p,0,1);}';
  const fs = 'precision mediump float;varying vec2 t;uniform sampler2D Y,U,V;uniform float hi;uniform mat3 m;uniform vec3 off;uniform vec3 sc;' +
    'float g(sampler2D s){vec4 c=texture2D(s,t);return hi>0.5?(c.r*255.0+c.a*65280.0)/1023.0:c.r;}' +
    'void main(){vec3 yuv=(vec3(g(Y),g(U),g(V))-off)*sc;gl_FragColor=vec4(clamp(m*yuv,0.0,1.0),1.0);}';
  function sh(type, src) { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; }
  const prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(prog); gl.useProgram(prog);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const tex = [0, 1, 2].map((i) => {
    const t = gl.createTexture(); gl.activeTexture(gl.TEXTURE0 + i); gl.bindTexture(gl.TEXTURE_2D, t);
    [gl.TEXTURE_MIN_FILTER, gl.TEXTURE_MAG_FILTER].forEach((k) => gl.texParameteri(gl.TEXTURE_2D, k, gl.LINEAR));
    [gl.TEXTURE_WRAP_S, gl.TEXTURE_WRAP_T].forEach((k) => gl.texParameteri(gl.TEXTURE_2D, k, gl.CLAMP_TO_EDGE));
    gl.uniform1i(gl.getUniformLocation(prog, 'YUV'[i]), i);
    return t;
  });
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  let lastMat = '';
  function setMatrix(f) {
    const bt709 = f.matrix === 1 || ((f.matrix === 2 || f.matrix === 0) && f.h >= 700);
    const full = f.range === 2;
    const key = bt709 + '/' + full + '/' + f.bits;
    if (key === lastMat) return;
    lastMat = key;
    const k = bt709 ? [1.5748, 0.1873, 0.4681, 1.8556] : [1.402, 0.344136, 0.714136, 1.772];
    // Spalten-Reihenfolge für GLSL mat3
    gl.uniformMatrix3fv(gl.getUniformLocation(prog, 'm'), false, [1, 1, 1, 0, -k[1], k[3], k[0], -k[2], 0]);
    gl.uniform3fv(gl.getUniformLocation(prog, 'off'), full ? [0, 0.5, 0.5] : [16 / 255, 128 / 255, 128 / 255]);
    gl.uniform3fv(gl.getUniformLocation(prog, 'sc'), full ? [1, 1, 1] : [255 / 219, 255 / 224, 255 / 224]);
    gl.uniform1f(gl.getUniformLocation(prog, 'hi'), f.bits > 8 ? 1 : 0);
  }
  function draw(f) {
    if (cv.width !== f.w || cv.height !== f.h) { cv.width = f.w; cv.height = f.h; fit(); }
    gl.viewport(0, 0, f.w, f.h);
    setMatrix(f);
    const fmt2 = f.bits > 8 ? gl.LUMINANCE_ALPHA : gl.LUMINANCE;
    const cw = (f.w + 1) >> 1, ch = (f.h + 1) >> 1;
    [[f.y, f.w, f.h], [f.u, cw, ch], [f.v, cw, ch]].forEach((pl, i) => {
      gl.activeTexture(gl.TEXTURE0 + i); gl.bindTexture(gl.TEXTURE_2D, tex[i]);
      gl.texImage2D(gl.TEXTURE_2D, 0, fmt2, pl[1], pl[2], 0, fmt2, gl.UNSIGNED_BYTE, pl[0]);
    });
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }
  function fit() {
    if (!cv.width) return;
    const s = Math.min(innerWidth / cv.width, innerHeight / cv.height);
    cv.style.width = Math.round(cv.width * s) + 'px';
    cv.style.height = Math.round(cv.height * s) + 'px';
    const pc = $('#pgs'); pc.style.width = cv.style.width; pc.style.height = cv.style.height;
  }
  addEventListener('resize', fit);

  // ---------- Ton (AudioContext ist der Taktgeber) ----------
  let actx = null, gain = null, aSources = [], aQueue = [], aBaseCtx = null, aBasePts = 0, audioEnd = 0;
  let audioLocked = false, aHold = [];   // Ton noch nicht erlaubt: Bild läuft schon, Ton kommt nach dem ersten Tippen
  function ensureAudio() {
    if (actx) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    actx = new AC({ sampleRate: 48000, latencyHint: 'playback' });
    gain = actx.createGain(); gain.connect(actx.destination);
    applyVolume();
  }
  function schedule(ch) {
    const n = ch.pcm.length >> 1;
    const ab = actx.createBuffer(2, n, 48000);
    const L = ab.getChannelData(0), R = ab.getChannelData(1);
    for (let i = 0, j = 0; i < n; i++, j += 2) { L[i] = ch.pcm[j]; R[i] = ch.pcm[j + 1]; }
    let when = aBaseCtx + (ch.pts - aBasePts), off = 0;
    const now = actx.currentTime;
    if (when < now + 0.005) { off = now + 0.005 - when; when = now + 0.005; }
    if (off >= ab.duration) return;
    const src = actx.createBufferSource(); src.buffer = ab; src.connect(gain); stats.audioChunks++;
    src.start(when, off);
    src.onended = () => { const k = aSources.indexOf(src); if (k >= 0) aSources.splice(k, 1); };
    aSources.push(src);
    audioEnd = Math.max(audioEnd, aBasePts + (when - aBaseCtx) + (ab.duration - off));
  }
  function stopAudio() {
    aSources.forEach((s) => { try { s.stop(); } catch (e) {} });
    aSources = []; aQueue = []; aHold = []; aBaseCtx = null; audioEnd = 0;
  }

  // ---------- Zustand ----------
  let info = null, hasAudio = false, duration = 0, gen = 0, worker = null;
  let vq = [], state = 'loading', playing = true, ended = false, consumed = 0;
  let startPts = 0, pausedAt = 0, perfBase = null, perfPts = 0, lastShown = 0, seeking = false;
  let item = null, mediaSource = null, subs = [], subEvents = null;

  function clock() {
    if (state !== 'playing') return pausedAt;
    if (hasAudio && !audioLocked && aBaseCtx !== null) return aBasePts + (actx.currentTime - aBaseCtx);
    if (perfBase !== null) return perfPts + (performance.now() - perfBase) / 1000;
    return pausedAt;
  }

  function startPlayback() {
    // genug gepuffert -> los
    const t0 = vq.length ? vq[0].pts : (aQueue.length ? aQueue[0].pts : startPts);
    pausedAt = Math.max(0, t0);
    if (hasAudio) ensureAudio();
    if (hasAudio && actx.state === 'running') {
      audioLocked = false;
      aBaseCtx = actx.currentTime + 0.12; aBasePts = pausedAt;
      aQueue.forEach(schedule); aQueue = [];
    } else if (hasAudio) {
      // Browser erlaubt Ton erst nach einer Berührung: Bild startet trotzdem, Ton wird beim ersten Tippen nahtlos zugeschaltet
      audioLocked = true; aHold = aQueue; aQueue = [];
      perfBase = performance.now() + 120; perfPts = pausedAt;
      actx.resume().then(unlock, () => {});
      $('#soundHint').hidden = false;
    } else {
      perfBase = performance.now() + 120; perfPts = pausedAt;
    }
    state = 'playing';
    spinner(false);
    if (!playing) pause(true);
  }

  function unlock() {
    if (!actx) ensureAudio();
    if (!audioLocked) { if (actx.state !== 'running' && state === 'playing') actx.resume().catch(() => {}); return; }
    actx.resume().then(() => {
      if (!audioLocked || actx.state !== 'running') return;
      const t = clock();
      audioLocked = false; perfBase = null;
      aBaseCtx = actx.currentTime + 0.05; aBasePts = t + 0.05;
      if (state === 'playing') { pausedAt = t; }
      const held = aHold; aHold = [];
      held.forEach(schedule);
      if (state !== 'playing') actx.suspend();
      $('#soundHint').hidden = true;
    }).catch(() => {});
  }

  function pause(force) {
    if (state !== 'playing' && !force) { playing = false; setPlayIcon(); return; }
    pausedAt = clock();
    playing = false;
    if (actx) actx.suspend();
    perfBase = null;
    state = 'paused';
    setPlayIcon(); report('progress');
  }
  function resume() {
    playing = true;
    if (state === 'paused') {
      if (hasAudio && actx && !audioLocked) { actx.resume(); } else { perfBase = performance.now(); perfPts = pausedAt; }
      state = 'playing';
    }
    setPlayIcon(); report('progress');
  }
  function setPlayIcon() {
    $('#playIcon').setAttribute('d', playing ? 'M6 19h4V5H6v14zm8-14v14h4V5h-4z' : 'M8 5v14l11-7z');
    $('#play').title = playing ? 'Pause' : 'Abspielen';
  }

  function seekTo(t) {
    if (!info) return;
    t = Math.max(0, Math.min(duration ? duration - 1 : t, t));
    gen++; seeking = true; ended = false;
    stopAudio(); vq = []; consumed = 0; startPts = t; pausedAt = t; perfBase = null;
    state = 'buffering'; spinner(true, '');
    worker.postMessage({ t: 'seek', to: t, gen });
    showTimes(t);
  }

  // ---------- Worker / Decoder ----------
  function startWorker(start) {
    const mt = qs.get('core') !== 'st' && window.crossOriginIsolated && typeof SharedArrayBuffer !== 'undefined';
    const base = new URL('core/', location.href).href;
    const core = base + (mt ? 'bmccore-mt.js' : 'bmccore-st.js');
    const threads = mt ? Math.max(2, Math.min(8, (navigator.hardwareConcurrency || 4))) : 1;
    worker = new Worker('decoder.js?v=1');
    worker.onmessage = onWorker;
    worker.onerror = (e) => fail('Der Player konnte nicht starten: ' + (e.message || 'unbekannter Fehler'));
    const src = '/Videos/' + itemId + '/stream?Static=true&api_key=' + encodeURIComponent(C.token);
    worker.postMessage({ t: 'open', url: new URL(src, location.href).href, core, base, threads, start });
    worker.postMessage({ t: 'run', on: true });
    window.__bmcMode = mt ? 'mt' : 'st';
  }

  function onWorker(e) {
    const m = e.data;
    if (m.t === 'err') return fail(m.msg);
    if (m.t === 'info') {
      info = m.info; duration = info.duration || (item && item.RunTimeTicks / TICKS) || 0;
      hasAudio = info.audio >= 0;
      const wantA = parseInt(qs.get('a'), 10);
      if (!isNaN(wantA) && wantA !== info.audio && info.streams.some((s) => s.index === wantA && s.type === 'audio' && s.decodable)) {
        info.audio = wantA; worker.postMessage({ t: 'audio', index: wantA, at: startPts, gen: ++gen });
      }
      fillAudio();
      return;
    }
    if (m.gen !== undefined && m.gen !== gen) return;      // alte Daten vor dem Spulen
    if (m.t === 'v') { vq.push(m); if (state === 'loading' || state === 'buffering') maybeStart(); return; }
    if (m.t === 'a') {
      if (state === 'playing' || state === 'paused' || state === 'stalled') {
        if (audioLocked) { aHold.push(m); const c = clock() - 0.2; while (aHold.length && aHold[0].pts + aHold[0].pcm.length / 96000 < c) aHold.shift(); }
        else if (aBaseCtx !== null) schedule(m);
      }
      else { aQueue.push(m); maybeStart(); }
      return;
    }
    if (m.t === 'end') { ended = true; if (state === 'loading' || state === 'buffering') maybeStart(true); }
  }
  function maybeStart(force) {
    const aSec = aQueue.reduce((s, c) => s + c.pcm.length / 96000, 0);
    if (force || (vq.length >= 6 && (!hasAudio || aSec >= 0.6))) {
      if (state === 'buffering' && aBaseCtx === null && !hasAudio) { /* nur Bild */ }
      seeking = false;
      startPlayback();
    }
  }

  // ---------- Darstellung pro Bild ----------
  let lastClockMsg = 0, lastEnds = 0;
  const stats = window.__bmcStats = { shown: 0, dropped: 0, stalls: 0, audioChunks: 0 };
  function tick() {
    requestAnimationFrame(tick);
    if (!info) return;
    const t = clock();
    if (state === 'playing' || state === 'paused') {
      while (vq.length > 1 && vq[1].pts <= t) { vq.shift(); consumed++; stats.dropped++; }
      if (vq.length && vq[0].pts <= t + 0.008) { const f = vq.shift(); consumed++; draw(f); lastShown = f.pts; stats.shown++; }
      if (state === 'playing') {
        // Puffer leer -> kurz anhalten und nachladen
        const audioDry = hasAudio && !audioLocked && aBaseCtx !== null && audioEnd && audioEnd < t + 0.05 && !ended;
        if (((!vq.length && !ended && info.video >= 0)) || audioDry) {
          pausedAt = t; if (actx && !audioLocked) actx.suspend(); perfBase = null; state = 'stalled'; stats.stalls++; spinner(true, '');
        }
        if (ended && !vq.length && (!hasAudio || audioLocked || audioEnd <= t)) { finish(); return; }
      }
    } else if (state === 'stalled') {
      const aAhead = hasAudio && !audioLocked ? audioEnd - pausedAt : 9;
      if ((vq.length >= 8 || ended) && aAhead > 0.5) {
        state = 'playing'; spinner(false);
        if (!playing) state = 'paused';
        else if (hasAudio && actx && !audioLocked) actx.resume();
        else { perfBase = performance.now(); perfPts = pausedAt; }
      }
    }
    const now = performance.now();
    if (now - lastClockMsg > 60 && worker) {
      worker.postMessage({ t: 'clock', clock: t, consumed }); consumed = 0; lastClockMsg = now;
    }
    if (!dragging) showTimes(t);
    showSub(t);
    if (now - lastEnds > 1000) { lastEnds = now; showEnds(t); }
  }

  function showTimes(t) {
    $('#cur').textContent = fmt(t);
    $('#rest').textContent = '-' + fmt(Math.max(0, duration - t));
    if (duration) { $('#seek').value = Math.round(1000 * t / duration); fillRange($('#seek')); }
  }
  function fillRange(el) { el.style.setProperty('--p', (100 * (el.value - el.min) / ((el.max - el.min) || 1)) + '%'); }
  function showEnds(t) {
    if (!duration) { $('#endsAt').textContent = ''; return; }
    const d = new Date(Date.now() + Math.max(0, duration - t) * 1000);
    $('#endsAt').textContent = 'Endet um ' + d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  }

  function finish() {
    state = 'ended'; report('stopped', duration);
    setTimeout(leave, 800);
  }

  // ---------- Ton- und Untertitelauswahl ----------
  function langName(l) {
    const map = { ger: 'Deutsch', deu: 'Deutsch', de: 'Deutsch', eng: 'Englisch', en: 'Englisch', fre: 'Französisch', fra: 'Französisch',
      spa: 'Spanisch', ita: 'Italienisch', tur: 'Türkisch', jpn: 'Japanisch', rus: 'Russisch', pol: 'Polnisch' };
    return map[(l || '').toLowerCase()] || (l && l !== 'und' ? l.toUpperCase() : '');
  }
  function chName(n) { return { 1: 'Mono', 2: 'Stereo', 6: '5.1', 7: '6.1', 8: '7.1' }[n] || (n ? n + ' Kanäle' : ''); }
  function fillAudio() {
    const sel = $('#audioSel'); sel.innerHTML = '';
    const list = info.streams.filter((s) => s.type === 'audio' && s.decodable);
    $('#audioBtn').hidden = list.length < 2;
    if (list.length < 2) return;
    list.forEach((s, i) => {
      const o = document.createElement('option');
      o.value = s.index;
      o.textContent = [langName(s.lang) || ('Ton ' + (i + 1)), s.title, s.codec.toUpperCase(), chName(s.channels)].filter(Boolean).join(' - ');
      if (s.index === info.audio) o.selected = true;
      sel.appendChild(o);
    });
    sel.onchange = () => {
      const at = clock(); gen++;
      stopAudio(); vq = []; info.audio = +sel.value; hasAudio = true;
      state = 'buffering'; spinner(true, '');
      worker.postMessage({ t: 'audio', index: +sel.value, at, gen });
    };
  }
  function fillSubs() {
    const sel = $('#subSel'); sel.innerHTML = '';
    $('#subBtn').hidden = !subs.length;
    if (!subs.length) return;
    const off = document.createElement('option'); off.value = ''; off.textContent = 'Aus'; sel.appendChild(off);
    subs.forEach((s) => {
      const o = document.createElement('option'); o.value = s.Index; o.textContent = s.DisplayTitle || ('Untertitel ' + s.Index);
      sel.appendChild(o);
    });
    const def = mediaSource && mediaSource.DefaultSubtitleStreamIndex;
    const want = qs.has('s') ? parseInt(qs.get('s'), 10) : def;
    if (want !== undefined && want !== null && want >= 0 && subs.some((s) => s.Index === want)) { sel.value = want; loadSub(want); }
    sel.onchange = () => loadSub(sel.value === '' ? -1 : +sel.value);
  }
  const pgs = window.BmcPgs ? window.BmcPgs.Renderer($('#pgs')) : null;
  let subReq = 0;
  function loadSub(idx) {
    subEvents = null; $('#subs').textContent = ''; lastSub = '';
    if (pgs) pgs.set(null);
    const my = ++subReq;
    if (idx < 0) return;
    const s = subs.find((x) => x.Index === idx);
    if (!s) return;
    if (!s.IsTextSubtitleStream) {   // Bild-Untertitel (PGS / Blu-ray)
      if (!pgs) return;
      toast('Untertitel werden geladen …');
      fetch(s.DeliveryUrl, { headers: { 'Authorization': AUTH } }).then((r) => { if (!r.ok) throw new Error(r.status); return r.arrayBuffer(); })
        .then((b) => { if (my !== subReq) return; const ev = window.BmcPgs.parse(b); pgs.set(ev); toast(ev.length ? '' : 'Untertitel sind leer'); })
        .catch(() => { if (my === subReq) toast('Untertitel konnten nicht geladen werden'); });
      return;
    }
    const u = s.DeliveryUrl.replace(/\.(vtt|srt|ass|ssa)(\?|$)/, '.js$2');
    fetch(u, { headers: { 'Authorization': AUTH } }).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).then((j) => {
      if (my !== subReq) return;
      subEvents = (j.TrackEvents || []).map((e) => ({ s: e.StartPositionTicks / TICKS, e: e.EndPositionTicks / TICKS,
        t: e.Text.replace(/\\N/g, '\n').replace(/<[^>]+>/g, '') }));
    }).catch(() => { if (my === subReq) toast('Untertitel konnten nicht geladen werden'); });
  }
  let toastT = 0;
  function toast(msg) {
    clearTimeout(toastT); $('#toast').textContent = msg; $('#toast').hidden = !msg;
    if (msg) toastT = setTimeout(() => { $('#toast').hidden = true; }, 4000);
  }
  let lastSub = '';
  function showSub(t) {
    if (pgs) pgs.draw(t);
    if (!subEvents) { if (lastSub) { $('#subs').textContent = ''; lastSub = ''; } return; }
    let txt = '';
    for (const e of subEvents) { if (e.s <= t && e.e > t) { txt += (txt ? '\n' : '') + e.t; } if (e.s > t) break; }
    if (txt !== lastSub) { $('#subs').textContent = txt; lastSub = txt; }
  }

  // ---------- Bedienung (wie der Jellyfin-Player) ----------
  $('#play').onclick = () => { playing ? pause() : resume(); poke(); };
  $('#rew').onclick = () => seekTo(clock() - 10);
  $('#fwd').onclick = () => seekTo(clock() + 30);
  $('#soundHint').onclick = (e) => { e.stopPropagation(); unlock(); };
  let dragging = false;
  $('#seek').addEventListener('input', () => { dragging = true; fillRange($('#seek')); const t = duration * $('#seek').value / 1000; $('#cur').textContent = fmt(t); });
  $('#seek').addEventListener('change', () => { dragging = false; seekTo(duration * $('#seek').value / 1000); });
  const VOL_ON = 'M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z';
  const VOL_OFF = 'M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z';
  function applyVolume() {
    const v = $('#vol').value / 100, mute = document.body.classList.contains('muted');
    if (gain) gain.gain.value = mute ? 0 : v * v;
    $('#volIcon').setAttribute('d', mute || v === 0 ? VOL_OFF : VOL_ON);
    fillRange($('#vol'));
    try { localStorage.setItem('bmc-player-vol', $('#vol').value); } catch (e) {}
  }
  try { const v = localStorage.getItem('bmc-player-vol'); if (v !== null) $('#vol').value = v; } catch (e) {}
  applyVolume();
  $('#vol').oninput = applyVolume;
  $('#mute').onclick = () => { document.body.classList.toggle('muted'); applyVolume(); };
  const FULL_ON = 'M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z';
  const FULL_OFF = 'M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z';
  function isFull() { return !!(document.fullscreenElement || document.webkitFullscreenElement); }
  function toggleFull() {
    const de = document.documentElement;
    if (isFull()) (document.exitFullscreen || document.webkitExitFullscreen).call(document);
    else { const r = (de.requestFullscreen || de.webkitRequestFullscreen); if (r) { const p = r.call(de); if (p && p.catch) p.catch(() => {}); } }
  }
  function fullIcon() { const f = isFull(); $('#fullIcon').setAttribute('d', f ? FULL_OFF : FULL_ON); $('#full').title = f ? 'Vollbild beenden' : 'Vollbild'; }
  document.addEventListener('fullscreenchange', fullIcon);
  document.addEventListener('webkitfullscreenchange', fullIcon);
  $('#full').onclick = toggleFull;
  // Favorit (Herz) wie in Jellyfin
  let fav = false;
  function setFav(on) { fav = on; $('#fav').classList.toggle('on', on); $('#fav').title = on ? 'Favorit entfernen' : 'Favorit'; }
  $('#fav').onclick = () => {
    const on = !fav; setFav(on);
    api('/Users/' + C.user + '/FavoriteItems/' + itemId, { method: on ? 'POST' : 'DELETE' }).catch(() => setFav(!on));
  };
  // Auswahlmenü für Ton und Untertitel
  function openMenu(sel, title) {
    const list = $('#menu .list'); list.innerHTML = '';
    const hd = document.createElement('div'); hd.className = 'hd'; hd.textContent = title; list.appendChild(hd);
    Array.from(sel.options).forEach((o) => {
      const b = document.createElement('button'); b.className = 'it';
      b.innerHTML = '<span class="chk"></span><span></span>';
      b.firstChild.textContent = o.value === sel.value ? '✓' : '';
      b.lastChild.textContent = o.textContent;
      b.onclick = (e) => { e.stopPropagation(); closeMenu(); if (sel.value !== o.value) { sel.value = o.value; sel.onchange && sel.onchange(); } };
      list.appendChild(b);
    });
    $('#menu').hidden = false; clearTimeout(hideT); document.body.classList.add('ui-on');
    const cur = list.querySelector('.it'); if (cur) cur.focus({ preventScroll: true });
  }
  function closeMenu() { $('#menu').hidden = true; poke(); }
  $('#menu').addEventListener('click', (e) => { if (e.target === $('#menu')) closeMenu(); });
  $('#audioBtn').onclick = () => openMenu($('#audioSel'), 'Audio');
  $('#subBtn').onclick = () => openMenu($('#subSel'), 'Untertitel');
  addEventListener('keydown', (e) => {
    if (!$('#menu').hidden) { if (e.key === 'Escape') closeMenu(); return; }
    if (e.target.tagName === 'INPUT' && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) return;
    if (e.key === ' ' || e.key === 'k' || e.key === 'MediaPlayPause') { e.preventDefault(); $('#play').click(); }
    else if (e.key === 'ArrowLeft' || e.key === 'j') seekTo(clock() - 10);
    else if (e.key === 'ArrowRight' || e.key === 'l') seekTo(clock() + 30);
    else if (e.key === 'ArrowUp') { $('#vol').value = Math.min(100, +$('#vol').value + 5); applyVolume(); }
    else if (e.key === 'ArrowDown') { $('#vol').value = Math.max(0, +$('#vol').value - 5); applyVolume(); }
    else if (e.key === 'f') toggleFull();
    else if (e.key === 'm') $('#mute').click();
    else if ((e.key === 'Escape' || e.key === 'Backspace') && !isFull()) leave();
    poke();
  });
  // Steuerleiste ein-/ausblenden
  let hideT = 0;
  function poke() {
    document.body.classList.add('ui-on');
    clearTimeout(hideT);
    hideT = setTimeout(() => { if (state === 'playing' && !dragging && $('#menu').hidden) document.body.classList.remove('ui-on'); }, 3500);
  }
  function hideUi() { clearTimeout(hideT); if (state === 'playing' && $('#menu').hidden) document.body.classList.remove('ui-on'); }
  let lastMove = 0;
  addEventListener('mousemove', (e) => { if (Math.abs(e.movementX) + Math.abs(e.movementY) < 1 && performance.now() - lastMove < 50) return; lastMove = performance.now(); poke(); });
  // Klick auf das Bild: Maus = Pause/Weiter (verzögert, damit Doppelklick = Vollbild klappt); Finger = Leiste ein/aus, Doppeltippen = Vollbild
  let ptype = 'mouse', clickT = 0, lastTap = 0;
  const onScreen = (e) => !e.target.closest('.top, .bottom, #menu, #soundHint, #error');
  let soundTap = false;   // erster Klick schaltet nur den Ton zu (nicht zusätzlich Pause)
  $('#stage').addEventListener('pointerdown', (e) => { ptype = e.pointerType || 'mouse'; soundTap = audioLocked; });
  $('#stage').addEventListener('click', (e) => {
    if (!onScreen(e)) return;
    if (soundTap) { soundTap = false; poke(); return; }
    if (ptype === 'mouse') {
      clearTimeout(clickT);
      if (e.detail >= 2) return;            // zweiter Klick -> dblclick übernimmt
      clickT = setTimeout(() => { $('#play').click(); }, 260);
      return;
    }
    const now = performance.now();
    if (now - lastTap < 320) { lastTap = 0; toggleFull(); return; }
    lastTap = now;
    if (document.body.classList.contains('ui-on')) hideUi(); else poke();
  });
  $('#stage').addEventListener('dblclick', (e) => {
    if (!onScreen(e) || ptype !== 'mouse') return;
    clearTimeout(clickT); toggleFull(); poke();
  });

  // ---------- Fortschritt an den Server melden (Weiterschauen) ----------
  let repT = 0;
  function body(pos) {
    return JSON.stringify({ ItemId: itemId, MediaSourceId: itemId, PositionTicks: Math.round((pos === undefined ? clock() : pos) * TICKS),
      IsPaused: !playing, CanSeek: true, PlayMethod: 'DirectStream', AudioStreamIndex: info ? info.audio : null });
  }
  function report(kind, pos) {
    if (!info) return;
    const path = kind === 'start' ? '/Sessions/Playing' : kind === 'stopped' ? '/Sessions/Playing/Stopped' : '/Sessions/Playing/Progress';
    fetch(path, { method: 'POST', keepalive: kind === 'stopped', headers: { 'Authorization': AUTH, 'Content-Type': 'application/json' }, body: body(pos) }).catch(() => {});
  }
  function stopReport() { if (repT) { clearInterval(repT); repT = 0; if (state !== 'ended') report('stopped'); } }
  addEventListener('pagehide', stopReport);

  // ---------- Start ----------
  (async function main() {
    spinner(true, '');
    try {
      item = await api('/Users/' + C.user + '/Items/' + itemId);
      $('#title').textContent = item.Name || '';
      document.title = item.Name || 'Jellyfin';
      setFav(!!(item.UserData && item.UserData.IsFavorite));
      $('#sub').textContent = [item.ProductionYear, item.SeriesName && (item.SeriesName + (item.ParentIndexNumber ? ' · S' + item.ParentIndexNumber + 'E' + (item.IndexNumber || '') : ''))].filter(Boolean).join(' · ');
      duration = (item.RunTimeTicks || 0) / TICKS;
      const pi = await api('/Items/' + itemId + '/PlaybackInfo?BmcPlayer=1&UserId=' + C.user + (qs.has('s') ? '&SubtitleStreamIndex=' + encodeURIComponent(qs.get('s')) : ''), { method: 'POST', body: JSON.stringify({ DeviceProfile: {} }) });
      mediaSource = (pi.MediaSources || [])[0] || null;
      subs = ((mediaSource && mediaSource.MediaStreams) || []).filter((s) => s.Type === 'Subtitle' && s.DeliveryUrl && (s.IsTextSubtitleStream || /pgs/i.test(s.Codec || '')));
      fillSubs();
    } catch (e) { return fail('Der Film konnte nicht geladen werden (' + e.message + '). Bitte im Media Center neu anmelden.'); }
    let start = 0;
    if (qs.has('t')) start = parseFloat(qs.get('t')) || 0;
    else if (item.UserData && item.UserData.PlaybackPositionTicks) start = item.UserData.PlaybackPositionTicks / TICKS;
    startPts = start; pausedAt = start;
    spinner(true, '');
    startWorker(start);
    // Ton erst nach einer Berührung erlaubt (Browser-Regel) – erstes Tippen/Klicken/Taste schaltet ihn zu
    addEventListener('pointerdown', unlock, true);
    addEventListener('keydown', unlock, true);
    const wait = setInterval(() => {
      if (state === 'playing') { clearInterval(wait); report('start'); repT = setInterval(() => report('progress'), 10000); }
    }, 300);
    setPlayIcon(); poke(); requestAnimationFrame(tick);
  })();
})();
