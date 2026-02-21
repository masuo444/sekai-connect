/**
 * Connect-Sekai — ゴールデンビザ診断
 */
(function () {
  'use strict';
  var T = CSTools;

  /* ── ビザプログラム定義 ── */
  var PROGRAMS = [
    {
      id: 'uae-golden-10',
      name: 'UAE ゴールデンビザ（10年）',
      country: 'UAE',
      duration: '10年',
      color: 'var(--gold)',
      criteria: [
        {
          label: '不動産投資 200万AED（約8,000万円）以上',
          check: function (d) { return d.investment >= 8000; }
        },
        {
          label: '事業収入が年間100万AED（約4,000万円）以上、または資産1,000万AED以上',
          check: function (d) { return d.assets >= 40000 || d.income >= 4000; }
        },
        {
          label: '専門職（医師・エンジニア・科学者・芸術家等）',
          check: function (d) { return ['doctor', 'engineer', 'scientist', 'artist', 'executive'].indexOf(d.job) >= 0; }
        },
        {
          label: '博士号または修士号保有者',
          check: function (d) { return d.education === 'phd' || d.education === 'masters'; }
        }
      ],
      minPass: 1
    },
    {
      id: 'uae-green-5',
      name: 'UAE グリーンビザ（5年）',
      country: 'UAE',
      duration: '5年',
      color: '#2ecc71',
      criteria: [
        {
          label: 'フリーランサー・自営業者（年収36万AED ≒ 約1,400万円以上）',
          check: function (d) { return d.job === 'freelance' && d.income >= 1400; }
        },
        {
          label: '熟練労働者（学士号以上＋有効な雇用契約）',
          check: function (d) { return (d.education === 'bachelor' || d.education === 'masters' || d.education === 'phd') && d.job !== 'other'; }
        },
        {
          label: '投資家（会社設立＋資本金50万AED ≒ 約2,000万円以上）',
          check: function (d) { return d.investment >= 2000; }
        }
      ],
      minPass: 1
    },
    {
      id: 'saudi-premium-permanent',
      name: 'サウジ プレミアムレジデンシー（永住）',
      country: 'サウジアラビア',
      duration: '永住',
      color: 'var(--emerald)',
      criteria: [
        {
          label: '不動産投資（サウジ国内に物件所有）',
          check: function (d) { return d.investment >= 3000; }
        },
        {
          label: '高い資産額（目安: 1億円以上）',
          check: function (d) { return d.assets >= 10000; }
        },
        {
          label: '専門的スキルまたは事業経験',
          check: function (d) { return ['doctor', 'engineer', 'scientist', 'executive'].indexOf(d.job) >= 0; }
        }
      ],
      minPass: 2
    },
    {
      id: 'saudi-premium-annual',
      name: 'サウジ プレミアムレジデンシー（年次更新）',
      country: 'サウジアラビア',
      duration: '1年（更新可）',
      color: '#27ae60',
      criteria: [
        {
          label: '有効なパスポートと犯罪歴なし',
          check: function () { return true; } // 基本要件として常にtrue
        },
        {
          label: '年間更新費用 10万SAR（約400万円）の支払い能力',
          check: function (d) { return d.assets >= 400 || d.income >= 400; }
        },
        {
          label: '健康保険への加入',
          check: function () { return true; }
        }
      ],
      minPass: 3
    }
  ];

  /* ── 診断実行 ── */
  function diagnose() {
    var data = {
      assets: T.getVal('visa-assets'),
      income: T.getVal('visa-income'),
      investment: T.getVal('visa-investment'),
      job: T.getSelect('visa-job'),
      education: T.getSelect('visa-education')
    };

    var resultsEl = document.getElementById('visa-results');
    var listEl = document.getElementById('visa-list');
    listEl.innerHTML = '';

    for (var i = 0; i < PROGRAMS.length; i++) {
      var prog = PROGRAMS[i];
      var passed = 0;
      var total = prog.criteria.length;

      var card = document.createElement('div');
      card.className = 'visa-card';

      var header = document.createElement('div');
      header.className = 'visa-card-header';
      header.innerHTML =
        '<span class="visa-card-country" style="border-color:' + prog.color + '">' + prog.country + '</span>' +
        '<h3>' + prog.name + '</h3>' +
        '<span class="visa-card-duration">滞在期間: ' + prog.duration + '</span>';
      card.appendChild(header);

      var checkList = document.createElement('ul');
      checkList.className = 'visa-checklist';

      for (var j = 0; j < prog.criteria.length; j++) {
        var crit = prog.criteria[j];
        var ok = crit.check(data);
        if (ok) passed++;

        var li = document.createElement('li');
        li.className = ok ? 'visa-check-pass' : 'visa-check-fail';
        li.innerHTML = '<span class="visa-check-icon">' + (ok ? '&#10003;' : '&#10007;') + '</span> ' + crit.label;
        checkList.appendChild(li);
      }
      card.appendChild(checkList);

      var eligible = passed >= prog.minPass;
      var status = document.createElement('div');
      status.className = 'visa-status ' + (eligible ? 'visa-status--eligible' : 'visa-status--ineligible');
      status.textContent = eligible ? '適格の可能性が高い' : '条件を満たしていない可能性';
      card.appendChild(status);

      listEl.appendChild(card);
    }

    resultsEl.style.display = 'block';
    resultsEl.style.animation = 'none';
    resultsEl.offsetHeight;
    resultsEl.style.animation = 'toolFadeUp .5s ease both';
  }

  /* ── イベントバインド ── */
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('visa-calc-btn');
    if (btn) btn.addEventListener('click', diagnose);
  });
})();
