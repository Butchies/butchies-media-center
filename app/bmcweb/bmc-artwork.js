/* Butchies Media Center: native home artwork layout. */
(function () {
  'use strict';
  var names = ['poster','wide','square','classic','banner'];
  function classify(r) {
    if (r >= 3) return 'banner';
    if (r >= 1.4) return 'wide';
    if (r > 1.2) return 'classic';
    if (r > .73) return 'square';
    return 'poster';
  }
  function visibleHome() {
    var roots = document.querySelectorAll('.homePage, #homePage');
    for (var i = 0; i < roots.length; i++) {
      var e = roots[i];
      if (!e.hidden && !e.classList.contains('hide') && getComputedStyle(e).display !== 'none') return e;
    }
    return null;
  }
  function ratioFor(card, frame) {
    var image = frame.querySelector('img');
    if (image && image.naturalWidth && image.naturalHeight) return image.naturalWidth / image.naturalHeight;
    var candidates = [card, frame];
    for (var i = 0; i < candidates.length; i++) {
      var cls = String(candidates[i].className || '');
      if (/banner/i.test(cls)) return 1000/185;
      if (/square/i.test(cls)) return 1;
      if (/fourThree/i.test(cls)) return 4/3;
      if (/portrait/i.test(cls)) return 2/3;
      if (/backdrop|landscape/i.test(cls)) return 16/9;
    }
    var pad = card.querySelector('.cardPadder');
    if (pad) {
      var rect = pad.getBoundingClientRect();
      if (rect.width && rect.height) return rect.width / rect.height;
    }
    return 0;
  }
  function refresh() {
    var home = visibleHome();
    document.querySelectorAll('.bmc-artwork-home').forEach(function (node) {
      if (node !== home) node.classList.remove('bmc-artwork-home');
    });
    if (!home) return;
    home.classList.add('bmc-artwork-home');
    home.querySelectorAll('.card').forEach(function (card) {
      var frame = card.querySelector('.cardImageContainer');
      if (!frame) return;
      var ratio = ratioFor(card, frame);
      if (!ratio || !isFinite(ratio)) return;
      var desired = 'bmc-artwork-' + classify(ratio);
      if (card.classList.contains(desired)) return;
      names.forEach(function (n) { card.classList.remove('bmc-artwork-' + n); });
      card.classList.add('bmc-artwork-card', desired);
    });
  }
  var pending = false;
  function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; refresh(); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', schedule);
  else schedule();
  new MutationObserver(schedule).observe(document.documentElement, {childList:true, subtree:true, attributes:true, attributeFilter:['class','hidden']});
  document.addEventListener('load', function (e) { if (e.target && e.target.tagName === 'IMG') schedule(); }, true);
})();
