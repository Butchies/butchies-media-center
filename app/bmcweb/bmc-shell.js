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
    if (/^#\/search(\.html)?(\?.*)?$/.test(h)) return { page: 'search' };
    var pm = h.match(/^#\/(mypreferencesmenu|mypreferencesplayback|mypreferencessubtitles|mypreferencesdisplay|userprofile)(\.html)?(\?.*)?$/);
    if (pm) return { page: 'settings', sub: pm[1] };
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
      '<div class="bmc-navsep"></div><a class="bmc-nav' + (active === 'search' ? ' active' : '') + '" data-go="#/search">⌕ &nbsp; Suche</a>' +
      '<a class="bmc-nav' + (active === 'settings' ? ' active' : '') + '" data-go="#/mypreferencesmenu">⚙ &nbsp; Einstellungen</a>' +
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
      else if (a.dataset.act === 'savepw') savePw();
      else if (a.dataset.act === 'logout') logout();
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


  /* ---------- Suche ---------- */
  var SQ = { term: '', res: null, t: 0 };
  var GROUPS = [['Movie', 'Filme', 'poster'], ['Series', 'Serien', 'poster'], ['Episode', 'Folgen', 'wide'], ['MusicAlbum', 'Alben', 'square'],
    ['Audio', 'Titel', 'square'], ['MusicArtist', 'Künstler', 'square'], ['BoxSet', 'Sammlungen', 'poster'], ['Person', 'Personen', 'poster']];
  function search(c, t) {
    var term = q('query') || SQ.term;
    SQ.term = term;
    paint(shell('search', 'Suche', '<h1 class="bmc-heading">Suche</h1><div class="bmc-filter"><input class="bmc-select bmc-search" id="bmcQ" type="search" placeholder="Film, Serie, Folge, Musik oder Person …" value="' + esc(term) + '" autocomplete="off"></div><div id="bmcRes">' + results() + '</div>'), true);
    var inp = document.getElementById('bmcQ');
    if (inp) {
      if (!window.matchMedia || !matchMedia('(pointer:coarse)').matches || !term) inp.focus();
      inp.setSelectionRange(inp.value.length, inp.value.length);
      inp.oninput = function () { clearTimeout(SQ.timer); SQ.timer = setTimeout(function () { run(inp.value.trim()); }, 300); };
    }
    if (term && !SQ.res) run(term);
  }
  function run(term) {
    var c = client(); if (!c) return;
    SQ.term = term; var my = ++SQ.t;
    if (term.length < 2) { SQ.res = null; return fill(); }
    var uid = c.getCurrentUserId(), res = {};
    var jobs = GROUPS.filter(function (g) { return g[0] !== 'Person' && g[0] !== 'MusicArtist'; }).map(function (g) {
      return c.getItems(uid, { searchTerm: term, IncludeItemTypes: g[0], Recursive: true, Limit: 24, Fields: FIELDS, EnableImageTypes: 'Primary,Backdrop,Thumb' })
        .then(function (r) { res[g[0]] = r.Items || []; }, function () { res[g[0]] = []; });
    });
    jobs.push(c.getJSON(c.getUrl('Persons', { searchTerm: term, Limit: 24 })).then(function (r) { res.Person = r.Items || []; }, function () { res.Person = []; }));
    jobs.push(c.getJSON(c.getUrl('Artists', { searchTerm: term, Limit: 24, userId: uid })).then(function (r) { res.MusicArtist = r.Items || []; }, function () { res.MusicArtist = []; }));
    Promise.all(jobs).then(function () { if (my === SQ.t) { SQ.res = res; fill(); } });
  }
  function fill() { var el = document.getElementById('bmcRes'); if (el) el.innerHTML = results(); }
  function results() {
    if (!SQ.term || SQ.term.length < 2) return '<p class="bmc-subtitle">Tippe mindestens 2 Buchstaben.</p>';
    if (!SQ.res) return '<p class="bmc-subtitle">Suche läuft …</p>';
    var html = GROUPS.map(function (g) { return row(g[1], SQ.res[g[0]], g[2]); }).join('');
    return html || '<p class="bmc-subtitle">Nichts gefunden für „' + esc(SQ.term) + '“.</p>';
  }

  /* ---------- Einstellungen ---------- */
  var LANGS = [['', 'Egal / Standard der Datei'], ['ger', 'Deutsch'], ['eng', 'Englisch'], ['fre', 'Französisch'], ['spa', 'Spanisch'], ['ita', 'Italienisch'], ['jpn', 'Japanisch'], ['tur', 'Türkisch'], ['rus', 'Russisch'], ['pol', 'Polnisch']];
  var SUBMODES = [['Default', 'Standard (wie in der Datei markiert)'], ['Always', 'Immer anzeigen'], ['OnlyForced', 'Nur erzwungene'], ['Smart', 'Intelligent (bei fremder Tonsprache)'], ['None', 'Keine']];
  var SIZES = [['extrasmall', 'Extra klein'], ['smaller', 'Kleiner'], ['small', 'Klein'], ['', 'Standard'], ['large', 'Groß'], ['larger', 'Größer'], ['extralarge', 'Extra groß']];
  var SUBSIZE = [['.8', 'Klein'], ['1', 'Normal'], ['1.25', 'Groß'], ['1.5', 'Sehr groß']];
  function opt(list, val) { return list.map(function (o) { return '<option value="' + esc(o[0]) + '"' + (String(val) === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>'; }).join(''); }
  function field(label, html, hint) { return '<div class="bmc-field"><label>' + esc(label) + '</label>' + html + (hint ? '<p class="bmc-hint">' + esc(hint) + '</p>' : '') + '</div>'; }
  function ls(k, d) { try { var v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  function settings(c, r, t) {
    var uid = c.getCurrentUserId(), sub = r.sub;
    var TITLES = { mypreferencesmenu: 'Einstellungen', mypreferencesdisplay: 'Anzeige', mypreferencesplayback: 'Wiedergabe', mypreferencessubtitles: 'Untertitel', userprofile: 'Profil' };
    var back = sub === 'mypreferencesmenu' ? '' : '<p><a class="bmc-back" data-go="#/mypreferencesmenu">‹ Einstellungen</a></p>';
    if (sub === 'mypreferencesmenu') {
      var tiles = [['#/userprofile?userId=' + uid, '👤', 'Profil', 'Name und Passwort'], ['#/mypreferencesdisplay', '🖥', 'Anzeige', 'Bildgröße der Kacheln'],
        ['#/mypreferencesplayback', '▶', 'Wiedergabe', 'Tonsprache, nächste Folge'], ['#/mypreferencessubtitles', '💬', 'Untertitel', 'Wann und welche Untertitel, Größe']];
      if (ADMIN) tiles.push(['#/dashboard', '⚒', 'Verwaltung', 'Benutzer, Bibliotheken, Plugins']);
      paint(shell('settings', 'Einstellungen', '<h1 class="bmc-heading">Einstellungen</h1><p class="bmc-subtitle">Angemeldet als ' + esc(USER) + '.</p><div class="bmc-tiles">' +
        tiles.map(function (x) { return '<button class="bmc-tile" data-go="' + esc(x[0]) + '"><span class="ico">' + x[1] + '</span><strong>' + esc(x[2]) + '</strong><span>' + esc(x[3]) + '</span></button>'; }).join('') +
        '<button class="bmc-tile" data-act="logout"><span class="ico">⎋</span><strong>Abmelden</strong><span>Von diesem Gerät abmelden</span></button></div>'));
      return;
    }
    if (sub === 'mypreferencesdisplay') {
      var key = uid + '-cardSize', cur = ls(key, ls('cardSize', ''));
      if (cur === 'normal' || cur === 'default') cur = '';
      paint(shell('settings', TITLES[sub], back + '<h1 class="bmc-heading">Anzeige</h1><section class="bmc-dialog bmc-form">' +
        field('Bildgröße', '<select class="bmc-select" id="bmcCs">' + opt(SIZES, cur) + '</select>', 'Wie groß die Kacheln auf Startseite und in den Bibliotheken sind. Gilt nur für dieses Gerät und wird sofort gespeichert.') + '</section>'));
      document.getElementById('bmcCs').onchange = function (e) {
        var v = e.target.value; lsSet(key, v === '' ? 'normal' : v);
        var adj = { extrasmall: 3, smaller: 2, small: 1, '': 0, large: -1, larger: -2, extralarge: -3 }[v] || 0;
        document.documentElement.style.setProperty('--bmc-cs', String(adj));
        document.documentElement.classList.toggle('bmc-cs', adj !== 0);
        toast('Gespeichert.');
      };
      return;
    }
    if (sub === 'userprofile') {
      paint(shell('settings', TITLES[sub], back + '<h1 class="bmc-heading">Profil</h1><section class="bmc-dialog bmc-form">' +
        field('Benutzername', '<input class="bmc-select" value="' + esc(USER) + '" disabled>') +
        '<h2 class="bmc-section">Passwort ändern</h2>' +
        field('Aktuelles Passwort', '<input class="bmc-select" type="password" id="pwOld" autocomplete="current-password">') +
        field('Neues Passwort', '<input class="bmc-select" type="password" id="pwNew" autocomplete="new-password">', 'Mindestens 6 Zeichen.') +
        field('Neues Passwort wiederholen', '<input class="bmc-select" type="password" id="pwNew2" autocomplete="new-password">') +
        '<button class="bmc-action" data-act="savepw">Passwort speichern</button><p class="bmc-hint" id="pwMsg"></p></section>'));
      return;
    }
    // Wiedergabe / Untertitel: Benutzer-Konfiguration vom Server
    paint(shell('settings', TITLES[sub], back + '<h1 class="bmc-heading">' + TITLES[sub] + '</h1><p class="bmc-subtitle">Wird geladen …</p>'));
    c.getUser(uid).then(function (u) {
      if (t !== token) return;
      var cfg = u.Configuration || {};
      var body = back + '<h1 class="bmc-heading">' + TITLES[sub] + '</h1><section class="bmc-dialog bmc-form">';
      if (sub === 'mypreferencesplayback') {
        body += field('Bevorzugte Tonsprache', '<select class="bmc-select" data-cfg="AudioLanguagePreference">' + opt(LANGS, cfg.AudioLanguagePreference || '') + '</select>', 'Gibt es diese Sprache im Film, wird sie automatisch gewählt.') +
          field('Standard-Tonspur', '<label class="bmc-check"><input type="checkbox" data-cfg="PlayDefaultAudioTrack"' + (cfg.PlayDefaultAudioTrack !== false ? ' checked' : '') + '> Die in der Datei als Standard markierte Tonspur abspielen, auch wenn sie eine andere Sprache hat</label>') +
          field('Nächste Folge', '<label class="bmc-check"><input type="checkbox" data-cfg="EnableNextEpisodeAutoPlay"' + (cfg.EnableNextEpisodeAutoPlay !== false ? ' checked' : '') + '> Bei Serien die nächste Folge automatisch starten</label>') +
          field('Auswahl merken', '<label class="bmc-check"><input type="checkbox" data-cfg="RememberAudioSelections"' + (cfg.RememberAudioSelections !== false ? ' checked' : '') + '> Gewählte Tonspur für die nächste Folge merken</label>');
      } else {
        body += field('Untertitel anzeigen', '<select class="bmc-select" data-cfg="SubtitleMode">' + opt(SUBMODES, cfg.SubtitleMode || 'Default') + '</select>') +
          field('Bevorzugte Untertitelsprache', '<select class="bmc-select" data-cfg="SubtitleLanguagePreference">' + opt(LANGS, cfg.SubtitleLanguagePreference || '') + '</select>') +
          field('Schriftgröße im Player', '<select class="bmc-select" id="bmcSubSize">' + opt(SUBSIZE, ls('bmc-play-subsize', '1')) + '</select>', 'Gilt nur für dieses Gerät.');
      }
      body += '<p class="bmc-hint" id="cfgMsg">Änderungen werden sofort gespeichert.</p></section>';
      paint(shell('settings', TITLES[sub], body));
      var ss = document.getElementById('bmcSubSize');
      if (ss) ss.onchange = function () { lsSet('bmc-play-subsize', ss.value); toast('Gespeichert.'); };
      Array.prototype.forEach.call(document.querySelectorAll('#bmcShell [data-cfg]'), function (el) {
        el.onchange = function () {
          var k = el.dataset.cfg;
          cfg[k] = el.type === 'checkbox' ? el.checked : el.value;
          if (k === 'EnableNextEpisodeAutoPlay') lsSet('bmc-play-autonext', el.checked ? '1' : '0');
          c.updateUserConfiguration(uid, cfg).then(function () { toast('Gespeichert.'); }, function () { toast('Speichern fehlgeschlagen.'); });
        };
      });
    }, function () { paint(shell('settings', TITLES[sub], back + '<p class="bmc-empty">Einstellungen konnten nicht geladen werden.</p>')); });
  }
  function savePw() {
    var c = client(), a = document.getElementById('pwOld').value, b = document.getElementById('pwNew').value, b2 = document.getElementById('pwNew2').value, msg = document.getElementById('pwMsg');
    if (b.length < 6) { msg.textContent = 'Das neue Passwort braucht mindestens 6 Zeichen.'; return; }
    if (b !== b2) { msg.textContent = 'Die beiden neuen Passwörter sind nicht gleich.'; return; }
    msg.textContent = 'Wird gespeichert …';
    c.ajax({ type: 'POST', url: c.getUrl('Users/' + c.getCurrentUserId() + '/Password'), data: JSON.stringify({ CurrentPw: a, NewPw: b }), contentType: 'application/json' })
      .then(function () { msg.textContent = 'Passwort geändert. Bitte melde dich mit dem neuen Passwort wieder an …'; setTimeout(logout, 2000); },
        function () { msg.textContent = 'Das hat nicht geklappt – stimmt das aktuelle Passwort?'; });
  }
  function logout() {
    var b = document.querySelector('.btnLogout');
    if (b) { close(); b.click(); return; }
    var c = client();
    (c && c.logout ? c.logout() : Promise.resolve()).then(function () {}, function () {}).then(function () {
      try { var cr = JSON.parse(localStorage.getItem('jellyfin_credentials') || '{}'); (cr.Servers || []).forEach(function (s) { delete s.AccessToken; delete s.UserId; }); localStorage.setItem('jellyfin_credentials', JSON.stringify(cr)); } catch (e) {}
      location.href = '/web/#/login'; location.reload();
    });
  }
  function toast(t) {
    var el = document.getElementById('bmcToast');
    if (!el) { el = document.createElement('div'); el.id = 'bmcToast'; el.className = 'bmc-toast'; root().appendChild(el); }
    el.textContent = t; el.classList.add('on'); clearTimeout(el._t); el._t = setTimeout(function () { el.classList.remove('on'); }, 1800);
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
      if (r.page === 'home') home(c, t);
      else if (r.page === 'search') search(c, t);
      else if (r.page === 'settings') settings(c, r, t);
      else lib(c, r, t);
    });
  }
  window.addEventListener('hashchange', check);
  // Benutzerwechsel → Bibliotheken neu laden
  var lastUid = null;
  setInterval(function () { var c = client(), u = c ? c.getCurrentUserId() : null; if (u !== lastUid) { lastUid = u; VIEWS = null; L = null; if (u) check(); } }, 1000);
  check();
})();
