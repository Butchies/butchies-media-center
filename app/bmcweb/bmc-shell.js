/* Butchies Media Center – Oberfläche nach design/designsystem (preview.html):
   Seitenleiste (Startseite, Bibliotheken, Einstellungen), Kopfzeile, Startseite mit Hero, Kachelreihen
   und Bibliotheksseiten. Liegt über der Jellyfin-Oberfläche; Seiten, die hier noch nicht nachgebaut sind
   (Einstellungen, Dashboard, Serien-/Musik-Details, Player), zeigt weiterhin Jellyfin. */
(function () {
  'use strict';
  var VIEWS = null, ADMIN = false, USER = '', token = 0, retry = null;
  var PAGE = 60;

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function client() { var c = window.ApiClient; return c && c.getCurrentUserId && c.getCurrentUserId() ? c : null; }
  function q(name, h) { var m = (h || location.hash).match(new RegExp('[?&]' + name + '=([^&]*)')); return m ? decodeURIComponent(m[1]) : ''; }

  /* ---------- Welche Seite? ---------- */
  function route() {
    var h = location.hash || '';
    if (h === '' || h === '#' || h === '#/' || /^#\/home(\.html)?(\?.*)?$/.test(h)) return { page: 'home' };
    var m = h.match(/^#\/(movies|tv|music|list)(\.html)?\?/);
    if (m) { var id = q('topParentId') || q('parentId'); if (/^[0-9a-f]{32}$/i.test(id)) return { page: 'lib', id: id.toLowerCase(), kind: m[1] }; }
    return null;
  }
  function libHash(v) {
    var t = v.CollectionType;
    if (t === 'movies') return '#/movies?topParentId=' + v.Id + '&collectionType=movies';
    if (t === 'tvshows') return '#/tv?topParentId=' + v.Id + '&collectionType=tvshows';
    if (t === 'music') return '#/music?topParentId=' + v.Id + '&collectionType=music';
    return '#/list?parentId=' + v.Id + '&serverId=' + (v.ServerId || '');
  }
  function libIcon(t) { return { movies: '▣', tvshows: '▤', music: '♫', boxsets: '❏', playlists: '☰', homevideos: '▦', musicvideos: '♪' }[t] || '▦'; }
  function details(it) { return '#/details?id=' + it.Id + (it.ServerId ? '&serverId=' + it.ServerId : ''); }

  /* ---------- Bilder ---------- */
  function url(id, type, tag, w) { var c = client(); return c && tag ? c.getScaledImageUrl(id, { type: type, tag: tag, maxWidth: w, quality: 90 }) : ''; }
  function wideImg(it) {
    var t = it.ImageTags || {};
    if (it.Type === 'Episode' && t.Primary) return url(it.Id, 'Primary', t.Primary, 640);
    if (t.Thumb) return url(it.Id, 'Thumb', t.Thumb, 640);
    if ((it.BackdropImageTags || []).length) return url(it.Id, 'Backdrop', it.BackdropImageTags[0], 640);
    if (it.ParentThumbItemId && it.ParentThumbImageTag) return url(it.ParentThumbItemId, 'Thumb', it.ParentThumbImageTag, 640);
    if (it.ParentBackdropItemId && (it.ParentBackdropImageTags || []).length) return url(it.ParentBackdropItemId, 'Backdrop', it.ParentBackdropImageTags[0], 640);
    return t.Primary ? url(it.Id, 'Primary', t.Primary, 640) : '';
  }
  function posterImg(it) {
    var t = it.ImageTags || {};
    if (t.Primary) return url(it.Id, 'Primary', t.Primary, 400);
    if (it.SeriesId && it.SeriesPrimaryImageTag) return url(it.SeriesId, 'Primary', it.SeriesPrimaryImageTag, 400);
    if (it.AlbumId && it.AlbumPrimaryImageTag) return url(it.AlbumId, 'Primary', it.AlbumPrimaryImageTag, 400);
    return '';
  }
  function heroImg(it) {
    if ((it.BackdropImageTags || []).length) return url(it.Id, 'Backdrop', it.BackdropImageTags[0], 1920);
    if (it.ParentBackdropItemId && (it.ParentBackdropImageTags || []).length) return url(it.ParentBackdropItemId, 'Backdrop', it.ParentBackdropImageTags[0], 1920);
    return wideImg(it);
  }
  function emoji(it) {
    return { Movie: '🎬', Series: '🎞️', Season: '🎞️', Episode: '📺', MusicAlbum: '🎵', Audio: '🎵', MusicArtist: '🎤', BoxSet: '📚', Playlist: '📜', Video: '🎥' }[it.Type] || '🎬';
  }

  /* ---------- Kacheln (Markup wie preview.html: article.bmc-card > .bmc-image[data-shape] + h3 + p) ---------- */
  function sub(it) {
    if (it.Type === 'Episode') return (it.ParentIndexNumber != null ? 'S' + it.ParentIndexNumber + ':F' + (it.IndexNumber || '') + ' · ' : '') + (it.Name || '');
    if (it.Type === 'MusicAlbum') return it.AlbumArtist || (it.ProductionYear ? String(it.ProductionYear) : 'Album');
    if (it.Type === 'Series') return it.ProductionYear ? String(it.ProductionYear) + (it.Status === 'Continuing' ? ' – heute' : '') : 'Serie';
    return it.ProductionYear ? String(it.ProductionYear) : ({ Movie: 'Film', BoxSet: 'Sammlung', Playlist: 'Wiedergabeliste' }[it.Type] || '');
  }
  function card(it, shape, hash) {
    var wide = shape === 'wide';
    var img = wide ? wideImg(it) : posterImg(it);
    var ud = it.UserData || {};
    var title = it.Type === 'Episode' && it.SeriesName ? it.SeriesName : it.Name;
    var bar = ud.PlayedPercentage > 0 && ud.PlayedPercentage < 100 ? '<span class="bmc-bar"><i style="width:' + Math.round(ud.PlayedPercentage) + '%"></i></span>' : '';
    var badge = ud.UnplayedItemCount ? '<span class="bmc-badge">' + ud.UnplayedItemCount + '</span>' : (ud.Played && it.Type !== 'Series' ? '<span class="bmc-badge">✓</span>' : '');
    return '<article class="bmc-card' + (wide ? ' wide' : '') + '" data-go="' + esc(hash || details(it)) + '"><div class="bmc-image" data-shape="' + shape + '"' +
      (img ? ' style="background-image:url(&quot;' + esc(img) + '&quot;)"' : '') + '>' + (img ? '' : emoji(it)) + bar + badge + '</div><h3>' + esc(title) + '</h3><p>' + esc(sub(it)) + '</p></article>';
  }
  function shapeFor(it, lib) { return it.Type === 'MusicAlbum' || it.Type === 'Audio' || it.Type === 'MusicArtist' || (lib && lib.CollectionType === 'music') ? 'square' : 'poster'; }
  function row(title, items, shape, more) {
    if (!items || !items.length) return '';
    return '<h2 class="bmc-section">' + esc(title) + (more ? ' <a data-go="' + esc(more) + '">Alle anzeigen ›</a>' : '') + '</h2><div class="bmc-cards">' +
      items.map(function (it) { return card(it, typeof shape === 'function' ? shape(it) : shape); }).join('') + '</div>';
  }

  /* ---------- Rahmen: Seitenleiste + Kopfzeile ---------- */
  function shell(active, title, body) {
    var nav = '<a class="bmc-nav' + (active === 'home' ? ' active' : '') + '" data-go="#/home">⌂ &nbsp; Startseite</a>' +
      (VIEWS || []).map(function (v) {
        return '<a class="bmc-nav' + (active === v.Id ? ' active' : '') + '" data-go="' + esc(libHash(v)) + '">' + libIcon(v.CollectionType) + ' &nbsp; ' + esc(v.Name) + '</a>';
      }).join('') +
      '<div class="bmc-navsep"></div><a class="bmc-nav" data-go="#/search">⌕ &nbsp; Suche</a>' +
      '<a class="bmc-nav" data-go="#/mypreferencesmenu">⚙ &nbsp; Einstellungen</a>' +
      (ADMIN ? '<a class="bmc-nav" data-go="#/dashboard">⚒ &nbsp; Verwaltung</a>' : '');
    return '<div class="bmc-shell"><aside class="bmc-sidebar"><div class="bmc-brand" data-go="#/home">BUTCHIES MEDIA CENTER</div>' + nav + '</aside>' +
      '<main class="bmc-main"><header class="bmc-header"><div><button class="bmc-tool bmc-menubtn" data-act="menu">☰</button> <strong>' + esc(title) + '</strong></div>' +
      '<div class="bmc-tools"><button class="bmc-tool" data-go="#/search">⌕<span class="lbl"> Suche</span></button>' +
      '<button class="bmc-tool" data-go="#/mypreferencesmenu">' + (USER ? '👤<span class="lbl"> ' + esc(USER) + '</span>' : '⚙') + '</button></div></header>' + body + '</main></div>';
  }
  function root() {
    var el = document.getElementById('bmcShell');
    if (!el) {
      el = document.createElement('div'); el.id = 'bmcShell'; document.body.appendChild(el);
      el.addEventListener('click', onClick);
    }
    document.body.classList.add('bmcShellOn');
    return el;
  }
  function close() { var el = document.getElementById('bmcShell'); if (el) el.remove(); document.body.classList.remove('bmcShellOn'); }
  function paint(html, keep) {
    var el = root(), top = keep ? el.scrollTop : 0;
    el.innerHTML = html; el.scrollTop = top;
  }
  function onClick(e) {
    var a = e.target.closest('[data-act]');
    if (a) {
      var sb = document.querySelector('#bmcShell .bmc-sidebar');
      if (a.dataset.act === 'menu' && sb) {
        sb.classList.toggle('open');
        var s = document.querySelector('#bmcShell .bmc-scrim');
        if (sb.classList.contains('open') && !s) { s = document.createElement('div'); s.className = 'bmc-scrim'; s.dataset.act = 'scrim'; sb.parentNode.appendChild(s); }
        else if (s) s.remove();
      } else if (a.dataset.act === 'scrim') { sb && sb.classList.remove('open'); a.remove(); }
      else if (a.dataset.act === 'more') moreLib();
      else if (a.dataset.act === 'play') location.href = '/web/bmc/play/index.html?id=' + a.dataset.id;
      return;
    }
    var g = e.target.closest('[data-go]');
    if (g) { e.preventDefault(); location.hash = g.dataset.go; }
  }

  /* ---------- Grunddaten ---------- */
  function base(c) {
    if (VIEWS) return Promise.resolve();
    var uid = c.getCurrentUserId();
    return Promise.all([
      c.getUserViews({}, uid).then(function (r) { VIEWS = r.Items || []; }, function () { VIEWS = []; }),
      c.getCurrentUser().then(function (u) { ADMIN = !!(u.Policy && u.Policy.IsAdministrator); USER = u.Name || ''; }, function () {})
    ]);
  }

  /* ---------- Startseite ---------- */
  var FIELDS = 'PrimaryImageAspectRatio,Overview,ProductionYear,Status';
  function home(c, t) {
    var uid = c.getCurrentUserId(), D = {};
    paint(shell('home', 'Startseite', '<h1 class="bmc-heading">Deine Mediathek</h1><p class="bmc-subtitle">Wird geladen …</p>'));
    var jobs = [
      c.getResumableItems(uid, { Limit: 16, MediaTypes: 'Video', Fields: FIELDS, EnableImageTypes: 'Primary,Backdrop,Thumb' }).then(function (r) { D.resume = r.Items || []; }, function () { D.resume = []; }),
      c.getNextUpEpisodes({ userId: uid, Limit: 16, Fields: FIELDS, EnableImageTypes: 'Primary,Backdrop,Thumb' }).then(function (r) { D.next = r.Items || []; }, function () { D.next = []; })
    ];
    D.latest = {};
    (VIEWS || []).forEach(function (v) {
      if (v.CollectionType === 'playlists' || v.CollectionType === 'boxsets') return;
      jobs.push(c.getLatestItems({ userId: uid, ParentId: v.Id, Limit: 16, Fields: FIELDS, EnableImageTypes: 'Primary,Backdrop,Thumb' })
        .then(function (r) { D.latest[v.Id] = r || []; }, function () { D.latest[v.Id] = []; }));
    });
    Promise.all(jobs).then(function () {
      if (t !== token) return;
      var heroIt = D.resume[0] || D.next[0];
      if (!heroIt) (VIEWS || []).some(function (v) { var l = D.latest[v.Id]; if (l && l.length) { heroIt = l[0]; return true; } return false; });
      var hero = '';
      if (heroIt) {
        var img = heroImg(heroIt), resum = D.resume[0] === heroIt;
        var name = heroIt.Type === 'Episode' && heroIt.SeriesName ? heroIt.SeriesName : heroIt.Name;
        hero = '<section class="bmc-hero' + (img ? ' img' : '') + '"' + (img ? ' style="background-image:url(&quot;' + esc(img) + '&quot;)"' : '') + '>' +
          '<h2>' + esc(name) + '</h2><p>' + esc(heroIt.Type === 'Episode' ? sub(heroIt) + (heroIt.Overview ? ' – ' + heroIt.Overview : '') : (heroIt.Overview || sub(heroIt))) + '</p>' +
          '<button class="bmc-action" data-act="play" data-id="' + esc(heroIt.Id) + '">▶ ' + (resum ? 'Fortsetzen' : 'Abspielen') + '</button>' +
          '<button class="bmc-action" data-go="' + esc(details(heroIt)) + '">Details</button></section>';
      }
      var libs = (VIEWS || []).length ? '<h2 class="bmc-section">Meine Medien</h2><div class="bmc-cards">' + VIEWS.map(function (v) {
        var img = v.ImageTags && v.ImageTags.Primary ? url(v.Id, 'Primary', v.ImageTags.Primary, 640) : '';
        return '<article class="bmc-card wide" data-go="' + esc(libHash(v)) + '"><div class="bmc-image" data-shape="wide"' + (img ? ' style="background-image:url(&quot;' + esc(img) + '&quot;)"' : '') + '>' + (img ? '' : libIcon(v.CollectionType)) + '</div><h3>' + esc(v.Name) + '</h3><p>' +
          ({ movies: 'Filme', tvshows: 'Serien', music: 'Musik', boxsets: 'Sammlungen', playlists: 'Wiedergabelisten' }[v.CollectionType] || 'Medien') + '</p></article>';
      }).join('') + '</div>' : '';
      var body = '<h1 class="bmc-heading">Deine Mediathek</h1><p class="bmc-subtitle">' + (USER ? 'Willkommen zurück, ' + esc(USER) + '.' : 'Willkommen zurück.') + '</p>' + hero + libs +
        row('Weiterschauen', D.resume, 'wide') + row('Nächste Folgen', D.next, 'wide') +
        (VIEWS || []).map(function (v) { return row('Neu in ' + v.Name, D.latest[v.Id], function (it) { return shapeFor(it, v); }, libHash(v)); }).join('');
      if (!heroIt && !libs) body += '<p class="bmc-empty">Noch keine Medien. Lege unter Verwaltung → Bibliotheken deine Ordner an.</p>';
      paint(shell('home', 'Startseite', body));
    });
  }

  /* ---------- Bibliothek ---------- */
  var L = null;
  var SORTS = [['SortName', 'Ascending', 'Name A–Z'], ['DateCreated', 'Descending', 'Neu hinzugefügt'], ['ProductionYear,SortName', 'Descending', 'Erscheinungsjahr'],
    ['CommunityRating,SortName', 'Descending', 'Bewertung'], ['DatePlayed', 'Descending', 'Zuletzt gesehen']];
  function lib(c, r, t) {
    var v = (VIEWS || []).filter(function (x) { return x.Id === r.id; })[0] || { Id: r.id, Name: 'Bibliothek', CollectionType: '' };
    var types = { movies: 'Movie', tvshows: 'Series', music: 'MusicAlbum', boxsets: 'BoxSet', playlists: 'Playlist' }[v.CollectionType] || '';
    var sort = 0;
    try { sort = +localStorage.getItem('bmc-sort-' + r.id) || 0; } catch (e) {}
    if (!L || L.id !== r.id || L.sort !== sort) L = { id: r.id, v: v, types: types, sort: sort, items: [], total: null, t: t };
    L.t = t;
    paintLib();
    if (L.total === null) moreLib();
  }
  function paintLib() {
    var v = L.v;
    var filter = '<div class="bmc-filter"><label>Sortieren <select class="bmc-select" id="bmcSort">' +
      SORTS.map(function (s, i) { return '<option value="' + i + '"' + (i === L.sort ? ' selected' : '') + '>' + s[2] + '</option>'; }).join('') + '</select></label>' +
      (L.total !== null ? '<span class="bmc-subtitle" style="margin:0">' + L.total + ' Titel</span>' : '') + '</div>';
    var grid = L.items.length ? '<div class="bmc-grid">' + L.items.map(function (it) { return card(it, shapeFor(it, v)); }).join('') + '</div>'
      : (L.total === 0 ? '<p class="bmc-empty">Hier ist noch nichts.</p>' : '<p class="bmc-empty">Wird geladen …</p>');
    var more = L.total !== null && L.items.length < L.total ? '<button class="bmc-action bmc-more" data-act="more">Mehr laden</button>' : '';
    paint(shell(v.Id, v.Name, '<h1 class="bmc-heading">' + esc(v.Name) + '</h1>' + filter + grid + more), true);
    var s = document.getElementById('bmcSort');
    if (s) s.onchange = function () { try { localStorage.setItem('bmc-sort-' + L.id, s.value); } catch (e) {} L = null; check(); };
  }
  function moreLib() {
    var c = client(); if (!c || !L || L.busy) return;
    var st = L, s = SORTS[st.sort]; st.busy = true;
    var o = { ParentId: st.id, SortBy: s[0], SortOrder: s[1], StartIndex: st.items.length, Limit: PAGE, Fields: FIELDS, EnableImageTypes: 'Primary,Backdrop,Thumb', EnableTotalRecordCount: true };
    if (st.types) { o.IncludeItemTypes = st.types; o.Recursive = true; }
    c.getItems(c.getCurrentUserId(), o).then(function (r) {
      st.busy = false; st.items = st.items.concat(r.Items || []); st.total = r.TotalRecordCount != null ? r.TotalRecordCount : st.items.length;
      if (L === st && st.t === token) paintLib();
    }, function () { st.busy = false; st.total = st.items.length; if (L === st) paintLib(); });
  }

  /* ---------- Steuerung ---------- */
  function check() {
    clearTimeout(retry);
    var r = route();
    if (!r) { close(); return; }
    var c = client();
    if (!c) { retry = setTimeout(check, 200); return; }
    var t = ++token;
    base(c).then(function () {
      if (t !== token) return;
      if (r.page === 'home') home(c, t); else lib(c, r, t);
    });
  }
  window.addEventListener('hashchange', check);
  // Benutzerwechsel → Bibliotheken neu laden
  var lastUid = null;
  setInterval(function () { var c = client(), u = c ? c.getCurrentUserId() : null; if (u !== lastUid) { lastUid = u; VIEWS = null; L = null; if (u) check(); } }, 1000);
  check();
})();
