/* Butchies Media Center – Player (Aufbau nach design/player: Video, Steuerleiste, Wiedergabeeinstellungen, Wiedergabeliste).
   Das NAS schickt die Originaldatei (Direct Stream). Nur wenn das Plugin „Browser-Hilfe“ eingeschaltet ist und der Browser
   den Ton nicht kann bzw. eine andere Tonspur gewählt wird, packt das NAS die Datei um (Bild bleibt, Ton → AAC). */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var v = $('video'), P = $('player');
  var qs = new URLSearchParams(location.search);
  var ID = (qs.get('id') || '').replace(/[^0-9a-f]/gi, '').toLowerCase();
  var TICKS = 1e7;

  /* ---------- Anmeldung wie die Jellyfin-Oberfläche ---------- */
  var C = { token: '', user: '' };
  try {
    var cr = JSON.parse(localStorage.getItem('jellyfin_credentials') || '{}');
    var sv = (cr.Servers || []).filter(function (x) { return x.AccessToken; })[0] || {};
    C = { token: sv.AccessToken || '', user: sv.UserId || '' };
  } catch (e) {}
  var dev = '';
  try { dev = localStorage.getItem('_deviceId2') || ''; } catch (e) {}
  if (!dev) dev = 'bmcplay-' + Math.random().toString(36).slice(2);
  var AUTH = 'MediaBrowser Client="Butchies Media Center", Device="Browser", DeviceId="' + dev + '", Version="1.0.0", Token="' + C.token + '"';
  function api(path, opt) {
    return fetch(path, Object.assign({ headers: { 'Authorization': AUTH, 'Content-Type': 'application/json' } }, opt || {}))
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.status === 204 ? null : r.json(); });
  }

  /* ---------- Zustand ---------- */
  var item = null, ms = null, psid = '', helper = false;
  var mode = 'direct', base = 0, total = 0;     // remux: Video beginnt bei „base“ Sekunden
  var audioIdx = null, defaultAudio = null, queue = [], qpos = -1, chapters = [];
  var subCues = null, pgsR = null, pgsOn = false, lastSave = 0, sleepAt = 0, sleepEnd = false;

  var fmt = function (t) { if (!isFinite(t)) return '00:00'; var s = Math.max(0, Math.floor(t)), h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60); return (h ? h + ':' : '') + (h ? String(m).padStart(2, '0') : m) + ':' + String(s % 60).padStart(2, '0'); };
  function status(s, warn, btn) {
    var el = $('status'); el.textContent = s; el.classList.toggle('warn', !!warn);
    if (btn) { var b = document.createElement('button'); b.className = 'pill'; b.textContent = btn[0]; b.onclick = btn[1]; el.appendChild(b); }
  }
  function now() { return base + (v.currentTime || 0); }
  function store(k, val) { try { localStorage.setItem('bmc-play-' + k, val); } catch (e) {} }
  function load(k, d) { try { var x = localStorage.getItem('bmc-play-' + k); return x === null ? d : x; } catch (e) { return d; } }

  /* ---------- Was kann der Browser? ---------- */
  var AUDIO_MIME = { aac: 'audio/mp4; codecs="mp4a.40.2"', mp3: 'audio/mpeg', ac3: 'audio/mp4; codecs="ac-3"', eac3: 'audio/mp4; codecs="ec-3"',
    dts: 'audio/mp4; codecs="dtsc"', truehd: 'audio/mp4; codecs="mlpa"', flac: 'audio/mp4; codecs="flac"', opus: 'audio/mp4; codecs="opus"', vorbis: 'audio/ogg; codecs="vorbis"' };
  var NAMES = { ac3: 'Dolby Digital (AC3)', eac3: 'Dolby Digital Plus', dts: 'DTS', truehd: 'Dolby TrueHD', hevc: 'x265/HEVC', h265: 'x265/HEVC' };
  function canAudio(c) {
    c = (c || '').toLowerCase(); var m = AUDIO_MIME[c]; if (!m) return true;
    try { return !!(v.canPlayType(m) || (window.MediaSource && MediaSource.isTypeSupported(m))); } catch (e) { return true; }
  }
  function stream(i) { return ((ms && ms.MediaStreams) || []).filter(function (s) { return s.Index === i; })[0]; }

  /* ---------- Quelle setzen ---------- */
  function src(at) {
    var tok = encodeURIComponent(C.token);
    if (mode === 'remux') {
      base = at || 0;
      return '/Videos/' + ID + '/stream.mp4?Static=false&MediaSourceId=' + ms.Id + '&VideoCodec=copy&AudioCodec=aac&PlaySessionId=' + psid +
        (audioIdx != null ? '&AudioStreamIndex=' + audioIdx : '') + (base > 0 ? '&StartTimeTicks=' + Math.round(base * TICKS) : '') + '&api_key=' + tok;
    }
    base = 0;
    return '/Videos/' + ID + '/stream?Static=true&MediaSourceId=' + ms.Id + '&PlaySessionId=' + psid + '&api_key=' + tok;
  }
  function start(at, autoplay) {
    v.src = src(at);
    if (mode === 'direct' && at > 0) v.addEventListener('loadedmetadata', function once() { v.removeEventListener('loadedmetadata', once); v.currentTime = at; });
    if (autoplay !== false) v.play().catch(function (e) { if (e && e.name === 'NotSupportedError') showError(); else if (!$('status').classList.contains('warn')) status('Zum Starten auf ▶ klicken.'); });
  }
  function seekTo(t) {
    t = Math.max(0, Math.min(total || t, t));
    if (mode === 'remux') { var playing = !v.paused; start(t, playing); } else v.currentTime = t;
    drawSubs();
  }
  function chooseMode() {
    var a = stream(audioIdx), wantRemux = false;
    if (a && !canAudio(a.Codec)) wantRemux = true;                      // z. B. Firefox + DTS/AC3
    if (audioIdx != null && defaultAudio != null && audioIdx !== defaultAudio) wantRemux = true;   // andere Tonspur
    mode = wantRemux && helper ? 'remux' : 'direct';
    if (wantRemux && !helper) {
      if (a && !canAudio(a.Codec)) status('Achtung: Dein Browser kann den Ton „' + (NAMES[(a.Codec || '').toLowerCase()] || a.Codec) + '“ nicht abspielen – das Bild läuft ohne Ton. Abhilfe: Verwaltung → Plugins → „Browser-Hilfe“ einschalten, oder Edge bzw. die App benutzen.', true);
      else status('Andere Tonspuren gehen im Browser nur mit dem Plugin „Browser-Hilfe“. Es läuft die Standard-Tonspur.', true);
    }
  }

  /* ---------- Untertitel (Text über VTTCue, mit Versatz; PGS als Bild) ---------- */
  var track = null;
  function clearSubs() {
    if (track) { Array.prototype.slice.call(track.cues || []).forEach(function (c) { track.removeCue(c); }); }
    pgsOn = false; $('pgs').hidden = true; if (pgsR) pgsR.set(null);
  }
  function drawSubs() {
    if (!track) { track = v.addTextTrack('subtitles', 'Untertitel', 'de'); }
    Array.prototype.slice.call(track.cues || []).forEach(function (c) { track.removeCue(c); });
    track.mode = 'showing';
    if (!subCues) return;
    var off = parseFloat(String($('offset').value).replace(',', '.')) || 0;
    subCues.forEach(function (c) {
      var s = c.s + off - base, e = c.e + off - base;
      if (e <= 0) return;
      try { track.addCue(new VTTCue(Math.max(0, s), e, c.t)); } catch (x) {}
    });
  }
  function setSub(val) {
    subCues = null; clearSubs(); store('sub', val);
    $('subToggle').classList.toggle('on', val !== 'off');
    if (val === 'off') return drawSubs();
    var s = stream(+val); if (!s) return;
    var tok = '?api_key=' + encodeURIComponent(C.token);
    var path = '/Videos/' + ID + '/' + ms.Id + '/Subtitles/' + s.Index + '/0/Stream.';
    if (/pgs/i.test(s.Codec || '')) {
      if (!window.BmcPgs) return status('Bild-Untertitel (PGS) können hier nicht angezeigt werden.', true);
      fetch(path + 'sup' + tok, { headers: { 'Authorization': AUTH } }).then(function (r) { return r.arrayBuffer(); }).then(function (b) {
        if ($('subtitle').value !== val) return;
        pgsR = pgsR || window.BmcPgs.Renderer($('pgs')); pgsR.set(window.BmcPgs.parse(b)); pgsOn = true; $('pgs').hidden = false;
      }).catch(function () { status('Untertitel konnten nicht geladen werden.', true); });
      return;
    }
    if (s.IsTextSubtitleStream === false) return status('Diese Untertitel (' + s.Codec + ') gehen nur mit Umrechnen – das schafft das NAS nicht.', true);
    api(path + 'js' + tok).then(function (j) {
      if ($('subtitle').value !== val) return;
      subCues = (j.TrackEvents || []).map(function (e) { return { s: e.StartPositionTicks / TICKS, e: e.EndPositionTicks / TICKS, t: e.Text }; });
      drawSubs();
    }).catch(function () { status('Untertitel konnten nicht geladen werden.', true); });
  }

  /* ---------- Fortschritt melden (Weiterschauen, Gesehen) ---------- */
  function report(kind) {
    if (!ms) return;
    var path = kind === 'start' ? '/Sessions/Playing' : kind === 'stop' ? '/Sessions/Playing/Stopped' : '/Sessions/Playing/Progress';
    fetch(path, { method: 'POST', keepalive: kind === 'stop', headers: { 'Authorization': AUTH, 'Content-Type': 'application/json' },
      body: JSON.stringify({ ItemId: ID, MediaSourceId: ms.Id, PlaySessionId: psid, PositionTicks: Math.round(now() * TICKS), IsPaused: v.paused,
        CanSeek: true, PlayMethod: mode === 'remux' ? 'DirectStream' : 'DirectPlay', AudioStreamIndex: audioIdx,
        SubtitleStreamIndex: $('subtitle').value === 'off' ? -1 : +$('subtitle').value, PlaybackRate: v.playbackRate }) }).catch(function () {});
  }
  var stopped = false;
  function stop() { if (!stopped && ms) { stopped = true; report('stop'); } }
  addEventListener('pagehide', stop);

  /* ---------- Wiedergabeliste: Folgen der Staffel bzw. Kapitel ---------- */
  function go(id, t) { stop(); location.replace('index.html?id=' + id + (t ? '&t=' + Math.floor(t) : '')); }
  function renderList() {
    var q = $('queue'); q.replaceChildren();
    if (queue.length > 1) {
      $('listTitle').textContent = 'Wiedergabeliste';
      $('listNote').textContent = item.SeriesName ? item.SeriesName + (item.SeasonName ? ' · ' + item.SeasonName : '') : (item.Album || '');
      queue.forEach(function (e, i) {
        var li = document.createElement('li'); li.className = i === qpos ? 'active' : ''; li.tabIndex = 0;
        li.textContent = (e.IndexNumber != null ? e.IndexNumber + '. ' : '') + e.Name;
        if (e.UserData && e.UserData.Played) { var s = document.createElement('span'); s.className = 'sub'; s.textContent = '✓ gesehen'; li.appendChild(s); }
        li.onclick = function () { if (i !== qpos) go(e.Id); };
        li.onkeydown = function (ev) { if (ev.key === 'Enter') li.onclick(); };
        q.append(li);
      });
    } else if (chapters.length) {
      $('listTitle').textContent = 'Kapitel';
      $('listNote').textContent = '';
      chapters.forEach(function (c, i) {
        var li = document.createElement('li'); li.tabIndex = 0; li.dataset.i = i;
        li.textContent = fmt(c.t) + ' · ' + (c.name || 'Kapitel ' + (i + 1));
        li.onclick = function () { seekTo(c.t); if (v.paused) v.play().catch(function () {}); };
        li.onkeydown = function (ev) { if (ev.key === 'Enter') li.onclick(); };
        q.append(li);
      });
    } else {
      $('listTitle').textContent = 'Wiedergabeliste';
      $('listNote').textContent = 'Nur dieser Titel.';
    }
    $('previous').disabled = !(queue.length > 1 && qpos > 0) && !chapters.length;
    $('next').disabled = !(queue.length > 1 && qpos < queue.length - 1) && !chapters.length;
  }
  function markChapters() {
    var m = $('marks'); m.replaceChildren();
    if (!total) return;
    chapters.forEach(function (c) { if (c.t > 0) { var i = document.createElement('i'); i.style.left = (c.t / total * 100) + '%'; m.appendChild(i); } });
    var cur = -1; chapters.forEach(function (c, i) { if (c.t <= now()) cur = i; });
    Array.prototype.forEach.call($('queue').querySelectorAll('li[data-i]'), function (li) { li.className = +li.dataset.i === cur ? 'active' : ''; });
  }
  function nextTitle() {
    if (queue.length > 1 && qpos < queue.length - 1) return go(queue[qpos + 1].Id);
    var t = now(), n = chapters.filter(function (c) { return c.t > t + 1; })[0];
    if (n) seekTo(n.t);
  }
  function prevTitle() {
    if (queue.length > 1 && qpos > 0 && now() < 10) return go(queue[qpos - 1].Id);
    var t = now(), p = chapters.filter(function (c) { return c.t < t - 3; }).pop();
    if (p) seekTo(p.t); else seekTo(0);
  }

  /* ---------- Bedienung (wie design/player/player.js) ---------- */
  $('play').onclick = function () { v.paused ? v.play().catch(function () { status('Wiedergabe fehlgeschlagen.', true); }) : v.pause(); };
  $('previous').onclick = prevTitle; $('next').onclick = nextTitle;
  $('rew').onclick = function () { seekTo(now() - 10); }; $('forward').onclick = function () { seekTo(now() + 10); };
  var seeking = false;
  $('seek').oninput = function (e) { seeking = true; $('clock').textContent = fmt(total * (+e.target.value / 1000)) + ' / ' + fmt(total); };
  $('seek').onchange = function (e) { seeking = false; if (total) seekTo(total * (+e.target.value / 1000)); };
  $('mute').onclick = function () { v.muted = !v.muted; };
  $('volume').oninput = function (e) { v.volume = +e.target.value; v.muted = false; store('vol', v.volume); };
  $('speed').onchange = function (e) { v.playbackRate = +e.target.value; };
  $('fullscreen').onclick = function () { document.fullscreenElement ? document.exitFullscreen() : P.requestFullscreen().catch(function () { status('Vollbild ist hier nicht verfügbar.'); }); };
  $('pip').onclick = function () {
    (document.pictureInPictureElement ? document.exitPictureInPicture() : v.requestPictureInPicture()).catch(function () { status('Bild im Bild wird nicht unterstützt.'); });
  };
  $('subtitle').onchange = function (e) { setSub(e.target.value); };
  $('subToggle').onclick = function () {
    var s = $('subtitle');
    if (s.value === 'off' && s.options.length > 1) s.value = load('lastsub', s.options[1].value); else { if (s.value !== 'off') store('lastsub', s.value); s.value = 'off'; }
    if (!s.querySelector('option[value="' + s.value + '"]')) s.value = s.options[1].value;
    s.dispatchEvent(new Event('change'));
  };
  $('offset').onchange = function () { drawSubs(); status('Untertitel-Versatz: ' + ($('offset').value || 0) + ' s'); };
  $('autonext').checked = load('autonext', '1') === '1';
  $('autonext').onchange = function () { store('autonext', $('autonext').checked ? '1' : '0'); };
  $('audio').onchange = function (e) {
    audioIdx = +e.target.value; var at = now(), was = !v.paused;
    chooseMode(); start(at, was);
  };
  $('sleep').onchange = function (e) {
    var x = e.target.value; sleepEnd = x === 'end'; sleepAt = x !== '0' && x !== 'end' ? Date.now() + (+x) * 60000 : 0;
    $('sleepLeft').textContent = sleepEnd ? 'hält am Ende an' : ''; tickSleep();
  };
  function tickSleep() {
    if (!sleepAt) return;
    var left = sleepAt - Date.now();
    if (left <= 0) { sleepAt = 0; v.pause(); $('sleep').value = '0'; $('sleepLeft').textContent = ''; status('Schlaftimer: Wiedergabe angehalten.'); return; }
    $('sleepLeft').textContent = 'noch ' + Math.ceil(left / 60000) + ' Min.';
  }
  setInterval(tickSleep, 15000);
  $('back').onclick = function (e) {
    e.preventDefault(); stop();
    if (history.length > 1 && document.referrer && document.referrer.indexOf(location.origin) === 0) history.back();
    else location.href = '/web/#/details?id=' + ID;
  };

  // Steuerleiste nach 3 s ohne Bewegung ausblenden (Klasse idle aus dem Design)
  var idleT = 0;
  function poke() { P.classList.remove('idle'); clearTimeout(idleT); idleT = setTimeout(function () { if (!v.paused) P.classList.add('idle'); }, 3000); }
  ['mousemove', 'touchstart', 'keydown'].forEach(function (ev) { P.addEventListener(ev, poke, { passive: true }); });
  v.addEventListener('click', function () { $('play').click(); });
  v.addEventListener('dblclick', function () { $('fullscreen').click(); });

  v.addEventListener('timeupdate', function () {
    if (!seeking) {
      var t = now();
      $('seek').value = total > 0 ? Math.round(t / total * 1000) : 0;
      $('clock').textContent = fmt(t) + ' / ' + fmt(total);
    }
    if (pgsOn && pgsR) pgsR.draw(now() - (parseFloat($('offset').value) || 0));
    if (Date.now() - lastSave > 10000) { lastSave = Date.now(); report('progress'); markChapters(); }
  });
  v.addEventListener('durationchange', function () { if (!total && mode === 'direct' && isFinite(v.duration)) { total = v.duration; markChapters(); } });
  v.addEventListener('play', function () { $('play').textContent = '⏸'; if (!$('status').classList.contains('warn')) status('▶ ' + (item ? (item.SeriesName ? item.SeriesName + ' – ' : '') + item.Name : '')); poke(); report('progress'); });
  v.addEventListener('pause', function () { $('play').textContent = '▶'; P.classList.remove('idle'); report('progress'); });
  v.addEventListener('volumechange', function () { $('mute').textContent = v.muted || v.volume === 0 ? '🔇' : '🔊'; });
  v.addEventListener('ended', function () {
    if (mode === 'remux' && total && now() < total - 5) return;   // Teilstück zu Ende – nicht der Film
    stop();
    if (sleepEnd) { status('Schlaftimer: Ende des Titels – angehalten.'); return; }
    if ($('autonext').checked && queue.length > 1 && qpos < queue.length - 1) { status('Nächster Titel …'); setTimeout(function () { go(queue[qpos + 1].Id); }, 1500); }
    else status('Wiedergabe beendet.');
  });
  v.addEventListener('error', showError);
  function showError() {
    var vs = ((ms && ms.MediaStreams) || []).filter(function (s) { return s.Type === 'Video'; })[0];
    var codec = vs ? (vs.Codec || '').toLowerCase() : '';
    var msg = 'Wiedergabe nicht möglich: Dein Browser kann ' + (NAMES[codec] ? 'das Videoformat „' + NAMES[codec] + '“' : 'diese Datei') + ' nicht abspielen.';
    if (helper) status(msg, true, ['Mit dem Butchies-Web-Player abspielen', function () { stop(); location.href = '/web/bmc/player/player.html?id=' + ID + '&t=' + Math.floor(now()); }]);
    else status(msg + ' Abhilfe: Edge, die App, oder Verwaltung → Plugins → „Browser-Hilfe“ einschalten.', true);
  }
  document.addEventListener('keydown', function (e) {
    var tag = document.activeElement && document.activeElement.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || tag === 'BUTTON') return;
    var k = e.key.toLowerCase();
    if (e.code === 'Space') { e.preventDefault(); $('play').click(); }
    else if (e.key === 'ArrowLeft') $('rew').click(); else if (e.key === 'ArrowRight') $('forward').click();
    else if (k === 'f') $('fullscreen').click(); else if (k === 'm') $('mute').click(); else if (k === 'n') $('next').click();
  });

  /* ---------- Start ---------- */
  if (!ID || !C.token) { status('Bitte zuerst im Media Center anmelden.', true); return; }
  var vol = parseFloat(load('vol', '1')); if (isFinite(vol)) { v.volume = vol; $('volume').value = vol; }
  api('/Users/' + C.user + '/Items/' + ID).then(function (it) {
    item = it;
    document.title = it.Name + ' | Butchies Media Center';
    $('title').innerHTML = '';
    $('title').textContent = it.SeriesName || it.Name;
    if (it.Type === 'Audio') P.classList.add('audio');
    if (it.SeriesName) { var sm = document.createElement('small'); sm.textContent = (it.ParentIndexNumber != null ? 'Staffel ' + it.ParentIndexNumber + ', Folge ' + (it.IndexNumber || '') + ' · ' : '') + it.Name; $('title').appendChild(sm); }
    else if (it.ProductionYear) { var sy = document.createElement('small'); sy.textContent = String(it.ProductionYear); $('title').appendChild(sy); }
    total = it.RunTimeTicks ? it.RunTimeTicks / TICKS : 0;
    chapters = (it.Chapters || []).map(function (c) { return { t: c.StartPositionTicks / TICKS, name: c.Name }; });
    var jobs = [api('/Items/' + ID + '/PlaybackInfo?BmcPlayer=1&UserId=' + C.user, { method: 'POST', body: JSON.stringify({ DeviceProfile: {} }) })];
    if (it.Type === 'Audio' && it.AlbumId) jobs.push(api('/Users/' + C.user + '/Items?ParentId=' + it.AlbumId + '&SortBy=ParentIndexNumber,IndexNumber,SortName').catch(function () { return null; }));
    else if (it.Type === 'Episode' && it.SeriesId) jobs.push(api('/Shows/' + it.SeriesId + '/Episodes?UserId=' + C.user + (it.SeasonId ? '&SeasonId=' + it.SeasonId : '')).catch(function () { return null; }));
    return Promise.all(jobs);
  }).then(function (r) {
    var pi = r[0];
    if (pi.ErrorCode === 'NotAllowed') throw new Error('4K-Filme sind auf diesem NAS gesperrt (zu schwach). Bitte die 1080p-Fassung benutzen.');
    if (!pi.MediaSources || !pi.MediaSources.length) throw new Error('Für diesen Titel gibt es keine abspielbare Datei.');
    ms = pi.MediaSources[0]; psid = pi.PlaySessionId || ''; helper = !!pi.BmcHelper;
    if (r[1] && r[1].Items) { queue = r[1].Items; qpos = queue.map(function (e) { return e.Id; }).indexOf(ID); }
    // Tonspuren
    var aud = (ms.MediaStreams || []).filter(function (s) { return s.Type === 'Audio'; });
    defaultAudio = ms.DefaultAudioStreamIndex != null ? ms.DefaultAudioStreamIndex : (aud[0] ? aud[0].Index : null);
    var want = qs.get('a'); audioIdx = want != null && stream(+want) ? +want : defaultAudio;
    $('audio').replaceChildren.apply($('audio'), aud.map(function (s) { var o = new Option(s.DisplayTitle || s.Codec, s.Index); o.selected = s.Index === audioIdx; return o; }));
    $('audio').disabled = aud.length < 2;
    // Untertitel
    var subs = (ms.MediaStreams || []).filter(function (s) { return s.Type === 'Subtitle'; });
    subs.forEach(function (s) { $('subtitle').appendChild(new Option(s.DisplayTitle || s.Codec, s.Index)); });
    var sIdx = qs.get('s') != null ? qs.get('s') : (ms.DefaultSubtitleStreamIndex != null && ms.DefaultSubtitleStreamIndex >= 0 ? String(ms.DefaultSubtitleStreamIndex) : 'off');
    if (!$('subtitle').querySelector('option[value="' + sIdx + '"]')) sIdx = 'off';
    $('subtitle').value = sIdx;
    renderList();
    chooseMode();
    var t = qs.has('t') ? +qs.get('t') : ((item.UserData && item.UserData.PlaybackPositionTicks) || 0) / TICKS;
    start(t > 0 && (!total || t < total - 10) ? t : 0);
    setSub(sIdx);
    report('start');
    markChapters();
    if (mode === 'remux') status('Ton wird vom NAS umgepackt (Browser-Hilfe).');
  }).catch(function (e) { status(String(e.message || e), true); });
})();
