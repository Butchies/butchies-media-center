/* Butchies Media Center: Film-/Serien-Detailseite im gewohnten Aufbau (eigene Umsetzung).
   Ganzseitiges Hintergrundbild, links das Poster, rechts Logo bzw. Titel, Infozeile
   (★ Bewertung · Jahr · Laufzeit · FSK · Genres · Endet um), Spurauswahl in einer Zeile,
   Knöpfe als Pillen/Kreise, Beschreibung mit „Mehr“, „Regisseur: …“. Darunter die Reihen
   „Besetzung & Mitwirkende“ und „Ähnlich wie dieses“ über die volle Breite.
   Die Elemente der Jellyfin-Seite werden nur innerhalb derselben Seite umgestellt. */
(function () {
  'use strict';
  var TYPES = { Movie: 1, Series: 1, Season: 1, Episode: 1, Video: 1, MusicVideo: 1, BoxSet: 1, Trailer: 1 };
  var typeCache = {}, pending = false;

  function $(s, r) { return (r || document).querySelector(s); }
  function currentPage() {
    var ps = document.querySelectorAll('.itemDetailPage');
    for (var i = 0; i < ps.length; i++) if (!ps[i].classList.contains('hide')) return ps[i];
    return null;
  }
  function itemId() { var m = location.hash.match(/[?&]id=([0-9a-f]{32})/i); return m ? m[1].toLowerCase() : null; }

  function withType(id, cb) {
    if (typeCache[id]) return cb(typeCache[id]);
    var c = window.ApiClient; if (!c || !c.getCurrentUserId()) return;
    if (typeCache[id] === 0) return; typeCache[id] = 0;
    c.getItem(c.getCurrentUserId(), id).then(function (it) { typeCache[id] = it.Type || '-'; schedule(); }, function () { delete typeCache[id]; });
  }

  function into(parent, el) { if (el && el.parentNode !== parent) parent.appendChild(el); }

  function runtimeText(t) {   // „1h 38m“ → „1h, 38 Min.“, „45m“ → „45 Min.“
    var m = t.match(/^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m(?:in)?\.?)?\s*$/i);
    if (!m || (!m[1] && !m[2])) return null;
    if (m[1] && m[2]) return m[1] + 'h, ' + m[2] + ' Min.';
    if (m[1]) return m[1] + 'h';
    return m[2] + ' Min.';
  }

  function build(page) {
    var wrapper = $('.detailPageWrapperContainer', page);
    if (!wrapper) return;
    var head = $('.bmcHead', page);
    if (!head) {
      head = document.createElement('div'); head.className = 'bmcHead';
      head.innerHTML = '<div class="bmcPoster"></div><div class="bmcInfo"></div>';
      wrapper.insertBefore(head, wrapper.firstChild);
    }
    var poster = $('.bmcPoster', head), info = $('.bmcInfo', head);
    into(poster, $('.detailImageContainer', page));
    into(info, $('.detailLogo', page));
    into(info, $('.nameContainer', page));
    into(info, $('.itemMiscInfo-primary', page));
    into(info, $('.itemMiscInfo-secondary', page));
    into(info, $('.trackSelections', page));
    into(info, $('.mainDetailButtons', page));
    into(info, $('.detailSectionContent', page));
    into(info, $('.itemDetailsGroup', page));

    // Logo vorhanden → Titeltext ausblenden (wie gewohnt nur das Logo)
    var logo = $('.detailLogo', info);
    var hasLogo = !!(logo && !logo.classList.contains('hide') && /url\(/.test(logo.style.backgroundImage || ''));
    head.classList.toggle('bmc-haslogo', hasLogo);

    // Infozeile: Laufzeit-Schreibweise und Genres
    var misc = $('.itemMiscInfo-primary', info);
    if (misc) {
      var items = misc.querySelectorAll('.mediaInfoItem');
      for (var i = 0; i < items.length; i++) {
        var el = items[i];
        if (el.children.length || el.classList.contains('bmcGenres')) continue;
        var nt = runtimeText(el.textContent);
        if (nt && nt !== el.textContent) el.textContent = nt;
      }
      var genres = [].map.call(page.querySelectorAll('.genresGroup .genres a'), function (a) { return a.textContent.trim(); }).filter(Boolean).join(', ');
      var g = $('.bmcGenres', misc);
      if (genres) {
        if (!g) { g = document.createElement('div'); g.className = 'mediaInfoItem bmcGenres'; misc.appendChild(g); }
        if (g.textContent !== genres) g.textContent = genres;
      } else if (g) g.remove();
    }
    // Bewertung mit Komma (6,1)
    var star = $('.starRatingContainer', info);
    if (star) { var tn = [].filter.call(star.childNodes, function (n) { return n.nodeType === 3 && /\d\.\d/.test(n.nodeValue); })[0];
      if (tn) tn.nodeValue = tn.nodeValue.replace(/(\d)\.(\d)/, '$1,$2'); }
    // Überschrift der ähnlichen Titel
    var h = $('#similarCollapsible .sectionTitle', page);
    if (h && h.textContent.trim() === 'Ähnliches') h.textContent = 'Ähnlich wie dieses';
  }

  function tick() {
    pending = false;
    var page = currentPage();
    document.body.classList.toggle('bmc-detail-on', !!(page && page.classList.contains('bmc-detail')));
    if (!page) return;
    var id = itemId();
    if (!id) return;
    var t = typeCache[id];
    if (!t) { withType(id, function () {}); return; }
    var on = !!TYPES[t];
    page.classList.toggle('bmc-detail', on);
    if (on) build(page);
  }
  function schedule() { if (!pending) { pending = true; requestAnimationFrame(tick); } }
  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style'] });
  window.addEventListener('hashchange', schedule);
  schedule();
})();
