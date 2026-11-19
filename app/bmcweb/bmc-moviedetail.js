/* Butchies Media Center – Detailseiten (Film, Folge, Serie, Staffel, Album, Sammlung, Wiedergabeliste).
   Aufbau und Aussehen 1:1 nach design/film-detailseite (index.html, movie-detail.css, movie-detail.js),
   gefüllt mit den echten Daten. Serien, Alben und Sammlungen benutzen denselben Aufbau, nur mit passenden
   Reitern (Folgen, Titel, Inhalt). Die Seite liegt über der Jellyfin-Detailseite; Favorit, Gesehen, Spurauswahl
   und das Menü lösen die Funktionen der Jellyfin-Seite darunter aus. Abspielen öffnet den Butchies-Player. */
(function () {
  'use strict';
  var VIDEO = { Movie: 1, Episode: 1, Video: 1, MusicVideo: 1, Trailer: 1 };
  var KIND = { Series: 'series', Season: 'series', MusicAlbum: 'album', BoxSet: 'folder', Playlist: 'folder' };
  var EYEBROW = { Movie: 'FILMDETAILS', Episode: 'FOLGE', Video: 'VIDEO', MusicVideo: 'MUSIKVIDEO', Trailer: 'TRAILER', Series: 'SERIENDETAILS',
    Season: 'STAFFEL', MusicAlbum: 'ALBUM', BoxSet: 'SAMMLUNG', Playlist: 'WIEDERGABELISTE' };
  var S = null;
  var loading = null, timer = null;

  function $(s, r) { return (r || document).querySelector(s); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function client() { var c = window.ApiClient; return c && c.getCurrentUserId && c.getCurrentUserId() ? c : null; }
  function hashId() {
    if (!/^#\/details\?/.test(location.hash)) return null;
    var m = location.hash.match(/[?&]id=([0-9a-f]{32})/i); return m ? m[1].toLowerCase() : null;
  }
  function jfPage() {
    var ps = document.querySelectorAll('.itemDetailPage');
    for (var i = 0; i < ps.length; i++) if (!ps[i].classList.contains('hide')) return ps[i];
    return null;
  }
  function jfBtn(cls) { var p = jfPage(); return p ? $('.mainDetailButtons .' + cls, p) : null; }
  function playUrl(id, t) { return '/web/bmc/play/index.html?id=' + id + (t != null ? '&t=' + Math.floor(t) : ''); }

  /* ---------- Daten ---------- */
  function img(id, type, tag, h) {
    var c = client(); if (!c || !tag) return '';
    return c.getScaledImageUrl(id, { type: type, tag: tag, maxHeight: h, quality: 90 });
  }
  function ticksToSec(t) { return Math.floor((t || 0) / 1e7); }
  function mins(t) { return t ? Math.max(1, Math.round(t / 6e8)) : 0; }
  function clock(sec) { sec = Math.floor(sec || 0); var h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = sec % 60; return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0'); }
  function codecName(c) {
    c = (c || '').toLowerCase();
    return { hevc: 'H.265 / HEVC', h265: 'H.265 / HEVC', h264: 'H.264 / AVC', avc: 'H.264 / AVC', av1: 'AV1', vp9: 'VP9', vp8: 'VP8',
      mpeg2video: 'MPEG-2', mpeg4: 'MPEG-4', vc1: 'VC-1', aac: 'AAC', ac3: 'Dolby Digital (AC3)', eac3: 'Dolby Digital Plus (E-AC3)',
      dts: 'DTS', truehd: 'Dolby TrueHD', mp3: 'MP3', flac: 'FLAC', opus: 'Opus', vorbis: 'Vorbis', subrip: 'SRT', srt: 'SRT',
      ass: 'ASS', ssa: 'SSA', webvtt: 'VTT', vtt: 'VTT', mov_text: 'MP4-Text', pgssub: 'PGS', dvdsub: 'DVD', dvd_subtitle: 'DVD' }[c] || c.toUpperCase();
  }
  function uniq(a) { return a.filter(function (x, i) { return x && a.indexOf(x) === i; }); }

  function technical(it) {
    var ms = (it.MediaSources || [])[0] || {};
    var streams = ms.MediaStreams || it.MediaStreams || [];
    var v = streams.filter(function (s) { return s.Type === 'Video'; })[0];
    var au = streams.filter(function (s) { return s.Type === 'Audio'; });
    var su = streams.filter(function (s) { return s.Type === 'Subtitle'; });
    var tech = {};
    if (ms.Container) tech['Container'] = ms.Container.split(',')[0].toUpperCase();
    if (v && v.Width) tech['Auflösung'] = v.Width + ' × ' + v.Height;
    if (v && v.Codec) tech['Videocodec'] = codecName(v.Codec) + (v.BitDepth > 8 ? ' · ' + v.BitDepth + ' Bit' : '');
    if (v && v.VideoRangeType && v.VideoRangeType !== 'SDR' && v.VideoRangeType !== 'Unknown') tech['Dynamikbereich'] = v.VideoRangeType;
    var fr = v && (v.RealFrameRate || v.AverageFrameRate);
    if (fr) tech['Bildrate'] = (Math.round(fr * 1000) / 1000).toString().replace('.', ',') + ' fps';
    if (au.length) tech['Audiocodec'] = uniq(au.map(function (a) { return codecName(a.Codec) + (a.Channels ? ' ' + ({ 1: 'Mono', 2: 'Stereo', 6: '5.1', 8: '7.1' }[a.Channels] || a.Channels + ' Kanäle') : ''); })).join(', ');
    if (su.length) tech['Untertitel'] = uniq(su.map(function (s) { return codecName(s.Codec); })).join(' / ');
    if (ms.Bitrate) tech['Bitrate'] = (Math.round(ms.Bitrate / 100000) / 10).toString().replace('.', ',') + ' Mbit/s';
    if (ms.Size) tech['Dateigröße'] = (Math.round(ms.Size / 1e8) / 10).toString().replace('.', ',') + ' GB';
    return tech;
  }

  function info(it) {
    var ud = it.UserData || {}, t = it.ImageTags || {};
    var poster = '';
    if (it.Type === 'Episode' && it.SeriesId && it.SeriesPrimaryImageTag) poster = img(it.SeriesId, 'Primary', it.SeriesPrimaryImageTag, 750);
    else if (t.Primary) poster = img(it.Id, 'Primary', t.Primary, 750);
    else if (it.SeriesId && it.SeriesPrimaryImageTag) poster = img(it.SeriesId, 'Primary', it.SeriesPrimaryImageTag, 750);
    var backdrop = (it.BackdropImageTags || []).length ? img(it.Id, 'Backdrop', it.BackdropImageTags[0], 1080)
      : (it.ParentBackdropItemId && (it.ParentBackdropImageTags || []).length ? img(it.ParentBackdropItemId, 'Backdrop', it.ParentBackdropImageTags[0], 1080) : '');
    var year = it.ProductionYear || '';
    if (it.Type === 'Series' && year) year = year + (it.Status === 'Continuing' ? ' – heute' : (it.EndDate ? ' – ' + new Date(it.EndDate).getFullYear() : ''));
    return {
      id: it.Id, serverId: it.ServerId, type: it.Type, title: it.Name || '', year: year,
      runtimeMinutes: VIDEO[it.Type] ? mins(it.RunTimeTicks) : 0,
      ageRating: it.OfficialRating || '', genres: it.Genres || [],
      rating: it.CommunityRating ? (Math.round(it.CommunityRating * 10) / 10).toFixed(1).replace('.', ',') : '',
      tagline: (it.Taglines || [])[0] || '', overview: it.Overview || '',
      directors: (it.People || []).filter(function (p) { return p.Type === 'Director'; }).map(function (p) { return p.Name; }),
      progress: ud.PlayedPercentage || 0, isFavorite: !!ud.IsFavorite, isPlayed: !!ud.Played,
      canDownload: !!it.CanDownload, square: it.Type === 'MusicAlbum' || it.Type === 'Playlist',
      poster: poster, backdrop: backdrop,
      people: (it.People || []).filter(function (p) { return p.Type === 'Actor' || p.Type === 'GuestStar'; }).map(function (p) {
        return { id: p.Id, name: p.Name, role: p.Role || 'Darsteller', image: img(p.Id, 'Primary', p.PrimaryImageTag, 330), icon: '👤' };
      }),
      chapters: (it.Chapters || []).map(function (c) { return { time: ticksToSec(c.StartPositionTicks), name: c.Name || '' }; }),
      technical: VIDEO[it.Type] ? technical(it) : {}
    };
  }

  function load(id) {
    var c = client(); if (!c) return;
    var uid = c.getCurrentUserId();
    var token = loading = {};
    c.getItem(uid, id).then(function (it) {
      if (token !== loading) return;
      var kind = VIDEO[it.Type] ? 'video' : KIND[it.Type];
      if (!kind) { S = { id: id, skip: true }; close(); return; }
      var st = { id: id, item: it, kind: kind, m: info(it), similar: [], extras: [], trailers: [], admin: false, views: [],
                 seasons: [], season: null, episodes: null, next: null, children: null,
                 tab: kind === 'series' ? 'Folgen' : kind === 'album' ? 'Titel' : kind === 'folder' ? 'Inhalt' : 'Übersicht', menu: false, expanded: false };
      S = st; render();
      var jobs = [
        c.getCurrentUser().then(function (u) { st.admin = !!(u.Policy && u.Policy.IsAdministrator); }, function () {}),
        c.getUserViews({}, uid).then(function (r) { st.views = r.Items || []; }, function () {})
      ];
      if (kind === 'video' || it.Type === 'Series') {
        jobs.push(c.getSimilarItems(id, { userId: uid, limit: 12, fields: 'PrimaryImageAspectRatio' }).then(function (r) { st.similar = r.Items || []; }, function () {}));
      }
      if (kind === 'video') {
        jobs.push(c.getJSON(c.getUrl('Users/' + uid + '/Items/' + id + '/SpecialFeatures')).then(function (r) { st.extras = r || []; }, function () {}));
        jobs.push(c.getJSON(c.getUrl('Users/' + uid + '/Items/' + id + '/LocalTrailers')).then(function (r) { st.trailers = r || []; }, function () {}));
      }
      if (kind === 'series') {
        var sid = it.Type === 'Season' ? it.SeriesId : id;
        st.seriesId = sid;
        jobs.push(c.getSeasons(sid, { userId: uid, Fields: 'PrimaryImageAspectRatio' }).then(function (r) {
          st.seasons = r.Items || [];
          if (it.Type === 'Season') st.season = id;
        }, function () {}));
        jobs.push(c.getNextUpEpisodes({ userId: uid, SeriesId: sid, Limit: 1, Fields: 'PrimaryImageAspectRatio' }).then(function (r) { st.next = (r.Items || [])[0] || null; }, function () {}));
      }
      if (kind === 'album' || kind === 'folder') {
        var o = { ParentId: id, Fields: 'PrimaryImageAspectRatio,ProductionYear,MediaSources', EnableImageTypes: 'Primary,Backdrop,Thumb' };
        if (kind === 'album') o.SortBy = 'ParentIndexNumber,IndexNumber,SortName';
        jobs.push(c.getItems(uid, o).then(function (r) { st.children = r.Items || []; }, function () { st.children = []; }));
      }
      Promise.all(jobs).then(function () {
        if (S !== st) return;
        if (kind === 'series') {
          if (!st.season) {   // Staffel mit der nächsten Folge, sonst die erste
            var want = st.next && st.next.SeasonId;
            st.season = (st.seasons.filter(function (x) { return x.Id === want; })[0] || st.seasons[0] || {}).Id || null;
          }
          loadEpisodes(st);
        }
        render();
      });
    }, function () { if (token === loading) { S = null; close(); } });
  }
  function loadEpisodes(st) {
    var c = client(); if (!c || !st.seriesId) return;
    st.episodes = null;
    c.getEpisodes(st.seriesId, { userId: c.getCurrentUserId(), seasonId: st.season || undefined, Fields: 'Overview,PrimaryImageAspectRatio', EnableImageTypes: 'Primary,Thumb' })
      .then(function (r) { st.episodes = r.Items || []; if (S === st) render(); }, function () { st.episodes = []; if (S === st) render(); });
  }

  /* ---------- Darstellung (Markup wie movie-detail.js) ---------- */
  function thumbStyle(url) { return url ? ' style="background-image:url(&quot;' + esc(url) + '&quot;)"' : ''; }
  function cards(items, kind) {
    return '<div class="cards">' + items.map(function (x, i) {
      return '<button class="card' + (x.wide ? ' wide' : '') + (x.square ? ' square' : '') + '" data-card="' + kind + '" data-i="' + i + '"><div class="thumb"' + thumbStyle(x.image) + '>' +
        (x.image ? '' : esc(x.icon || '🎬')) + '</div><h3>' + esc(x.name) + '</h3><p>' + esc(x.role || x.type || 'Film') + '</p></button>';
    }).join('') + '</div>';
  }
  function itemCards(list) {
    return list.map(function (x) {
      var sq = x.Type === 'MusicAlbum' || x.Type === 'Audio' || x.Type === 'Playlist';
      var t = x.ImageTags || {};
      var image = t.Primary ? img(x.Id, 'Primary', t.Primary, 330) : (x.AlbumId && x.AlbumPrimaryImageTag ? img(x.AlbumId, 'Primary', x.AlbumPrimaryImageTag, 330) : '');
      return { name: x.Name, role: x.ProductionYear ? String(x.ProductionYear) : ({ Movie: 'Film', Series: 'Serie', Episode: 'Folge', MusicAlbum: 'Album', Audio: 'Titel' }[x.Type] || ''),
        image: image, icon: { Series: '🎞️', MusicAlbum: '🎵', Audio: '🎵', Episode: '📺' }[x.Type] || '🎬', square: sq };
    });
  }
  function extraCards() {
    return S.extras.map(function (x) {
      return { name: x.Name, type: x.ExtraType === 'Trailer' ? 'Trailer' : 'Extra', image: img(x.Id, 'Primary', (x.ImageTags || {}).Primary, 300), icon: '🎞️', wide: true };
    });
  }
  function tabsFor() {
    var m = S.m, k = S.kind;
    var all = k === 'series' ? ['Folgen', 'Übersicht', 'Darsteller', 'Ähnliche Titel']
      : k === 'album' ? ['Titel', 'Übersicht'] : k === 'folder' ? ['Inhalt', 'Übersicht']
      : ['Übersicht', 'Darsteller', 'Extras', 'Kapitel', 'Ähnliche Titel', 'Medieninformationen'];
    return all.filter(function (t) {
      if (t === 'Darsteller') return m.people.length;
      if (t === 'Extras') return S.extras.length;
      if (t === 'Kapitel') return m.chapters.length;
      if (t === 'Ähnliche Titel') return S.similar.length;
      if (t === 'Medieninformationen') return Object.keys(m.technical).length;
      return true;
    });
  }
  function seasonSelect() {
    if (S.seasons.length < 2 && S.item.Type !== 'Season') return '';
    return '<div class="sources"><label>Staffel<select data-season="1">' + S.seasons.map(function (x) {
      return '<option value="' + esc(x.Id) + '"' + (x.Id === S.season ? ' selected' : '') + '>' + esc(x.Name) + '</option>';
    }).join('') + '</select></label></div>';
  }
  function episodeList() {
    if (S.episodes === null) return '<p class="empty">Folgen werden geladen …</p>';
    if (!S.episodes.length) return '<p class="empty">Keine Folgen gefunden.</p>';
    return '<div class="eps">' + S.episodes.map(function (e, i) {
      var t = e.ImageTags || {}, ud = e.UserData || {};
      var image = t.Primary ? img(e.Id, 'Primary', t.Primary, 270) : (t.Thumb ? img(e.Id, 'Thumb', t.Thumb, 270) : '');
      var bar = ud.PlayedPercentage > 0 && ud.PlayedPercentage < 100 ? '<span class="bar"><i style="width:' + Math.round(ud.PlayedPercentage) + '%"></i></span>' : '';
      return '<div class="ep"><button class="epthumb" data-ep="' + i + '" aria-label="Abspielen"' + thumbStyle(image) + '>' + (image ? '' : '📺') + '<span class="epplay">▶</span>' + bar + '</button>' +
        '<div class="eptext"><h3><button class="eplink" data-epd="' + i + '">' + (e.IndexNumber != null ? e.IndexNumber + '. ' : '') + esc(e.Name) + '</button>' + (ud.Played ? ' <span class="epseen">✓</span>' : '') + '</h3>' +
        '<p class="epmeta">' + [mins(e.RunTimeTicks) ? mins(e.RunTimeTicks) + ' Minuten' : '', e.PremiereDate ? new Date(e.PremiereDate).toLocaleDateString('de-DE') : ''].filter(Boolean).join(' · ') + '</p>' +
        (e.Overview ? '<p class="epov">' + esc(e.Overview) + '</p>' : '') + '</div></div>';
    }).join('') + '</div>';
  }
  function trackList() {
    if (S.children === null) return '<p class="empty">Wird geladen …</p>';
    if (!S.children.length) return '<p class="empty">Keine Titel gefunden.</p>';
    return S.children.map(function (x, i) {
      return '<div class="row track" data-track="' + i + '"><strong>' + (x.IndexNumber != null ? x.IndexNumber + '. ' : '') + esc(x.Name) + '</strong><span>' + (x.RunTimeTicks ? clock(x.RunTimeTicks / 1e7) : '') + ' ▶</span></div>';
    }).join('');
  }
  function panel() {
    var m = S.m, tab = S.tab;
    if (tab === 'Folgen') return seasonSelect() + episodeList();
    if (tab === 'Titel') return trackList();
    if (tab === 'Inhalt') return S.children === null ? '<p class="empty">Wird geladen …</p>' : (S.children.length ? cards(itemCards(S.children), 'child') : '<p class="empty">Noch leer.</p>');
    if (tab === 'Darsteller') return cards(m.people, 'person');
    if (tab === 'Extras') return cards(extraCards(), 'extra');
    if (tab === 'Kapitel') return m.chapters.map(function (x, i) {
      return '<button class="ghost chap" data-chap="' + i + '">▶ ' + clock(x.time) + (x.name ? ' · ' + esc(x.name) : '') + '</button>';
    }).join(' ');
    if (tab === 'Ähnliche Titel') return cards(itemCards(S.similar), 'movie');
    if (tab === 'Medieninformationen') return Object.keys(m.technical).map(function (k) { return '<div class="row"><strong>' + esc(k) + '</strong><span>' + esc(m.technical[k]) + '</span></div>'; }).join('');
    return '<h2>' + (S.kind === 'video' ? 'Handlung' : 'Beschreibung') + '</h2><p class="overview">' + (m.overview ? esc(m.overview) : '<span class="empty">Keine Beschreibung vorhanden.</span>') + '</p>' +
      (m.directors.length ? '<div class="row"><strong>Regie</strong><span>' + esc(m.directors.join(', ')) + '</span></div>' : '') +
      (m.genres.length ? '<div class="row"><strong>Genres</strong><span>' + esc(m.genres.join(', ')) + '</span></div>' : '');
  }
  function jfSelect(cls) {
    var p = jfPage(), s = p && $('select.' + cls, p);
    return s && s.options.length ? s : null;
  }
  function select(label, key, sel, textFn) {
    if (!sel) return '';
    var o = [];
    for (var i = 0; i < sel.options.length; i++) {
      var op = sel.options[i];
      o.push('<option value="' + esc(op.value) + '"' + (op.selected ? ' selected' : '') + '>' + esc(textFn ? textFn(op.textContent) : op.textContent) + '</option>');
    }
    return '<label>' + esc(label) + '<select data-sel="' + key + '">' + o.join('') + '</select></label>';
  }
  function sourcesHtml() {
    if (S.kind !== 'video') return '';
    var src = jfSelect('selectSource'), vid = jfSelect('selectVideo');
    var vText = vid ? vid.options[vid.selectedIndex].textContent : '';
    var one = src && src.options.length === 1;
    return '<div class="sources">' + select('Videoquelle', 'selectSource', src, function (t) { return one ? 'Originaldatei' + (vText ? ' · ' + vText : '') : t; }) +
      select('Tonspur', 'selectAudio', jfSelect('selectAudio')) +
      select('Untertitel', 'selectSubtitles', jfSelect('selectSubtitles')) + '</div>';
  }
  function metaHtml() {
    var m = S.m, it = S.item, parts = [];
    if (it.Type === 'Episode' && it.ParentIndexNumber != null) parts.push('Staffel ' + it.ParentIndexNumber + ', Folge ' + (it.IndexNumber != null ? it.IndexNumber : '?'));
    if (m.year) parts.push(m.year);
    if (S.kind === 'series' && it.Type === 'Series' && S.seasons.length) parts.push(S.seasons.length + (S.seasons.length === 1 ? ' Staffel' : ' Staffeln'));
    if (S.kind === 'album' && it.AlbumArtist) parts.unshift(it.AlbumArtist);
    if ((S.kind === 'album' || S.kind === 'folder') && S.children && S.children.length) parts.push(S.children.length + (S.kind === 'album' ? ' Titel' : ' Einträge'));
    if (m.runtimeMinutes) parts.push(m.runtimeMinutes + ' Minuten');
    if (m.ageRating) parts.push(m.ageRating);
    if (m.rating) parts.push('★ ' + m.rating);
    if (m.genres.length) parts.push(m.genres.join(' / '));
    return parts.map(function (p) { return '<span>' + esc(p) + '</span>'; }).join('');
  }
  function actionsHtml() {
    var m = S.m, k = S.kind, h = '';
    if (k === 'video') {
      var resumable = m.progress > 0 && m.progress < 100;
      h += resumable ? '<button class="primary" data-action="resume">▶ Fortsetzen</button><button class="secondary" data-action="restart">Von Anfang an</button>'
        : '<button class="primary" data-action="play">▶ Abspielen</button>';
      if (S.trailers.length) h += '<button class="secondary" data-action="trailer">Trailer</button>';
    } else if (k === 'series') {
      var n = S.next, first = S.episodes && S.episodes[0];
      if (n) h += '<button class="primary" data-action="next">▶ ' + esc(S.item.Type === 'Series' && n.ParentIndexNumber != null ? 'S' + n.ParentIndexNumber + ':F' + n.IndexNumber + ' ansehen' : 'Weiterschauen') + '</button>';
      else if (first) h += '<button class="primary" data-action="first">▶ Abspielen</button>';
    } else if (S.children && S.children.length) {
      h += '<button class="primary" data-action="first">▶ ' + (k === 'album' ? 'Alle abspielen' : 'Abspielen') + '</button>';
    }
    if (S.item.Type !== 'Playlist') h += '<button class="secondary ' + (m.isFavorite ? 'active' : '') + '" data-action="favorite">' + (m.isFavorite ? '♥ Favorit' : '♡ Favorit') + '</button>';
    if (k === 'video' || k === 'series') h += '<button class="secondary ' + (m.isPlayed ? 'active' : '') + '" data-action="played">' + (m.isPlayed ? '✓ Gesehen' : 'Als gesehen markieren') + '</button>';
    return h;
  }
  function libView() {
    var want = { Movie: 'movies', Series: 'tvshows', Season: 'tvshows', Episode: 'tvshows', MusicAlbum: 'music', BoxSet: 'boxsets', Playlist: 'playlists' }[S.item.Type];
    var v = S.views.filter(function (x) { return x.CollectionType === want; });
    return v.filter(function (x) { return x.Id === S.item.ParentId; })[0] || v[0] || null;
  }
  function libHash(v) {
    var t = v.CollectionType;
    if (t === 'movies') return '#/movies?topParentId=' + v.Id + '&collectionType=movies';
    if (t === 'tvshows') return '#/tv?topParentId=' + v.Id + '&collectionType=tvshows';
    if (t === 'music') return '#/music?topParentId=' + v.Id + '&collectionType=music';
    return '#/list?parentId=' + v.Id;
  }

  function root() {
    var el = document.getElementById('bmcMd');
    if (!el) { el = document.createElement('div'); el.id = 'bmcMd'; document.body.appendChild(el); }
    document.body.classList.add('bmcMdOn');
    return el;
  }
  function close() {
    var el = document.getElementById('bmcMd'); if (el) el.remove();
    document.body.classList.remove('bmcMdOn');
  }

  function render() {
    if (!S || S.skip || !S.m || hashId() !== S.id) return;
    var m = S.m, it = S.item, app = root(), keepScroll = app.scrollTop;
    var tabs = tabsFor(); if (tabs.indexOf(S.tab) < 0) S.tab = tabs[0];
    var long = m.overview.length > 155;
    var menuItems = [];
    if (S.admin && it.Type !== 'BoxSet' && it.Type !== 'Playlist') menuItems.push(['addtocollection', 'Zur Sammlung hinzufügen']);
    if (it.Type !== 'Playlist') menuItems.push(['addtoplaylist', 'Zur Wiedergabeliste']);
    if (S.admin) { menuItems.push(['editimages', 'Bilder bearbeiten']); menuItems.push(['edit', 'Metadaten bearbeiten']); }
    if (S.admin && (it.Type === 'Movie' || it.Type === 'Series')) menuItems.push(['identify', 'Identifizieren']);
    if (m.canDownload) menuItems.push(['download', 'Herunterladen']);
    var lib = libView();
    var title = it.Type === 'Season' && it.SeriesName ? it.SeriesName + ' – ' + m.title : m.title;
    var eyebrow = EYEBROW[it.Type] + (it.Type === 'Episode' && it.SeriesName ? ' · ' + it.SeriesName.toUpperCase() : '');
    app.innerHTML = '<div class="backdrop' + (m.backdrop ? ' img' : '') + '"' + thumbStyle(m.backdrop) + '></div><div class="wrap"><header class="top"><div class="brand">BUTCHIES <b>MEDIA CENTER</b></div><nav class="nav">' +
      '<button class="ghost" data-route="home">⌂ Start</button>' + (lib ? '<button class="ghost" data-route="lib">' + esc(lib.Name) + '</button>' : '') +
      '<button class="ghost" data-route="search">⌕ Suche</button><button class="ghost" data-action="menu">⋯</button></nav></header>' +
      (S.menu ? '<div class="menu">' + menuItems.map(function (x) { return '<button data-menu="' + x[0] + '">' + esc(x[1]) + '</button>'; }).join('') + '</div>' : '') +
      '<main><section class="hero"><div class="poster' + (m.square ? ' square' : '') + '" aria-label="Bild"' + thumbStyle(m.poster) + '>' + (m.poster ? '' : (S.kind === 'album' ? '🎵' : '🎬')) + '</div><div><div class="eyebrow">' + esc(eyebrow) + '</div><h1>' + esc(title) + '</h1><div class="meta">' +
      metaHtml() + '</div>' +
      (m.tagline ? '<p class="tagline">' + esc(m.tagline) + '</p>' : '') +
      '<div class="actions">' + actionsHtml() + '</div>' +
      (m.overview ? '<p class="overview">' + esc(S.expanded || !long ? m.overview : m.overview.slice(0, 155) + '…') + (long ? ' <button class="ghost" data-action="expand">' + (S.expanded ? 'Weniger' : 'Mehr lesen') + '</button>' : '') + '</p>' : '') +
      sourcesHtml() + '</div></section><div class="tabs" role="tablist">' +
      tabs.map(function (t) { return '<button role="tab" aria-selected="' + (S.tab === t) + '" class="' + (S.tab === t ? 'active' : '') + '" data-tab="' + esc(t) + '">' + esc(t) + '</button>'; }).join('') +
      '</div><section class="panel">' + panel() + '</section></main></div>';
    app.scrollTop = keepScroll;
    bind(app);
    // Spurauswahl kommt von der Jellyfin-Seite darunter – die ist evtl. noch nicht fertig
    if (S.kind === 'video' && !jfSelect('selectAudio') && (S.waits = (S.waits || 0) + 1) < 20) { clearTimeout(S.wt); S.wt = setTimeout(render, 400); }
  }

  /* ---------- Bedienung ---------- */
  function go(hash) { S && (S.menu = false); location.hash = hash; }
  function details(id) { go('#/details?id=' + id + (S.m.serverId ? '&serverId=' + S.m.serverId : '')); }
  function clickJf(cls) { var b = jfBtn(cls); if (b) { b.click(); return true; } return false; }
  function viaMenu(id) {
    var b = jfBtn('btnMoreCommands'); if (!b) return;
    document.body.classList.add('bmcMdSilent');
    b.click();
    var n = 0;
    (function find() {
      var it = $('.actionSheet [data-id="' + id + '"]');
      if (it) { document.body.classList.remove('bmcMdSilent'); it.click(); return; }
      if (++n < 40) return setTimeout(find, 50);
      document.body.classList.remove('bmcMdSilent');
    })();
  }
  /* Abspielen im Butchies-Player (design/player) – mit der hier gewählten Ton- und Untertitelspur */
  function play(t) {
    var app = document.getElementById('bmcMd'), a = app && app.querySelector('select[data-sel="selectAudio"]'), s = app && app.querySelector('select[data-sel="selectSubtitles"]');
    var u = playUrl(S.id, t);
    if (a && a.value !== '') u += '&a=' + encodeURIComponent(a.value);
    if (s) u += '&s=' + (s.value === '-1' || s.value === '' ? 'off' : encodeURIComponent(s.value));
    location.href = u;
  }
  function bind(app) {
    app.querySelectorAll('[data-tab]').forEach(function (el) { el.onclick = function () { S.tab = el.dataset.tab; S.menu = false; render(); }; });
    app.querySelectorAll('[data-route]').forEach(function (el) {
      el.onclick = function () {
        var r = el.dataset.route, lib = libView();
        if (r === 'home') go('#/home');
        else if (r === 'search') go('#/search');
        else if (r === 'lib' && lib) go(libHash(lib));
      };
    });
    app.querySelectorAll('[data-card]').forEach(function (el) {
      el.onclick = function () {
        var k = el.dataset.card, i = +el.dataset.i;
        if (k === 'person') details(S.m.people[i].id);
        else if (k === 'movie') details(S.similar[i].Id);
        else if (k === 'extra') location.href = playUrl(S.extras[i].Id);
        else if (k === 'child') { var x = S.children[i]; if (VIDEO[x.Type] || x.Type === 'Audio') location.href = playUrl(x.Id); else details(x.Id); }
      };
    });
    app.querySelectorAll('[data-chap]').forEach(function (el) { el.onclick = function () { play(S.m.chapters[+el.dataset.chap].time); }; });
    app.querySelectorAll('[data-ep]').forEach(function (el) { el.onclick = function () { location.href = playUrl(S.episodes[+el.dataset.ep].Id); }; });
    app.querySelectorAll('[data-epd]').forEach(function (el) { el.onclick = function () { details(S.episodes[+el.dataset.epd].Id); }; });
    app.querySelectorAll('[data-track]').forEach(function (el) { el.onclick = function () { location.href = playUrl(S.children[+el.dataset.track].Id); }; });
    app.querySelectorAll('[data-menu]').forEach(function (el) { el.onclick = function () { S.menu = false; render(); viaMenu(el.dataset.menu); }; });
    app.querySelectorAll('select[data-season]').forEach(function (el) { el.onchange = function () { S.season = el.value; loadEpisodes(S); render(); }; });
    app.querySelectorAll('select[data-sel]').forEach(function (el) {
      el.onchange = function () {
        var o = jfSelect(el.dataset.sel); if (!o) return;
        o.value = el.value; o.dispatchEvent(new Event('change', { bubbles: true }));
        if (el.dataset.sel === 'selectSource') setTimeout(render, 300);
      };
    });
    app.querySelectorAll('[data-action]').forEach(function (el) {
      el.onclick = function () {
        var a = el.dataset.action, m = S.m;
        if (a === 'menu') { S.menu = !S.menu; return render(); }
        S.menu = false;
        if (a === 'play' || a === 'resume') return play();
        if (a === 'restart') return play(0);
        if (a === 'trailer') { location.href = playUrl(S.trailers[0].Id); return; }
        if (a === 'next' && S.next) { location.href = playUrl(S.next.Id); return; }
        if (a === 'first') { var f = (S.kind === 'series' ? S.episodes : S.children) || []; if (f[0]) location.href = playUrl(f[0].Id); return; }
        if (a === 'favorite') { if (clickJf('btnUserRating')) m.isFavorite = !m.isFavorite; }
        else if (a === 'played') { if (clickJf('btnPlaystate')) { m.isPlayed = !m.isPlayed; if (m.isPlayed) m.progress = 0; if (S.kind === 'series') setTimeout(function () { loadEpisodes(S); }, 800); } }
        else if (a === 'expand') S.expanded = !S.expanded;
        render();
      };
    });
  }
  document.addEventListener('click', function (e) {   // Menü schließt bei Klick daneben
    if (S && S.menu && !e.target.closest('#bmcMd .menu, #bmcMd [data-action="menu"]')) { S.menu = false; render(); }
  });

  /* ---------- Ein-/Ausblenden je nach Seite ---------- */
  function check() {
    var id = hashId();
    if (!id) { loading = null; close(); return; }
    if (S && S.id === id) {
      if (S.skip) return close();
      if (!document.getElementById('bmcMd')) render();
      return;
    }
    close(); S = null;
    if (client()) load(id); else schedule();
  }
  function schedule() { clearTimeout(timer); timer = setTimeout(check, 120); }
  window.addEventListener('hashchange', function () { S && S.id !== hashId() && (S = null); schedule(); });
  window.addEventListener('pageshow', function (e) { if (e.persisted) S = null; schedule(); });   // zurück aus dem Player → Fortschritt neu laden
  document.addEventListener('viewshow', function () {   // Jellyfin-Seite neu aufgebaut → Spurauswahl/Status neu lesen
    if (S && S.id === hashId() && !S.skip) { S = null; } schedule();
  });
  schedule();
})();
