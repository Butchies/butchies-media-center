/* Butchies Media Center: Einstellung „Bildgröße“ – eigene Umsetzung.
   Einstellungen → Anzeige → „Bildgröße“ (unter dem Anzeigemodus, über dem Bildschirmschoner).
   7 Stufen, wird sofort und nur für dieses Gerät gespeichert (Schlüssel cardSize).
   Die Stufe wird als Zahl +3 … -3 in die CSS-Variable --bmc-cs geschrieben (siehe bmc-cardsize.css). */
(function () {
  'use strict';
  var KEY = 'cardSize';
  var VALUES = { extrasmall: 3, smaller: 2, small: 1, '': 0, large: -1, larger: -2, extralarge: -3 };
  var LABELS = [['extrasmall', 'Extra klein'], ['smaller', 'Kleiner'], ['small', 'Klein'], ['', 'Standard'],
    ['large', 'Groß'], ['larger', 'Größer'], ['extralarge', 'Extra groß']];

  function supported() {
    try { return CSS.supports('width', 'calc(100% / max(var(--x, 1), 1))'); } catch (e) { return false; }
  }
  function storeKey() {  // je Gerät; mit Benutzer-ID, falls angemeldet (wie die Jellyfin-Geräteeinstellungen)
    var uid = '';
    try { uid = window.ApiClient && ApiClient.getCurrentUserId() || ''; } catch (e) {}
    return (uid ? uid + '-' : '') + KEY;
  }
  function read() {
    var v = null;
    try { v = localStorage.getItem(storeKey()); if (v === null) v = localStorage.getItem(KEY); } catch (e) {}
    if (v === null || v === 'normal' || v === 'default') v = '';   // alte Werte = Standard
    return Object.prototype.hasOwnProperty.call(VALUES, v) ? v : '';
  }
  function write(v) {
    try { localStorage.setItem(storeKey(), v === '' ? 'normal' : v); } catch (e) {}
  }
  function apply(v) {
    if (v === undefined) v = read();
    var adj = VALUES[v] || 0, root = document.documentElement;
    root.style.setProperty('--bmc-cs', String(adj));
    root.classList.toggle('bmc-cs', adj !== 0 && supported());
  }

  // ---- Feld in Einstellungen → Anzeige
  function makeField() {
    var box = document.createElement('div');
    box.className = 'selectContainer bmcCardSizeContainer';
    var id = 'bmcSelectCardSize';
    var label = document.createElement('label');
    label.className = 'selectLabel'; label.htmlFor = id; label.textContent = 'Bildgröße';
    var sel = document.createElement('select');
    sel.id = id; sel.className = 'emby-select-withcolor emby-select';
    LABELS.forEach(function (o) { var op = document.createElement('option'); op.value = o[0]; op.textContent = o[1]; sel.appendChild(op); });
    var arrow = document.createElement('div');
    arrow.className = 'selectArrowContainer';
    arrow.innerHTML = '<div style="visibility:hidden;display:none;">0</div><span class="selectArrow material-icons keyboard_arrow_down" aria-hidden="true"></span>';
    var desc = document.createElement('div');
    desc.className = 'fieldDescription';
    desc.textContent = 'Lege die gewünschte Größe der Bildraster fest. Gilt nur für dieses Gerät und wird sofort gespeichert.';
    sel.value = read();
    sel.addEventListener('change', function () { write(sel.value); apply(sel.value); });
    box.appendChild(label); box.appendChild(sel); box.appendChild(arrow); box.appendChild(desc);
    return box;
  }
  function addToSettings() {
    if (!supported()) return;   // wie im Vorbild: nur anzeigen, wenn der Browser die Berechnung kann
    var forms = document.querySelectorAll('form.displaySettingsForm, .displaySettings form, form');
    for (var i = 0; i < forms.length; i++) {
      var f = forms[i];
      var screensaver = f.querySelector('.selectScreensaverContainer');
      var layout = f.querySelector('#selectLayout, .selectLayout');
      if (!screensaver && !layout) continue;
      if (f.querySelector('.bmcCardSizeContainer')) return;
      var field = makeField();
      var layoutBox = layout && layout.closest('.selectContainer');
      if (layoutBox && layoutBox.parentNode) layoutBox.parentNode.insertBefore(field, layoutBox.nextSibling);
      else screensaver.parentNode.insertBefore(field, screensaver);
      // Wechsel des Anzeigemodus (TV/Desktop/Mobil) setzt die Bildgröße auf Standard zurück
      if (layout && !layout.__bmcCs) {
        layout.__bmcCs = true;
        layout.addEventListener('change', function () {
          write(''); apply('');
          var s = document.getElementById('bmcSelectCardSize'); if (s) s.value = '';
        });
      }
      return;
    }
  }

  var pending = false;
  function tick() { pending = false; addToSettings(); }
  function schedule() { if (!pending) { pending = true; setTimeout(tick, 150); } }
  apply();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', schedule); else schedule();
  new MutationObserver(schedule).observe(document.documentElement, { childList: true, subtree: true });
  // nach dem Anmelden gilt der Wert des Benutzers
  window.addEventListener('hashchange', function () { apply(); });
  window.addEventListener('storage', function (e) { if (e.key && e.key.slice(-KEY.length) === KEY) apply(); });
})();
