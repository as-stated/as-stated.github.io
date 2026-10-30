// As Stated: progressive enhancements. Every page works without this file.
(function () {
  "use strict";
  document.documentElement.setAttribute("data-js", "1");

  // Claim index filters: rows are claims, groups are papers.
  var form = document.getElementById("filters");
  var index = document.getElementById("case-index");
  if (form && index) {
    form.hidden = false;
    var groups = Array.prototype.slice.call(index.querySelectorAll("tbody.ix-group"));
    var get = function (id) { return document.getElementById(id); };
    var q = get("f-text"), fam = get("f-fam"), kind = get("f-kind"), track = get("f-track"), count = get("f-count");
    var total = index.querySelectorAll("tr.ix-row").length;
    var apply = function () {
      var s = q.value.trim().toLowerCase();
      var claims = 0, papers = 0;
      groups.forEach(function (g) {
        var trackOk = !track.value || g.dataset.track === track.value;
        var shown = 0;
        Array.prototype.forEach.call(g.querySelectorAll("tr.ix-row"), function (r) {
          var ok = trackOk && (!s || r.dataset.text.indexOf(s) !== -1) &&
            (!fam.value || r.dataset.fam === fam.value) && (!kind.value || r.dataset.kind === kind.value);
          r.hidden = !ok;
          if (ok) { shown += 1; }
        });
        g.hidden = shown === 0;
        claims += shown;
        if (shown) { papers += 1; }
      });
      count.textContent = claims === total ? total + " claims in " + groups.length + " papers"
        : claims + " of " + total + " claims, in " + papers + " paper" + (papers === 1 ? "" : "s");
    };
    [q, fam, kind, track].forEach(function (el) {
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
