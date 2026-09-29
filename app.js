/* Sports Odds — renders data.json into league tabs + pick cards. */
(function () {
  'use strict';

  var esc = function (value) {
    return String(value == null ? '' : value).replace(/[&<>'"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[c];
    });
  };
  var record = function (value) {
    return value ? '<span class="record">' + esc(value) + '</span>' : '';
  };

  function gameCard(game) {
    var market = [];
    if (game.event) market.push('<span>' + esc(game.event) + '</span>');
    if (game.venue) market.push('<span>' + esc(game.venue) + '</span>');
    if (game.line) market.push('<span>' + (game.probs ? '3-way: ' : 'Line: ') + esc(game.line) + '</span>');
    if (game.total) market.push('<span>Total ' + esc(game.total) + '</span>');
    if (!market.length) market.push('<span>Detailed line not shown</span>');
    var inputText = game.inputText || (game.line || game.total
      ? 'Inputs: listed market, team records and matchup context.'
      : 'Inputs: matchup context; detailed market inputs not shown.');
    var breakdown = game.probs ? (
      '<div class="soccer-probs" aria-label="Three-way probabilities: home ' + game.probs.h +
      ' percent, draw ' + game.probs.d + ' percent, away ' + game.probs.a + ' percent">' +
      '<span>H <strong>' + game.probs.h + '%</strong></span>' +
      '<span>D <strong>' + game.probs.d + '%</strong></span>' +
      '<span>A <strong>' + game.probs.a + '%</strong></span></div>'
    ) : '';
    var callLabel = game.pick_label || ((game.pick || '') + ' wins');
    return (
      '<article class="game-card ' + esc(game.side) + '">' +
        '<div>' +
          '<p class="game-time">' + esc(game.time) + '</p>' +
          '<div class="matchup" aria-label="' + esc(game.away) + ' at ' + esc(game.home) + '">' +
            '<div class="team-row"><span>' + esc(game.away) + '</span>' + record(game.ar) + '</div>' +
            '<div class="at">@</div>' +
            '<div class="team-row"><span>' + esc(game.home) + '</span>' + record(game.hr) + '</div>' +
          '</div>' +
          '<div class="market">' + market.join('') + '</div>' +
          '<p class="inputs">' + esc(inputText) + '</p>' +
        '</div>' +
        '<div class="pick-side">' +
          '<span class="call">' + esc(callLabel) + '</span>' +
          '<div class="probability">' +
            '<div class="bar-labels"><span>' + (game.probs ? 'Jev pick' : 'Winner probability') + '</span><strong>' + game.pct + '%</strong></div>' +
            '<div class="bar" role="img" aria-label="' + game.pct + ' percent probability that ' + esc(game.pick) + ' wins"><span style="width:' + game.pct + '%"></span></div>' +
            breakdown +
          '</div>' +
          '<div class="metric-row"><span>Jev confidence</span><strong>' + Number(game.conf).toFixed(2) + '</strong></div>' +
        '</div>' +
      '</article>'
    );
  }

  function panel(league, index) {
    var selected = index === 0;
    var body;
    if (!league.games || !league.games.length) {
      body =
        '<div class="empty-state"><div class="empty-copy">' +
        '<span class="empty-mark">—</span>' +
        '<h2>' + esc(league.empty || 'No games today') + '</h2>' +
        '<p>' + esc(league.note || 'Check back tomorrow — the board refreshes every morning.') + '</p>' +
        '</div></div>';
    } else {
      body =
        '<div class="section-head">' +
          '<div><h2>' + esc(league.title) + '</h2><span class="count">' + esc(league.count) + '</span></div>' +
          '<div class="legend" aria-label="Pick color legend">' +
            '<span><i class="away-dot"></i>Away pick</span>' +
            '<span><i class="home-dot"></i>Home pick</span>' +
          '</div>' +
        '</div>' +
        '<div class="games">' + league.games.map(gameCard).join('') + '</div>';
    }
    return (
      '<section class="section" id="panel-' + league.id + '" role="tabpanel" aria-labelledby="tab-' + league.id + '"' +
      (selected ? '' : ' hidden') + '>' + body + '</section>'
    );
  }

  function render(data) {
    var ts = document.getElementById('timestamp');
    ts.textContent = data.generated_et || '';
    var sub = document.getElementById('subtitle');
    if (data.subtitle) sub.textContent = data.subtitle;

    var notice = document.getElementById('changes-notice');
    if (data.changes && data.changes.length) {
      notice.hidden = false;
      notice.innerHTML = '<strong>Latest changes.</strong> ' + data.changes.map(esc).join(' ');
    }

    var tabsEl = document.getElementById('tabs');
    tabsEl.innerHTML = data.leagues.map(function (league, i) {
      var n = league.games ? league.games.length : 0;
      return '<button class="tab" id="tab-' + league.id + '" type="button" role="tab" ' +
        'aria-selected="' + (i === 0) + '" aria-controls="panel-' + league.id + '" ' +
        'data-panel="panel-' + league.id + '"' + (i === 0 ? '' : ' tabindex="-1"') + '>' +
        esc(league.short) + (n ? ' <small>' + n + '</small>' : '') + '</button>';
    }).join('');

    document.getElementById('panels').innerHTML = data.leagues.map(panel).join('');

    var tabs = Array.prototype.slice.call(tabsEl.querySelectorAll('.tab'));
    var panels = Array.prototype.slice.call(document.querySelectorAll('[role="tabpanel"]'));
    var activeIndex = 0, touchStartX = null, touchStartY = null;

    function activate(index, direction, moveFocus) {
      if (index < 0 || index >= tabs.length || index === activeIndex) return;
      activeIndex = index;
      tabs.forEach(function (tab, i) {
        var selected = i === index;
        tab.setAttribute('aria-selected', selected ? 'true' : 'false');
        tab.tabIndex = selected ? 0 : -1;
      });
      panels.forEach(function (p, i) {
        p.hidden = i !== index;
        p.classList.remove('is-entering', 'from-left');
      });
      var p = panels[index];
      p.classList.add('is-entering');
      if (direction < 0) p.classList.add('from-left');
      if (moveFocus) tabs[index].focus({ preventScroll: true });
    }

    tabs.forEach(function (tab, index) {
      tab.addEventListener('click', function () { activate(index, index > activeIndex ? 1 : -1); });
      tab.addEventListener('keydown', function (event) {
        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].indexOf(event.key) === -1) return;
        event.preventDefault();
        var next = activeIndex;
        if (event.key === 'ArrowLeft') next = (activeIndex - 1 + tabs.length) % tabs.length;
        if (event.key === 'ArrowRight') next = (activeIndex + 1) % tabs.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = tabs.length - 1;
        activate(next, next > activeIndex ? 1 : -1, true);
      });
    });

    var panelsRoot = document.getElementById('panels');
    panelsRoot.addEventListener('touchstart', function (event) {
      if (event.touches.length !== 1) return;
      touchStartX = event.touches[0].clientX;
      touchStartY = event.touches[0].clientY;
    }, { passive: true });
    panelsRoot.addEventListener('touchend', function (event) {
      if (touchStartX === null || touchStartY === null || !event.changedTouches.length) return;
      var dx = event.changedTouches[0].clientX - touchStartX;
      var dy = event.changedTouches[0].clientY - touchStartY;
      touchStartX = touchStartY = null;
      if (Math.abs(dx) < 48 || Math.abs(dx) < Math.abs(dy) * 1.25) return;
      if (dx < 0 && activeIndex < tabs.length - 1) activate(activeIndex + 1, 1);
      if (dx > 0 && activeIndex > 0) activate(activeIndex - 1, -1);
    }, { passive: true });
  }

  function fail(message) {
    document.getElementById('timestamp').textContent = 'Update failed';
    document.getElementById('panels').innerHTML =
      '<div class="error-state"><p>' + esc(message) + '</p></div>';
  }

  fetch('data.json?v=' + Date.now(), { cache: 'no-store' })
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(render)
    .catch(function (e) { fail('Could not load today\'s picks (' + e.message + '). Try refreshing.'); });

  // Auto-refresh the data every 30 minutes while the page is open.
  setInterval(function () {
    fetch('data.json?v=' + Date.now(), { cache: 'no-store' })
      .then(function (r) { if (r.ok) return r.json(); })
      .then(function (d) { if (d) render(d); })
      .catch(function () {});
  }, 30 * 60 * 1000);
})();
