/**
 * Connect-Sekai — 不動産ROI計算機
 */
(function () {
  'use strict';
  var T = CSTools;

  /* ── プリセット ── */
  var PRESETS = {
    dubai: {
      label: 'ドバイ標準',
      price: 5000,
      yield: 6.5,
      mgmt: 3,
      vacancy: 5,
      costs: 7,
      appreciation: 5
    },
    tokyo: {
      label: '東京標準',
      price: 8000,
      yield: 3.8,
      mgmt: 5,
      vacancy: 3,
      costs: 10,
      appreciation: 2
    }
  };

  function applyPreset(key) {
    var p = PRESETS[key];
    if (!p) return;
    document.getElementById('re-price').value = p.price;
    document.getElementById('re-yield').value = p.yield;
    document.getElementById('re-mgmt').value = p.mgmt;
    document.getElementById('re-vacancy').value = p.vacancy;
    document.getElementById('re-costs').value = p.costs;
    document.getElementById('re-appreciation').value = p.appreciation;
  }

  /* ── 計算 ── */
  function calculate() {
    var price = T.getVal('re-price');        // 万円
    var grossYield = T.getVal('re-yield');    // %
    var mgmtRate = T.getVal('re-mgmt');      // %
    var vacancyRate = T.getVal('re-vacancy'); // %
    var purchaseCosts = T.getVal('re-costs'); // %
    var appreciation = T.getVal('re-appreciation'); // %/年

    if (price <= 0) return;

    // 年間家賃収入（満室時）
    var grossRent = price * (grossYield / 100);
    // 空室控除後
    var effectiveRent = grossRent * (1 - vacancyRate / 100);
    // 管理費
    var mgmtCost = effectiveRent * (mgmtRate / 100);
    // NOI (純営業収入)
    var noi = effectiveRent - mgmtCost;
    // 購入諸費用
    var totalInvestment = price * (1 + purchaseCosts / 100);
    // 月間キャッシュフロー
    var monthlyCF = noi / 12;
    // キャップレート
    var capRate = (noi / price) * 100;
    // 年間ROI（諸費用込み）
    var annualROI = (noi / totalInvestment) * 100;

    // 5年・10年資産推移
    var projections = [];
    for (var y = 0; y <= 10; y++) {
      var propertyValue = price * Math.pow(1 + appreciation / 100, y);
      var cumulativeRent = noi * y;
      var totalAsset = propertyValue + cumulativeRent;
      projections.push({
        year: y,
        propertyValue: propertyValue,
        cumulativeRent: cumulativeRent,
        totalAsset: totalAsset,
        gain: totalAsset - totalInvestment
      });
    }

    // ── 結果表示 ── //

    // KPI カード
    var kpiEl = document.getElementById('re-kpis');
    kpiEl.innerHTML =
      '<div class="tool-kpi-grid">' +
      '<div class="tool-kpi"><div class="tool-kpi-label">月間キャッシュフロー</div><div class="tool-kpi-value">' + T.formatManen(monthlyCF) + '</div></div>' +
      '<div class="tool-kpi"><div class="tool-kpi-label">年間ROI</div><div class="tool-kpi-value">' + T.formatPercent(annualROI) + '</div></div>' +
      '<div class="tool-kpi"><div class="tool-kpi-label">キャップレート</div><div class="tool-kpi-value">' + T.formatPercent(capRate) + '</div></div>' +
      '<div class="tool-kpi"><div class="tool-kpi-label">年間NOI</div><div class="tool-kpi-value">' + T.formatManen(noi) + '</div></div>' +
      '</div>';

    // 資産推移チャート
    var chartEl = document.getElementById('re-chart');
    var chartData = [];
    var years = [0, 1, 3, 5, 7, 10];
    for (var i = 0; i < years.length; i++) {
      var p = projections[years[i]];
      chartData.push({
        label: p.year + '年目',
        value: p.totalAsset,
        color: p.gain >= 0 ? 'var(--gold)' : '#BC002D',
        sub: '(損益: ' + (p.gain >= 0 ? '+' : '') + T.formatManen(p.gain) + ')'
      });
    }
    T.renderBarChart(chartEl, chartData, { suffix: '万円' });

    // 詳細テーブル
    var detailEl = document.getElementById('re-detail');
    detailEl.innerHTML =
      '<table class="tool-table">' +
      '<thead><tr><th>年</th><th>物件価値</th><th>累計家賃収入</th><th>総資産</th><th>損益</th></tr></thead>' +
      '<tbody>' +
      projections.filter(function (p) { return [0, 1, 2, 3, 5, 7, 10].indexOf(p.year) >= 0; }).map(function (p) {
        return '<tr><td>' + p.year + '年</td><td>' + T.formatManen(p.propertyValue) + '</td><td>' + T.formatManen(p.cumulativeRent) + '</td><td>' + T.formatManen(p.totalAsset) + '</td><td class="' + (p.gain >= 0 ? 'text-positive' : 'text-negative') + '">' + (p.gain >= 0 ? '+' : '') + T.formatManen(p.gain) + '</td></tr>';
      }).join('') +
      '</tbody></table>';

    var resPanel = document.getElementById('re-results');
    resPanel.style.display = 'block';
    resPanel.style.animation = 'none';
    resPanel.offsetHeight;
    resPanel.style.animation = 'toolFadeUp .5s ease both';
  }

  /* ── イベントバインド ── */
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('re-calc-btn');
    if (btn) btn.addEventListener('click', calculate);

    // プリセットボタン
    var presetBtns = document.querySelectorAll('[data-preset]');
    for (var i = 0; i < presetBtns.length; i++) {
      presetBtns[i].addEventListener('click', function () {
        applyPreset(this.getAttribute('data-preset'));
      });
    }
  });
})();
