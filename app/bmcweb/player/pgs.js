/* Bild-Untertitel (PGS / Blu-ray .sup) für den Butchies-Player: einlesen und auf ein Overlay zeichnen. */
(function () {
  'use strict';
  function clamp(x) { return x < 0 ? 0 : x > 255 ? 255 : x | 0; }
  function palEntry(Y, Cr, Cb, A) {
    // BT.709, begrenzter Bereich
    const y = 1.164 * (Y - 16), cr = Cr - 128, cb = Cb - 128;
    return [clamp(y + 1.793 * cr), clamp(y - 0.213 * cb - 0.533 * cr), clamp(y + 2.112 * cb), A];
  }
  // Liest eine .sup-Datei -> Liste von Anzeige-Ereignissen {t, w, h, objs:[{x,y,w,h,rle,pal}]}
  function parse(buf) {
    const d = new Uint8Array(buf), n = d.length;
    const events = [];
    const palettes = {}, objects = {};
    let pcs = null, p = 0;
    while (p + 13 <= n) {
      if (d[p] !== 0x50 || d[p + 1] !== 0x47) { p++; continue; }       // "PG"
      const pts = ((d[p + 2] << 24) >>> 0) + (d[p + 3] << 16) + (d[p + 4] << 8) + d[p + 5];
      const type = d[p + 10], size = (d[p + 11] << 8) | d[p + 12];
      const s = p + 13;
      p = s + size;
      if (p > n) break;
      if (type === 0x16) {                                              // Bildaufbau
        const cnt = d[s + 10];
        const comps = [];
        let q = s + 11;
        for (let i = 0; i < cnt && q + 8 <= p; i++) {
          const oid = (d[q] << 8) | d[q + 1], crop = d[q + 3];
          comps.push({ oid, x: (d[q + 4] << 8) | d[q + 5], y: (d[q + 6] << 8) | d[q + 7] });
          q += (crop & 0x80) ? 16 : 8;
        }
        pcs = { t: pts / 90000, w: (d[s] << 8) | d[s + 1], h: (d[s + 2] << 8) | d[s + 3], state: d[s + 7], pal: d[s + 9], comps };
        if (pcs.state & 0x80) { for (const k in objects) delete objects[k]; }   // neue Epoche
      } else if (type === 0x14) {                                       // Farbtabelle
        const id = d[s];
        const pal = palettes[id] = palettes[id] ? palettes[id].slice() : new Array(256).fill(null);
        for (let q = s + 2; q + 5 <= p; q += 5) pal[d[q]] = palEntry(d[q + 1], d[q + 2], d[q + 3], d[q + 4]);
      } else if (type === 0x15) {                                       // Bildobjekt (lauflängenkodiert)
        const oid = (d[s] << 8) | d[s + 1], seq = d[s + 3];
        if (seq & 0x80) {
          objects[oid] = { w: (d[s + 7] << 8) | d[s + 8], h: (d[s + 9] << 8) | d[s + 10], parts: [d.subarray(s + 11, p)] };
        } else if (objects[oid]) {
          objects[oid].parts.push(d.subarray(s + 4, p));
        }
      } else if (type === 0x80 && pcs) {                                // Ende -> Ereignis fertig
        const pal = palettes[pcs.pal];
        const objs = [];
        for (const c of pcs.comps) {
          const o = objects[c.oid];
          if (!o || !pal) continue;
          objs.push({ x: c.x, y: c.y, w: o.w, h: o.h, parts: o.parts, pal });
        }
        events.push({ t: pcs.t, w: pcs.w, h: pcs.h, objs });
        pcs = null;
      }
    }
    events.sort((a, b) => a.t - b.t);
    for (let i = 0; i < events.length; i++) events[i].e = i + 1 < events.length ? events[i + 1].t : events[i].t + 8;
    return events.filter((e) => e.objs.length);
  }
  function decode(o) {
    let len = 0; o.parts.forEach((x) => { len += x.length; });
    const r = new Uint8Array(len); let k = 0; o.parts.forEach((x) => { r.set(x, k); k += x.length; });
    const img = new ImageData(o.w, o.h), px = img.data;
    let x = 0, y = 0, i = 0;
    function put(c, cnt) {
      const e = o.pal[c];
      for (let j = 0; j < cnt && x < o.w; j++, x++) {
        if (!e || !e[3]) continue;
        const a = (y * o.w + x) * 4;
        px[a] = e[0]; px[a + 1] = e[1]; px[a + 2] = e[2]; px[a + 3] = e[3];
      }
    }
    while (i < r.length && y < o.h) {
      const b = r[i++];
      if (b) { put(b, 1); continue; }
      const f = r[i++];
      if (f === 0) { x = 0; y++; continue; }
      let cnt = f & 0x3f;
      if (f & 0x40) cnt = (cnt << 8) | r[i++];
      const c = (f & 0x80) ? r[i++] : 0;
      put(c, cnt);
    }
    return img;
  }
  // Overlay: zeichnet das zur Zeit t passende Ereignis
  function Renderer(canvas) {
    const ctx = canvas.getContext('2d');
    let events = null, shown = null;
    return {
      set(ev) { events = ev; shown = null; ctx.clearRect(0, 0, canvas.width, canvas.height); },
      draw(t) {
        let cur = null;
        if (events) {
          let lo = 0, hi = events.length - 1;
          while (lo <= hi) { const m = (lo + hi) >> 1; if (events[m].t <= t) lo = m + 1; else hi = m - 1; }
          const e = events[hi];
          if (e && e.t <= t && e.e > t) cur = e;
        }
        if (cur === shown) return;
        shown = cur;
        if (cur && (canvas.width !== cur.w || canvas.height !== cur.h)) { canvas.width = cur.w; canvas.height = cur.h; }
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        if (!cur) return;
        cur.objs.forEach((o) => { if (!o.img) o.img = decode(o); ctx.putImageData(o.img, o.x, o.y); });
      }
    };
  }
  window.BmcPgs = { parse, Renderer };
})();
