/* Butchies-Player-Aussehen (Standard): Aufbau wie gewohnt aus Emby, eigene Umsetzung für die Jellyfin-Weboberfläche.
   Oben: Zurück + Logo links, Lautstärke/Cast/Bild-in-Bild rechts.
   Unten: kleine Zeile (Jahr bzw. „S7:E3 - Folgenname“) + großer Titel links, Untertitel/Ton/Einstellungen/Vollbild rechts,
   Zeitleiste über die ganze Breite, darunter links die Zeit, rechts „-Rest / Ende-Uhrzeit“,
   ganz unten links: Vorherige, Zurückspulen, Abspielen, Vorspulen, Nächste. */
(function () {
  'use strict';
  var curId = null, curItem = null, timer = null, moved = [];

  function $(s, r) { return (r || document).querySelector(s); }
  function osdPage() { var p = $('#videoOsdPage'); return p && !p.classList.contains('hide') && p.offsetParent !== null ? p : null; }
  function currentId() {
    var v = $('#videoOsdPage video') || $('video');
    var src = v && (v.currentSrc || v.src) || '';
    var m = src.match(/\/(?:Videos|Audio)\/([0-9a-f]{32})\//i);
    return m ? m[1].toLowerCase() : null;
  }
  function api() { return window.ApiClient; }
  function img(id, type, tag, h) { return api().getUrl('Items/' + id + '/Images/' + type, { maxHeight: h || 120, tag: tag, quality: 90 }); }
  function secs(t) {
    var p = String(t || '').trim().replace(/^-/, '').split(':').map(Number);
    if (!p.length || p.some(isNaN)) return null;
    return p.reduce(function (a, b) { return a * 60 + b; }, 0);
  }
  function fmt(s) {
    s = Math.max(0, Math.round(s));
    var h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0');
  }
  function clock(d) { return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }

  // ---- Knöpfe umsetzen (und beim Verlassen zurücklegen, damit die Oberfläche sauber bleibt)
  function move(el, target, before) {
    if (!el || !target || el.parentNode === target) return;
    if (!el.__bmcHome) { el.__bmcHome = { parent: el.parentNode, next: el.nextSibling }; moved.push(el); }
    el.classList.add('bmcMoved');
    target.insertBefore(el, before && before.parentNode === target ? before : null);
  }
  function restore() {
    moved.forEach(function (el) {
      var h = el.__bmcHome; el.classList.remove('bmcMoved');
      if (h && h.parent && document.contains(h.parent)) h.parent.insertBefore(el, h.next && h.next.parentNode === h.parent ? h.next : null);
      else if (el.parentNode) el.parentNode.removeChild(el);
      delete el.__bmcHome;
    });
    moved = [];
  }

  function cleanup() {
    restore(); unIcons(); closeMenus();
    ['#bmcLogo', '#bmcBar', '#bmcRemain', '#bmcTabs', '#bmcPanel', '#bmcSpeed'].forEach(function (s) { var e = $(s); if (e) e.remove(); });
    document.body.classList.remove('bmc-osd');
    curId = null; curItem = null;
  }

  function layout(page) {
    var controls = $('.osdControls', page);
    if (!controls) return;
    var bar = $('#bmcBar');
    if (!bar || bar.parentNode !== controls) {
      if (bar) bar.remove();
      bar = document.createElement('div'); bar.id = 'bmcBar';
      bar.innerHTML = '<div id="bmcMeta"></div><div id="bmcRight"></div>';
      controls.insertBefore(bar, controls.firstChild);
      if (curItem) buildMeta(curItem);
    }
    var right = $('#bmcRight');
    ['.btnSubtitles', '.btnAudio'].forEach(function (s) { move($(s, page), right); });
    if (!$('#bmcSpeed')) {
      var sp = document.createElement('button');
      sp.id = 'bmcSpeed'; sp.type = 'button'; sp.className = 'autoSize paper-icon-button-light'; sp.title = 'Wiedergabegeschwindigkeit';
      sp.innerHTML = '<span class="xlargePaperIconButton material-icons speed" aria-hidden="true"></span>';
      sp.addEventListener('click', function (e) { e.stopPropagation(); speedMenu(sp, page); });
      right.appendChild(sp);
    }
    ['.btnVideoOsdSettings', '.btnFullscreen'].forEach(function (s) { move($(s, page), right); });
    var fav = $('.btnUserRating', page); if (fav) fav.classList.add('bmcGone');
    tabs(page);
    // Lautstärke und Bild-in-Bild bleiben in der Player-Ansicht (Jellyfin sucht sie dort) und werden per CSS oben rechts angezeigt
  }

  function buildLogo(it) {
    var box = $('#bmcLogo');
    if (!box) { box = document.createElement('div'); box.id = 'bmcLogo'; document.body.appendChild(box); }
    box.innerHTML = '';
    var logoId = null, logoTag = null;
    if (it.ImageTags && it.ImageTags.Logo) { logoId = it.Id; logoTag = it.ImageTags.Logo; }
    else if (it.ParentLogoItemId && it.ParentLogoImageTag) { logoId = it.ParentLogoItemId; logoTag = it.ParentLogoImageTag; }
    if (logoId) {
      var i = document.createElement('img');
      i.alt = ''; i.src = img(logoId, 'Logo', logoTag, 120);
      i.onerror = function () { box.innerHTML = ''; box.appendChild(textLogo(it)); };
      box.appendChild(i);
    } else box.appendChild(textLogo(it));
  }
  function textLogo(it) {
    var s = document.createElement('span'); s.className = 'bmcLogoText';
    s.textContent = it.Type === 'Episode' && it.SeriesName ? it.SeriesName : cleanTitle(it.Name);
    return s;
  }
  function cleanTitle(n) { return String(n || '').replace(/\s*\((19|20)\d\d\)\s*$/, ''); }
  function year(it) {
    if (it.ProductionYear) return String(it.ProductionYear);
    var m = String(it.Name || '').match(/\(((?:19|20)\d\d)\)\s*$/);
    return m ? m[1] : '';
  }

  function buildMeta(it) {
    var meta = $('#bmcMeta');
    if (!meta) return;
    var small, big;
    if (it.Type === 'Episode') {
      var se = (it.ParentIndexNumber != null ? 'S' + it.ParentIndexNumber : '') + (it.IndexNumber != null ? ':E' + it.IndexNumber : '');
      small = (se ? se + ' - ' : '') + (it.Name || '');
      big = it.SeriesName || it.Name || '';
    } else {
      small = year(it);
      big = cleanTitle(it.Name);
    }
    meta.innerHTML = '';
    if (small) { var a = document.createElement('div'); a.className = 'bmcLine1'; a.textContent = small; meta.appendChild(a); }
    var b = document.createElement('div'); b.className = 'bmcLine2'; b.textContent = big; meta.appendChild(b);
  }

  function updateTimes(page) {
    var row = $('.osdControls > .flex.align-items-center', page);
    if (!row) return;
    var r = $('#bmcRemain');
    if (!r || r.parentNode !== row) { if (r) r.remove(); r = document.createElement('div'); r.id = 'bmcRemain'; r.className = 'osdTextContainer'; row.appendChild(r); }
    var pos = secs(($('.osdPositionText', row) || {}).textContent);
    var tot = curItem && curItem.RunTimeTicks ? curItem.RunTimeTicks / 1e7 : null;
    if (!tot) { var v = $('video', page); if (v && isFinite(v.duration) && v.duration > 0) tot = v.duration; }
    if (pos == null || !tot) { r.textContent = ''; return; }
    var rest = Math.max(0, tot - pos);
    r.textContent = '-' + fmt(rest) + '  /  ' + clock(new Date(Date.now() + rest * 1000));
  }

  function swapIcon(el, from, to) { if (el && !el.classList.contains(to)) { from.forEach(function (c) { el.classList.remove(c); }); el.classList.add(to); } }
  function icons(page) {  // Symbole wie gewohnt: ‹ zurück, 10-s-Spulen, Ton als Klangwelle
    swapIcon($('.btnRewind .material-icons', page), ['fast_rewind', 'replay_10'], 'replay_10');
    swapIcon($('.btnFastForward .material-icons', page), ['fast_forward', 'forward_30'], 'forward_10');
    swapIcon($('.btnAudio .material-icons', page), ['audiotrack'], 'graphic_eq');
    swapIcon($('.skinHeader.osdHeader .headerBackButton .material-icons'), ['arrow_back'], 'arrow_back_ios_new');
  }
  function unIcons() {
    var b = $('.skinHeader .headerBackButton .material-icons');
    if (b && b.classList.contains('arrow_back_ios_new')) { b.classList.remove('arrow_back_ios_new'); b.classList.add('arrow_back'); }
  }

  // ---- Wiedergabegeschwindigkeit
  function closeMenus() { var m = $('#bmcMenu'); if (m) m.remove(); }
  function speedMenu(btn, page) {
    if ($('#bmcMenu')) { closeMenus(); return; }
    var v = $('video', page); if (!v) return;
    var m = document.createElement('div'); m.id = 'bmcMenu';
    [0.5, 0.75, 1, 1.25, 1.5, 2].forEach(function (r) {
      var b = document.createElement('button'); b.type = 'button';
      b.textContent = (r === 1 ? 'Normal' : String(r).replace('.', ',') + 'x');
      if (Math.abs(v.playbackRate - r) < 0.01) b.className = 'on';
      b.addEventListener('click', function (e) { e.stopPropagation(); v.playbackRate = r; closeMenus(); });
      m.appendChild(b);
    });
    document.body.appendChild(m);
    var r = btn.getBoundingClientRect();
    m.style.right = Math.max(8, innerWidth - r.right) + 'px'; m.style.bottom = (innerHeight - r.top + 8) + 'px';
    setTimeout(function () { document.addEventListener('click', closeMenus, { once: true }); }, 0);
  }

  // ---- Reiter unter dem Player: Info, Kapitel, Besetzung & Mitwirkende, Als Nächstes
  var tabOpen = null, tabItem = null;
  function tabs(page) {
    var bottom = $('.videoOsdBottom .osdControls', page);
    if (!bottom || !curItem) return;
    var row = $('#bmcTabs');
    if (row && row.parentNode === bottom && tabItem === curItem.Id) return;
    if (row) row.remove(); var old = $('#bmcPanel'); if (old) old.remove();
    tabItem = curItem.Id; tabOpen = null;
    row = document.createElement('div'); row.id = 'bmcTabs';
    var list = [['info', 'Info'], ['chapters', 'Kapitel']];
    if ((curItem.People || []).length) list.push(['cast', 'Besetzung & Mitwirkende']);
    if (curItem.Type === 'Episode') list.push(['next', 'Als Nächstes']);
    list.forEach(function (t) {
      var b = document.createElement('button'); b.type = 'button'; b.dataset.tab = t[0]; b.textContent = t[1];
      b.addEventListener('click', function (e) { e.stopPropagation(); openTab(t[0], page); });
      row.appendChild(b);
    });
    var panel = document.createElement('div'); panel.id = 'bmcPanel'; panel.hidden = true;
    bottom.appendChild(row); bottom.appendChild(panel);
  }
  function card(imgUrl, title, sub, onClick, wide) {
    var c = document.createElement('button'); c.type = 'button'; c.className = 'bmcCard' + (wide ? ' wide' : '');
    var im = document.createElement('div'); im.className = 'bmcCardImg';
    if (imgUrl) im.style.backgroundImage = 'url("' + imgUrl + '")'; else im.classList.add('empty');
    var t = document.createElement('div'); t.className = 'bmcCardT'; t.textContent = title;
    c.appendChild(im); c.appendChild(t);
    if (sub) { var u = document.createElement('div'); u.className = 'bmcCardS'; u.textContent = sub; c.appendChild(u); }
    if (onClick) c.addEventListener('click', function (e) { e.stopPropagation(); onClick(); }); else c.disabled = true;
    return c;
  }
  function seekTo(page, sec) { var v = $('video', page); if (v) { try { v.currentTime = sec; } catch (e) {} } }
  function openTab(kind, page) {
    var panel = $('#bmcPanel'); if (!panel) return;
    [].forEach.call($('#bmcTabs').children, function (b) { b.classList.toggle('on', b.dataset.tab === kind && tabOpen !== kind); });
    if (tabOpen === kind) { tabOpen = null; panel.hidden = true; return; }
    tabOpen = kind; panel.hidden = false; panel.innerHTML = ''; panel.className = 'p-' + kind;
    var it = curItem, c = api();
    if (kind === 'info') {
      var h = document.createElement('div'); h.className = 'bmcInfo';
      var facts = [year(it), it.OfficialRating, it.RunTimeTicks ? Math.round(it.RunTimeTicks / 6e8) + ' Min.' : '',
        it.CommunityRating ? '★ ' + it.CommunityRating.toFixed(1).replace('.', ',') : '', (it.Genres || []).slice(0, 3).join(', ')].filter(Boolean);
      var f = document.createElement('div'); f.className = 'bmcFacts'; f.textContent = facts.join('   ·   '); h.appendChild(f);
      var o = document.createElement('div'); o.className = 'bmcOverview'; o.textContent = it.Overview || 'Keine Beschreibung vorhanden.'; h.appendChild(o);
      panel.appendChild(h);
    } else if (kind === 'chapters') {
      var tot = it.RunTimeTicks ? it.RunTimeTicks / 1e7 : (($('video', page) || {}).duration || 0);
      var ch = (it.Chapters || []).map(function (x, i) { return { n: x.Name || ('Kapitel ' + (i + 1)), t: x.StartPositionTicks / 1e7 }; });
      if (!ch.length && tot) for (var t = 0, i = 1; t < tot; t += 600, i++) ch.push({ n: 'Kapitel ' + i, t: t });
      var bd = it.BackdropImageTags && it.BackdropImageTags[0] ? img(it.Id, 'Backdrop', it.BackdropImageTags[0], 200)
        : (it.ParentBackdropItemId && it.ParentBackdropImageTags ? img(it.ParentBackdropItemId, 'Backdrop', it.ParentBackdropImageTags[0], 200) : null);
      ch.forEach(function (x) { panel.appendChild(card(bd, x.n, fmt(x.t), function () { seekTo(page, x.t); }, true)); });
    } else if (kind === 'cast') {
      (it.People || []).slice(0, 30).forEach(function (pp) {
        var u = pp.PrimaryImageTag ? img(pp.Id, 'Primary', pp.PrimaryImageTag, 300) : null;
        panel.appendChild(card(u, pp.Name, pp.Role || (pp.Type === 'Director' ? 'Regie' : ''), null));
      });
    } else if (kind === 'next') {
      c.getEpisodes(it.SeriesId, { userId: c.getCurrentUserId(), Fields: 'Overview' }).then(function (r) {
        if (tabOpen !== 'next') return;
        var eps = r.Items || [], k = eps.findIndex(function (e) { return e.Id === it.Id; });
        eps.slice(k + 1, k + 16).forEach(function (e, n) {
          var u = e.ImageTags && e.ImageTags.Primary ? img(e.Id, 'Primary', e.ImageTags.Primary, 200) : null;
          var label = 'S' + e.ParentIndexNumber + ':E' + e.IndexNumber + ' - ' + e.Name;
          panel.appendChild(card(u, label, '', n === 0 ? function () { var nb = $('.btnNextTrack', page); if (nb) nb.click(); }
            : function () { location.hash = '#/details?id=' + e.Id; }, true));
        });
        if (!panel.children.length) panel.textContent = 'Das ist die letzte Folge.';
      }).catch(function () {});
    }
  }

  function syncVisibility(page) {
    var box = $('#bmcLogo'), bottom = $('.videoOsdBottom', page);
    if (!box || !bottom) return;
    var hidden = bottom.classList.contains('videoOsdBottom-hidden') || bottom.classList.contains('hide') ||
      getComputedStyle(bottom).opacity === '0';
    box.classList.toggle('bmc-hide', hidden);
  }

  function tick() {
    var page = osdPage();
    if (!page) { if (curId || $('#bmcLogo') || moved.length) cleanup(); return; }
    document.body.classList.add('bmc-osd');
    layout(page); icons(page); updateTimes(page); syncVisibility(page);
    var id = currentId();
    if (!id || !api()) return;
    if (id !== curId) {
      curId = id;
      var c = api();
      c.getItem(c.getCurrentUserId(), id).then(function (it) {
        if (curId !== id) return;
        curItem = it; buildLogo(it); buildMeta(it); tabs(page); syncVisibility(page);
      }).catch(function () {});
    }
  }

  function start() { if (!timer) timer = setInterval(tick, 300); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
