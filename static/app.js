// As Stated: progressive enhancements. Every page works without this file.
(function () {
  "use strict";
  document.documentElement.setAttribute("data-js", "1");

  // Case index filters
  var form = document.getElementById("filters");
  var index = document.getElementById("case-index");
  if (form && index) {
    form.hidden = false;
    var rows = Array.prototype.slice.call(index.querySelectorAll("tbody tr"));
    var get = function (id) { return document.getElementById(id); };
    var q = get("f-text"), outcome = get("f-outcome"), track = get("f-track"), after = get("f-after"), count = get("f-count");
    var has = function (list, v) { return (" " + list + " ").indexOf(" " + v + " ") !== -1; };
    var apply = function () {
      var s = q.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (r) {
        var ok = (!s || r.dataset.text.indexOf(s) !== -1) &&
          (!outcome.value || has(r.dataset.outcomes, outcome.value)) &&
          (!track.value || r.dataset.track === track.value) &&
          (!after.value || has(r.dataset.after, after.value));
        r.hidden = !ok;
        if (ok) { shown += 1; }
      });
      count.textContent = shown + " of " + rows.length + " records";
    };
    [q, outcome, track, after].forEach(function (el) {
      el.addEventListener("input", apply);
      el.addEventListener("change", apply);
    });
    form.addEventListener("submit", function (e) { e.preventDefault(); });
    apply();
  }

  // Copy buttons (citation, BibTeX)
  Array.prototype.forEach.call(document.querySelectorAll("[data-copy]"), function (btn) {
    btn.addEventListener("click", function () {
      var el = document.getElementById(btn.getAttribute("data-copy"));
      if (!el) { return; }
      var label = btn.textContent;
      var done = function () { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = label; }, 1500); };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(el.textContent).then(done);
      } else {
        var range = document.createRange(); range.selectNodeContents(el);
        var sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
        try { document.execCommand("copy"); done(); } catch (e) { /* text stays selected for manual copy */ }
      }
    });
  });
})();
