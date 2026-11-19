/* Butchies Media Center – technische Ergänzung (immer aktiv, ändert nichts am Aussehen). */
(function () {
  'use strict';
  function api() { return window.ApiClient; }
  // Untertitel immer selbst zeichnen (wie Firefox/Edge): Chromes eigene Anzeige verrutscht nach dem Spulen
  // bei umgepackten Filmen (MKV -> MP4). Nur wenn der Nutzer nicht ausdrücklich „Nativ“ gewählt hat.
  var subFixed = null;
  function subStyle() {
    var c = api(), uid = c && c.getCurrentUserId && c.getCurrentUserId();
    if (!uid || subFixed === uid) return;
    try {
      var key = uid + '-localplayersubtitleappearance3', cur = JSON.parse(localStorage.getItem(key) || '{}');
      if (cur.subtitleStyling !== 'Native' && cur.subtitleStyling !== 'Custom') {
        cur.subtitleStyling = 'Custom';
        localStorage.setItem(key, JSON.stringify(cur));
      }
    } catch (e) { /* ohne Speicher: Standard bleibt */ }
    subFixed = uid;
  }
  setInterval(subStyle, 1000);
})();
/* Hinweis im Jellyfin-Fehlerfenster, wenn der Browser x265/HEVC nicht abspielen kann
   (das NAS ist zu schwach, um Video umzurechnen). */
(function () {
  'use strict';
  function hevcOk() {
    try {
      var M = window.MediaSource || window.ManagedMediaSource;
      return !!(M && (M.isTypeSupported('video/mp4; codecs="hvc1.1.6.L120.90"') || M.isTypeSupported('video/mp4; codecs="hev1.1.6.L120.90"') ||
                      M.isTypeSupported('video/mp4; codecs="hvc1.2.4.L120.90"')));
    } catch (e) { return false; }
  }
  function check() {
    if (hevcOk() || document.querySelector('.dialog .bmc4kHint')) return;
    var dlgs = document.querySelectorAll('.dialog');
    for (var i = 0; i < dlgs.length; i++) {
      var d = dlgs[i];
      if (d.querySelector('.bmcHevcHint') || !/kompatib|compatible/i.test(d.textContent || '')) continue;
      var p = document.createElement('div');
      p.className = 'bmcHevcHint';
      p.setAttribute('style', 'margin:1em auto 0;max-width:30em;text-align:left;font-size:.95em;line-height:1.45;opacity:.95');
      p.innerHTML = '<b>Meist ist es ein x265-/HEVC-Film:</b> dieser Browser kann ihn nicht abspielen, und das NAS ist zu schwach, ' +
        'um das Video umzurechnen. So klappt es:<br>• am PC das Programm <b>„Butchies Media Center“</b> (Windows-Player)<br>' +
        '• oder Microsoft <b>Edge</b> / Chrome mit HEVC-Unterstützung der Grafikkarte<br>• auf Handy/Fernseher die Butchies-Apps';
      var txt = d.querySelector('.text, p, .dialogContentInner') || d;
      txt.appendChild(p);
    }
  }
  function check4k() {  // Wiedergabe gesperrt (4K / unbekannte Auflösung): verständlich erklären
    var dlgs = document.querySelectorAll('.dialog');
    for (var i = 0; i < dlgs.length; i++) {
      var d = dlgs[i];
      if (d.querySelector('.bmc4kHint') || !/nicht erlaubt|not allowed/i.test(d.textContent || '')) continue;
      var p = document.createElement('div');
      p.className = 'bmc4kHint';
      p.setAttribute('style', 'margin:1em auto 0;max-width:30em;text-align:left;font-size:.95em;line-height:1.45;opacity:.95');
      p.innerHTML = '<b>Dieser Film ist auf dem NAS gesperrt.</b> Filme über 1080p (z. B. 4K) und Filme, deren Auflösung noch nicht ' +
        'gelesen werden konnte, gibt das Media Center nicht heraus – das NAS schafft die Datenmenge nicht ruckelfrei.<br>' +
        '• Ist der Film gerade erst dazugekommen: ein paar Minuten warten, dann wird die Auflösung gelesen.<br>' +
        '• 4K-Filme bitte als 1080p-Fassung in die Bibliothek legen.';
      (d.querySelector('.text, p, .dialogContentInner') || d).appendChild(p);
    }
  }
  new MutationObserver(function () { check(); check4k(); }).observe(document.documentElement, { childList: true, subtree: true });
})();
/* Butchies-Player: Kann der Browser einen Film nicht selbst abspielen (z. B. x265 ohne Grafikkarten-Unterstützung),
   öffnet sich automatisch der Butchies-Player. Er entschlüsselt den Film auf diesem Gerät (WebAssembly),
   das NAS streamt nur die Originaldatei. */
