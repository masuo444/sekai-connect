/**
 * Connect-Sekai Tools — 共通ユーティリティ
 */
var CSTools = (function () {
  'use strict';

  /* ── 数値フォーマット ── */
  function formatNumber(n) {
    if (n == null || isNaN(n)) return '0';
    return Number(n).toLocaleString('ja-JP');
  }

  function formatManen(n) {
    return formatNumber(Math.round(n)) + '万円';
  }

  function formatPercent(n, digits) {
    digits = digits !== undefined ? digits : 1;
    return Number(n).toFixed(digits) + '%';
  }

  /* ── 横棒グラフ描画 ── */
  /**
   * renderBarChart(container, data, opts)
   *   container : DOM element
   *   data      : [{label, value, color?, sub?}]
   *   opts      : {unit?, maxValue?, showValue?, suffix?, animate?}
   */
  function renderBarChart(container, data, opts) {
    opts = opts || {};
    var unit = opts.unit || '';
    var suffix = opts.suffix || '';
    var showValue = opts.showValue !== false;
    var animate = opts.animate !== false;

    var maxVal = opts.maxValue || 0;
    for (var i = 0; i < data.length; i++) {
      if (data[i].value > maxVal) maxVal = data[i].value;
    }
    if (maxVal === 0) maxVal = 1;

    container.innerHTML = '';
    container.className = 'cs-bar-chart';

    for (var j = 0; j < data.length; j++) {
      var item = data[j];
      var row = document.createElement('div');
      row.className = 'cs-bar-row';
      row.style.animationDelay = (j * 0.06) + 's';

      var label = document.createElement('span');
      label.className = 'cs-bar-label';
      label.textContent = item.label;
      row.appendChild(label);

      var track = document.createElement('div');
      track.className = 'cs-bar-track';

      var bar = document.createElement('div');
      bar.className = 'cs-bar-fill';
      bar.style.background = item.color || 'var(--gold)';
      var pct = (item.value / maxVal) * 100;
      if (animate) {
        bar.style.width = '0%';
        (function (b, p) {
          setTimeout(function () { b.style.width = p + '%'; }, 80 + j * 120);
        })(bar, pct);
      } else {
        bar.style.width = pct + '%';
      }
      track.appendChild(bar);
      row.appendChild(track);

      if (showValue) {
        var val = document.createElement('span');
        val.className = 'cs-bar-value';
        val.textContent = unit + formatNumber(Math.round(item.value)) + suffix;
        row.appendChild(val);
      }

      if (item.sub) {
        var sub = document.createElement('span');
        sub.className = 'cs-bar-sub';
        sub.textContent = item.sub;
        row.appendChild(sub);
      }

      container.appendChild(row);
    }
  }

  /* ── 横棒グラフ（グループ比較） ── */
  /**
   * renderGroupedBarChart(container, categories, series, opts)
   *   categories : ['家賃','食費',...]
   *   series     : [{name, color, values:[...]}]
   *   opts       : {unit?, suffix?}
   */
  function renderGroupedBarChart(container, categories, series, opts) {
    opts = opts || {};
    var unit = opts.unit || '';
    var suffix = opts.suffix || '';

    var maxVal = 0;
    for (var s = 0; s < series.length; s++) {
      for (var v = 0; v < series[s].values.length; v++) {
        if (series[s].values[v] > maxVal) maxVal = series[s].values[v];
      }
    }
    if (maxVal === 0) maxVal = 1;

    container.innerHTML = '';
    container.classList.add('cs-bar-chart', 'cs-bar-chart--grouped');

    // Legend
    var legend = document.createElement('div');
    legend.className = 'cs-bar-legend';
    for (var l = 0; l < series.length; l++) {
      var chip = document.createElement('span');
      chip.className = 'cs-bar-legend-item';
      chip.innerHTML = '<span class="cs-bar-legend-dot" style="background:' + series[l].color + '"></span>' + series[l].name;
      legend.appendChild(chip);
    }
    container.appendChild(legend);

    for (var c = 0; c < categories.length; c++) {
      var group = document.createElement('div');
      group.className = 'cs-bar-group';

      var catLabel = document.createElement('span');
      catLabel.className = 'cs-bar-label';
      catLabel.textContent = categories[c];
      group.appendChild(catLabel);

      for (var si = 0; si < series.length; si++) {
        var row = document.createElement('div');
        row.className = 'cs-bar-row cs-bar-row--grouped';

        var track = document.createElement('div');
        track.className = 'cs-bar-track';

        var bar = document.createElement('div');
        bar.className = 'cs-bar-fill';
        bar.style.background = series[si].color;
        var pct = (series[si].values[c] / maxVal) * 100;
        bar.style.width = '0%';
        (function (b, p, delay) {
          setTimeout(function () { b.style.width = p + '%'; }, delay);
        })(bar, pct, 50 + c * 100 + si * 40);
        track.appendChild(bar);
        row.appendChild(track);

        var val = document.createElement('span');
        val.className = 'cs-bar-value';
        val.textContent = unit + formatNumber(Math.round(series[si].values[c])) + suffix;
        row.appendChild(val);

        group.appendChild(row);
      }
      container.appendChild(group);
    }
  }

  /* ── ハイライトボックス ── */
  function renderHighlight(container, text, sub) {
    container.innerHTML = '';
    container.className = 'cs-highlight';
    container.style.animation = 'toolFadeUp .4s ease both';
    var h = document.createElement('div');
    h.className = 'cs-highlight-value';
    h.textContent = text;
    container.appendChild(h);
    if (sub) {
      var s = document.createElement('div');
      s.className = 'cs-highlight-sub';
      s.textContent = sub;
      container.appendChild(s);
    }
  }

  /* ── 入力値取得ヘルパー ── */
  function getVal(id) {
    var el = document.getElementById(id);
    if (!el) return 0;
    return parseFloat(el.value) || 0;
  }

  function getSelect(id) {
    var el = document.getElementById(id);
    if (!el) return '';
    return el.value;
  }

  return {
    formatNumber: formatNumber,
    formatManen: formatManen,
    formatPercent: formatPercent,
    renderBarChart: renderBarChart,
    renderGroupedBarChart: renderGroupedBarChart,
    renderHighlight: renderHighlight,
    getVal: getVal,
    getSelect: getSelect
  };
})();
