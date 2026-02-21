/**
 * Connect-Sekai — 税金シミュレーター
 */
(function () {
  'use strict';
  var T = CSTools;

  /* ── 日本の累進課税率テーブル（2024年） ── */
  var JP_BRACKETS = [
    { limit: 195,  rate: 0.05, deduction: 0 },
    { limit: 330,  rate: 0.10, deduction: 9.75 },
    { limit: 695,  rate: 0.20, deduction: 42.75 },
    { limit: 900,  rate: 0.23, deduction: 63.6 },
    { limit: 1800, rate: 0.33, deduction: 153.6 },
    { limit: 4000, rate: 0.40, deduction: 279.6 },
    { limit: Infinity, rate: 0.45, deduction: 479.6 }
  ];

  /* 日本の所得税計算（万円） */
  function calcJPIncomeTax(income) {
    for (var i = 0; i < JP_BRACKETS.length; i++) {
      if (income <= JP_BRACKETS[i].limit) {
        return income * JP_BRACKETS[i].rate - JP_BRACKETS[i].deduction;
      }
    }
    return 0;
  }

  /* 給与所得控除（万円） */
  function salaryDeduction(income) {
    if (income <= 162.5) return 55;
    if (income <= 180) return income * 0.4 - 10;
    if (income <= 360) return income * 0.3 + 8;
    if (income <= 660) return income * 0.2 + 44;
    if (income <= 850) return income * 0.1 + 110;
    return 195; // 上限
  }

  /* 日本の税金・社保の合計計算（万円単位） */
  function calcJapanTotal(income, type, family) {
    var taxableIncome = income;

    // 給与所得控除
    if (type === 'salary') {
      taxableIncome = income - salaryDeduction(income);
    }

    // 基礎控除 48万円
    taxableIncome -= 48;

    // 配偶者控除
    if (family === 'married' || family === 'family') {
      taxableIncome -= 38;
    }

    if (taxableIncome < 0) taxableIncome = 0;

    var incomeTax = calcJPIncomeTax(taxableIncome);
    var復興税 = incomeTax * 0.021;
    var住民税 = taxableIncome * 0.10;
    var社保 = income * 0.15; // 概算15%

    return {
      incomeTax: Math.max(0, incomeTax),
      surtax: Math.max(0, 復興税),
      resident: Math.max(0, 住民税),
      social: Math.max(0, 社保),
      total: Math.max(0, incomeTax + 復興税 + 住民税 + 社保)
    };
  }

  /* UAE税金計算 */
  function calcUAETotal(income, type) {
    // 個人所得税 0%、VAT 5%（生活コストに反映）
    // 法人税 9%（課税所得37.5万AED超のみ、事業所得の場合）
    var corpTax = 0;
    if (type === 'business') {
      // 事業所得の場合、法人税 9%（簡易計算）
      // 37.5万AED ≒ 約1,500万円 の免税枠
      var taxable = income - 1500;
      if (taxable > 0) corpTax = taxable * 0.09;
    }
    return {
      incomeTax: 0,
      corpTax: corpTax,
      social: 0,
      total: Math.max(0, corpTax)
    };
  }

  /* サウジアラビア税金計算 */
  function calcSaudiTotal(income, type) {
    // 個人所得税 0%（サウジ国民・外国人とも）
    // 外国法人に20%法人税（内国法人はザカート2.5%）
    var corpTax = 0;
    if (type === 'business') {
      corpTax = income * 0.20; // 外国人事業者として
    }
    return {
      incomeTax: 0,
      corpTax: corpTax,
      social: 0,
      total: Math.max(0, corpTax)
    };
  }

  /* メイン計算関数 */
  function calculate() {
    var income = T.getVal('tax-income');
    var type = T.getSelect('tax-type');
    var family = T.getSelect('tax-family');

    if (income <= 0) return;

    var jp = calcJapanTotal(income, type, family);
    var uae = calcUAETotal(income, type);
    var sa = calcSaudiTotal(income, type);

    // 手取り計算
    var jpNet = income - jp.total;
    var uaeNet = income - uae.total;
    var saNet = income - sa.total;

    // 節税額
    var savingsUAE = jp.total - uae.total;
    var savingsSA = jp.total - sa.total;
    var maxSavings = Math.max(savingsUAE, savingsSA);

    // バーチャート: 税金比較
    var chartEl = document.getElementById('tax-chart');
    T.renderBarChart(chartEl, [
      { label: '日本', value: jp.total, color: '#BC002D' },
      { label: 'UAE', value: uae.total, color: 'var(--gold)' },
      { label: 'サウジ', value: sa.total, color: 'var(--emerald)' }
    ], { suffix: '万円', maxValue: jp.total > 0 ? jp.total * 1.1 : income * 0.5 });

    // ハイライト
    var hlEl = document.getElementById('tax-highlight');
    if (maxSavings > 0) {
      var bestCountry = savingsUAE >= savingsSA ? 'UAE' : 'サウジアラビア';
      T.renderHighlight(hlEl,
        '年間 ' + T.formatManen(maxSavings) + ' の節税',
        bestCountry + 'に移住した場合の推定節税額'
      );
    } else {
      hlEl.innerHTML = '';
    }

    // 詳細テーブル
    var detailEl = document.getElementById('tax-detail');
    detailEl.innerHTML =
      '<table class="tool-table">' +
      '<thead><tr><th>項目</th><th>日本</th><th>UAE</th><th>サウジ</th></tr></thead>' +
      '<tbody>' +
      '<tr><td>所得税</td><td>' + T.formatManen(jp.incomeTax) + '</td><td>0万円</td><td>0万円</td></tr>' +
      '<tr><td>住民税</td><td>' + T.formatManen(jp.resident) + '</td><td>—</td><td>—</td></tr>' +
      '<tr><td>社会保険料</td><td>' + T.formatManen(jp.social) + '</td><td>—</td><td>—</td></tr>' +
      '<tr><td>復興特別所得税</td><td>' + T.formatManen(jp.surtax) + '</td><td>—</td><td>—</td></tr>' +
      (type === 'business' ? '<tr><td>法人税（事業所得）</td><td>—</td><td>' + T.formatManen(uae.corpTax) + '</td><td>' + T.formatManen(sa.corpTax) + '</td></tr>' : '') +
      '<tr class="tool-table-total"><td>税負担合計</td><td>' + T.formatManen(jp.total) + '</td><td>' + T.formatManen(uae.total) + '</td><td>' + T.formatManen(sa.total) + '</td></tr>' +
      '<tr class="tool-table-highlight"><td>手取り（税引後）</td><td>' + T.formatManen(jpNet) + '</td><td>' + T.formatManen(uaeNet) + '</td><td>' + T.formatManen(saNet) + '</td></tr>' +
      '</tbody></table>';

    var resultsPanel = document.getElementById('tax-results');
    resultsPanel.style.display = 'block';
    resultsPanel.style.animation = 'none';
    resultsPanel.offsetHeight; // force reflow
    resultsPanel.style.animation = 'toolFadeUp .5s ease both';
  }

  /* ── イベントバインド ── */
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('tax-calc-btn');
    if (btn) btn.addEventListener('click', calculate);

    // Enter キーでも計算
    var form = document.getElementById('tax-form');
    if (form) {
      form.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); calculate(); }
      });
    }
  });
})();