(function () {
  'use strict';
  function hevcOk() {
    try {
      var M = window.MediaSource || window.ManagedMediaSource;
      return !!(M && (M.isTypeSupported('video/mp4; codecs="hvc1.1.6.L120.90"') || M.isTypeSupported('video/mp4; codecs="hev1.1.6.L120.90"')));
    } catch (e) { return false; }
  }
  // gewählte Ton-/Untertitelspur aus der Anfrage merken, damit der Butchies-Player sie übernimmt
  function pickIdx(url, b) {
    var r = {}, q = {};
    try { new URL(url, location.href).searchParams.forEach(function (v, k) { q[k.toLowerCase()] = v; }); } catch (e) {}
    var s = q.subtitlestreamindex !== undefined ? q.subtitlestreamindex : (b && b.SubtitleStreamIndex);
    var a = q.audiostreamindex !== undefined ? q.audiostreamindex : (b && b.AudioStreamIndex);
    if (s !== undefined && s !== null && s !== '' && !isNaN(+s)) r.s = +s;
    if (a !== undefined && a !== null && a !== '' && !isNaN(+a)) r.a = +a;
    return r;
  }
  /* Alles, was in der Jellyfin-Oberfläche abgespielt wird, läuft im Butchies-Player (bmcweb/play) */
  function ownPlayer(id, url, body) {
    var q = {}, start = 0, sel = {};
    try { new URL(url, location.href).searchParams.forEach(function (v, k) { q[k.toLowerCase()] = v; }); } catch (e) {}
    var jb = {};
    try { jb = typeof body === 'string' && body ? JSON.parse(body) : {}; } catch (e) {}
    start = ((jb.StartTimeTicks || +q.starttimeticks || 0) / 1e7);
    sel = pickIdx(url, jb);
    var u = '/web/bmc/play/index.html?id=' + id + (start > 0 ? '&t=' + Math.floor(start) : '');
    if (sel.a !== undefined) u += '&a=' + sel.a;
    if (sel.s !== undefined) u += '&s=' + (sel.s < 0 ? 'off' : sel.s);
    location.href = u;
  }
  var pending = null, nativeFetch = window.fetch;
  if (!nativeFetch || window.__bmcFetch) return;
  window.__bmcFetch = true;
  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    var m = /\/Items\/([0-9a-f]{32})\/PlaybackInfo/i.exec(url);
    if (!m) return nativeFetch.apply(this, arguments);
    if (window.bmcOwnPlayer !== false) {
      var bp = (init && typeof init.body === 'string') ? Promise.resolve(init.body)
        : (input && typeof input !== 'string' && input.clone) ? input.clone().text().catch(function () { return ''; }) : Promise.resolve('');
      bp.then(function (b) { ownPlayer(m[1].toLowerCase(), url, b); });
      return new Promise(function () {});   // Jellyfin-Player startet gar nicht erst
    }
    var self = this, start = 0, sel = {};
    var bodyP = (init && typeof init.body === 'string') ? Promise.resolve(init.body)
      : (input && typeof input !== 'string' && input.clone) ? input.clone().text().catch(function () { return ''; }) : Promise.resolve('');
    if (!hevcOk()) {
      var nu = url + (url.indexOf('?') >= 0 ? '&' : '?') + 'BmcNoHevc=1';
      input = typeof input === 'string' ? nu : new Request(nu, input);
    }
    return bodyP.then(function (b) {
      try { var jb = JSON.parse(b || '{}'); start = (jb.StartTimeTicks || 0) / 1e7; sel = pickIdx(url, jb); } catch (e) {}
      return nativeFetch.call(self, input, init);
    }).then(function (r) {
      try {
        r.clone().json().then(function (j) {
          if (j && j.ErrorCode === 'NoCompatibleStream' && j.BmcPlayer) pending = { id: m[1].toLowerCase(), start: start, sel: sel, at: Date.now() };
        }).catch(function () {});
      } catch (e) {}
      return r;
    });
  };
  // Die Jellyfin-Oberfläche fragt PlaybackInfo über axios (XMLHttpRequest) ab
  var XO = XMLHttpRequest.prototype.open, XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    var m = /\/Items\/([0-9a-f]{32})\/PlaybackInfo/i.exec(String(url || ''));
    this.__bmc = m ? m[1].toLowerCase() : null; this.__bmcUrl = String(url || '');
    if (m && !hevcOk()) {
      var a = Array.prototype.slice.call(arguments);
      a[1] = String(url) + (String(url).indexOf('?') >= 0 ? '&' : '?') + 'BmcNoHevc=1';
      return XO.apply(this, a);
    }
    return XO.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (body) {
    if (this.__bmc && window.bmcOwnPlayer !== false) { ownPlayer(this.__bmc, this.__bmcUrl, body); return; }
    if (this.__bmc) {
      var id = this.__bmc, start = 0, x = this, sel = {};
      try { var jb = JSON.parse(body || '{}'); start = (jb.StartTimeTicks || 0) / 1e7; sel = pickIdx(x.__bmcUrl, jb); } catch (e) {}
      this.addEventListener('load', function () {
        try {
          var j = JSON.parse(x.responseText || '{}');
          if (j.ErrorCode === 'NoCompatibleStream' && j.BmcPlayer) pending = { id: id, start: start, sel: sel, at: Date.now() };
        } catch (e) {}
      });
    }
    return XS.apply(this, arguments);
  };
  function go() {
    if (!pending || Date.now() - pending.at > 20000) return false;
    var p = pending; pending = null;
    var extra = '';
    if (p.sel && p.sel.s !== undefined) extra += '&s=' + p.sel.s;
    if (p.sel && p.sel.a !== undefined) extra += '&a=' + p.sel.a;
    location.href = '/web/bmc/player/player.html?id=' + p.id + '&t=' + Math.floor(p.start) + extra;
    return true;
  }
  new MutationObserver(function () {
    var d = document.querySelector('.dialogContainer .dialog');
    if (d && /kompatib|compatible/i.test(d.textContent || '') && go()) d.style.visibility = 'hidden';
  }).observe(document.documentElement, { childList: true, subtree: true });
})();
