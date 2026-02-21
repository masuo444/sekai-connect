/**
 * Connect-Sekai — 生活コスト比較
 */
(function () {
  'use strict';
  var T = CSTools;

  /* ── カテゴリ定義 ── */
  var CATEGORIES = [
    { key: 'rent1br', label: '家賃（1BR）' },
    { key: 'rent3br', label: '家賃（3BR）' },
    { key: 'food', label: '食費' },
    { key: 'transport', label: '交通費' },
    { key: 'education', label: '教育費' },
    { key: 'health', label: '医療費' },
    { key: 'utilities', label: '光熱費' },
    { key: 'leisure', label: '娯楽費' }
  ];

  /* ── 都市データ (月額・万円) ── */
  /* ティア: standard / comfort / luxury */
  var DATA = {
    tokyo: {
      name: '東京',
      color: '#BC002D',
      standard:  { rent1br: 10, rent3br: 22, food: 5,  transport: 1.5, education: 0,  health: 1.5, utilities: 1.5, leisure: 3 },
      comfort:   { rent1br: 18, rent3br: 40, food: 8,  transport: 2,   education: 5,  health: 2,   utilities: 2,   leisure: 5 },
      luxury:    { rent1br: 35, rent3br: 80, food: 15, transport: 5,   education: 15, health: 3,   utilities: 3,   leisure: 15 }
    },
    dubai: {
      name: 'ドバイ',
      color: 'var(--gold)',
      standard:  { rent1br: 12, rent3br: 28, food: 6,  transport: 2,   education: 0,  health: 2,   utilities: 2,   leisure: 4 },
      comfort:   { rent1br: 25, rent3br: 55, food: 10, transport: 3,   education: 10, health: 3,   utilities: 3,   leisure: 8 },
      luxury:    { rent1br: 60, rent3br: 120,food: 20, transport: 8,   education: 25, health: 5,   utilities: 4,   leisure: 25 }
    },
    riyadh: {
      name: 'リヤド',
      color: 'var(--emerald)',
      standard:  { rent1br: 6,  rent3br: 15, food: 4,  transport: 1.5, education: 0,  health: 1,   utilities: 1.5, leisure: 2 },
      comfort:   { rent1br: 12, rent3br: 30, food: 7,  transport: 2.5, education: 8,  health: 2,   utilities: 2,   leisure: 5 },
      luxury:    { rent1br: 30, rent3br: 65, food: 15, transport: 6,   education: 20, health: 4,   utilities: 3,   leisure: 15 }
    }
  };

  /* ── 比較実行 ── */
  function compare() {
    var tier = T.getSelect('col-tier');
    if (!tier) tier = 'comfort';

    var cities = ['tokyo', 'dubai', 'riyadh'];
    var catLabels = CATEGORIES.map(function (c) { return c.label; });

    var series = [];
    var totals = {};

    for (var i = 0; i < cities.length; i++) {
      var city = DATA[cities[i]];
      var tierData = city[tier];
      var values = [];
      var total = 0;

      for (var j = 0; j < CATEGORIES.length; j++) {
        var val = tierData[CATEGORIES[j].key] || 0;
        values.push(val);
        total += val;
      }

      series.push({
        name: city.name,
        color: city.color,
        values: values
      });
      totals[cities[i]] = total;
    }

    // グループバーチャート
    var chartEl = document.getElementById('col-chart');
    T.renderGroupedBarChart(chartEl, catLabels, series, { suffix: '万円' });

    // 合計比較
    var totalEl = document.getElementById('col-totals');
    var totalData = cities.map(function (key) {
      return { label: DATA[key].name, value: totals[key], color: DATA[key].color };
    });
    T.renderBarChart(totalEl, totalData, { suffix: '万円/月' });

    // ハイライト
    var hlEl = document.getElementById('col-highlight');
    var tierLabel = tier === 'standard' ? 'スタンダード' : (tier === 'comfort' ? 'コンフォート' : 'ラグジュアリー');
    var cheapest = cities.reduce(function (a, b) { return totals[a] < totals[b] ? a : b; });
    var most = cities.reduce(function (a, b) { return totals[a] > totals[b] ? a : b; });
    var diff = totals[most] - totals[cheapest];

    T.renderHighlight(hlEl,
      DATA[cheapest].name + ' が最安 (' + T.formatManen(totals[cheapest]) + '/月)',
      tierLabel + '水準で ' + DATA[most].name + ' より月 ' + T.formatManen(diff) + ' 安い'
    );

    // 詳細テーブル
    var detailEl = document.getElementById('col-detail');
    var rows = CATEGORIES.map(function (cat) {
      return '<tr><td>' + cat.label + '</td>' +
        cities.map(function (key) {
          return '<td>' + T.formatManen(DATA[key][tier][cat.key]) + '</td>';
        }).join('') + '</tr>';
    }).join('');

    detailEl.innerHTML =
      '<table class="tool-table">' +
      '<thead><tr><th>カテゴリ</th>' + cities.map(function (k) { return '<th>' + DATA[k].name + '</th>'; }).join('') + '</tr></thead>' +
      '<tbody>' + rows +
      '<tr class="tool-table-total"><td>月額合計</td>' + cities.map(function (k) { return '<td>' + T.formatManen(totals[k]) + '</td>'; }).join('') + '</tr>' +
      '<tr class="tool-table-highlight"><td>年間合計</td>' + cities.map(function (k) { return '<td>' + T.formatManen(totals[k] * 12) + '</td>'; }).join('') + '</tr>' +
      '</tbody></table>';

    var colPanel = document.getElementById('col-results');
    colPanel.style.display = 'block';
    colPanel.style.animation = 'none';
    colPanel.offsetHeight;
    colPanel.style.animation = 'toolFadeUp .5s ease both';
  }

  /* ── イベントバインド ── */
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('col-calc-btn');
    if (btn) btn.addEventListener('click', compare);

    // ティアボタン
    var tierBtns = document.querySelectorAll('[data-tier]');
    for (var i = 0; i < tierBtns.length; i++) {
      tierBtns[i].addEventListener('click', function () {
        // すべてのティアボタンの active を外す
        for (var j = 0; j < tierBtns.length; j++) tierBtns[j].classList.remove('active');
        this.classList.add('active');
        document.getElementById('col-tier').value = this.getAttribute('data-tier');
        compare();
      });
    }
  });
})();
