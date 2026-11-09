/* datepicker.js — 即時監控與交叉分析共用的日期選擇器
 * 日期顏色：正黑 = 當天 6 個檔期資料完整；淡灰 = 當天無資料或有檔期缺漏（含只剩商品明細的檔期）
 * 用法：
 *   MomoDates.build(allRows, listingRows)   // 依資料計算每天的狀態，載入資料後呼叫
 *   MomoDates.attach(inputEl)               // 把 <input class="q-date"> 換成自製日曆；value 維持 YYYY-MM-DD，選日期會觸發 change
 *   MomoDates.info('2026/11/08')            // { gray, missing:[...], listing:[...] }
 */
(function () {
  const SLOTS = ['00:00', '07:00', '11:00', '14:00', '18:00', '22:00'];
  const SLOT_END = { '00:00': 7, '07:00': 11, '11:00': 14, '14:00': 18, '18:00': 22, '22:00': 24 };
  let status = {};      // 'YYYY/MM/DD' -> { gray, missing, listing }
  let minDate = '', maxDate = '';
  const inputs = [];

  const pad = n => String(n).padStart(2, '0');
  const fmt = d => `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())}`;
  const parse = s => { const p = (s || '').split(/[\/-]/).map(Number); return p.length === 3 && !p.some(isNaN) ? new Date(p[0], p[1] - 1, p[2]) : null; };

  function build(rows, listingRows) {
    status = {};
    const have = {}, listing = {};
    (rows || []).forEach(r => { if (r.date && r.slot) (have[r.date] = have[r.date] || new Set()).add(r.slot); });
    (listingRows || []).forEach(r => { if (r.date && r.slot) (listing[r.date] = listing[r.date] || new Set()).add(r.slot); });
    const dates = Object.keys(have).concat(Object.keys(listing)).sort();
    if (!dates.length) return;
    const now = new Date();
    const today = fmt(now);
    minDate = dates[0];
    maxDate = today;
    for (let d = parse(minDate); fmt(d) <= today; d.setDate(d.getDate() + 1)) {
      const key = fmt(d);
      // 今天：只檢查已經結束的檔期
      const expected = key < today ? SLOTS : SLOTS.filter(s => now.getHours() >= SLOT_END[s]);
      const h = have[key] || new Set(), l = listing[key] || new Set();
      const missing = expected.filter(s => !h.has(s) && !l.has(s));
      const lst = SLOTS.filter(s => l.has(s) && !h.has(s));
      status[key] = { gray: missing.length > 0 || lst.length > 0, missing, listing: lst };
    }
    inputs.forEach(refreshInput);
  }

  function info(dateStr) {
    const key = (dateStr || '').replace(/-/g, '/');
    if (key < minDate || key > maxDate) return { gray: true, missing: [], listing: [], outOfRange: true };
    return status[key] || { gray: true, missing: SLOTS.slice(), listing: [] };
  }

  function describe(dateStr) {
    const s = info(dateStr);
    if (s.outOfRange) return '不在資料範圍內';
    const parts = [];
    if (s.missing.length === 6) return '整天無資料';
    if (s.missing.length) parts.push('無資料：' + s.missing.join('、'));
    if (s.listing.length) parts.push('僅商品明細：' + s.listing.join('、'));
    return parts.length ? parts.join('；') : '資料完整';
  }

  // ── 樣式 ──
  const css = `
  .mdp-wrap{position:relative;display:inline-block;}
  .q-date.mdp-input{width:118px;cursor:pointer;}
  .q-date.mdp-input.mdp-gray{color:#b8bec7;}
  .mdp-pop{position:absolute;top:calc(100% + 6px);left:0;z-index:1000;background:#fff;border:1px solid #cbd5e1;border-radius:10px;
    box-shadow:0 8px 24px rgba(15,23,42,.14);padding:10px;width:252px;font-family:inherit;display:none;}
  .mdp-pop.open{display:block;}
  .mdp-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;font-weight:700;font-size:13px;color:#000;}
  .mdp-nav{border:none;background:transparent;font-size:16px;cursor:pointer;padding:2px 8px;border-radius:6px;color:#475569;}
  .mdp-nav:hover{background:#f1f5f9;} .mdp-nav:disabled{opacity:.25;cursor:default;background:transparent;}
  .mdp-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;}
  .mdp-wd{font-size:11px;color:#94a3b8;text-align:center;padding:3px 0;}
  .mdp-day{font-size:13px;text-align:center;padding:6px 0;border-radius:6px;cursor:pointer;color:#000;font-weight:600;border:none;background:transparent;font-family:inherit;}
  .mdp-day:hover{background:#eff6ff;}
  .mdp-day.gray{color:#c3c9d1;font-weight:400;}
  .mdp-day.off{color:#e5e7eb;font-weight:400;cursor:default;background:transparent;}
  .mdp-day.sel{background:#2563eb;color:#fff;}
  .mdp-day.sel.gray{background:#cbd5e1;color:#fff;}
  .mdp-day.today{box-shadow:inset 0 0 0 1px #93c5fd;}
  .mdp-legend{margin-top:8px;padding-top:7px;border-top:1px solid #e2e8f0;font-size:11px;color:#64748b;line-height:1.7;}
  .mdp-legend b{color:#000;} .mdp-legend i{font-style:normal;color:#b8bec7;font-weight:700;}
  .mdp-hint{font-size:11px;color:#64748b;min-height:16px;margin-top:4px;}
  @media (max-width:480px){ .mdp-pop{position:fixed;left:50%;top:80px;transform:translateX(-50%);} }`;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  function refreshInput(el) {
    if (!el.value) { el.classList.remove('mdp-gray'); el.title = ''; return; }
    el.classList.toggle('mdp-gray', info(el.value).gray);
    el.title = describe(el.value);
  }

  function attach(el) {
    if (el._mdp) return;
    el._mdp = true;
    el.type = 'text';
    el.readOnly = true;
    el.classList.add('mdp-input');
    el.placeholder = 'YYYY-MM-DD';
    const wrap = document.createElement('span');
    wrap.className = 'mdp-wrap';
    el.parentNode.insertBefore(wrap, el);
    wrap.appendChild(el);
    const pop = document.createElement('div');
    pop.className = 'mdp-pop';
    wrap.appendChild(pop);
    let view = null;   // 顯示中的月份（Date，1 號）

    // 程式改 value 時也要更新顏色
    const desc = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
    Object.defineProperty(el, 'value', {
      get() { return desc.get.call(this); },
      set(v) { desc.set.call(this, v); refreshInput(this); }
    });

    function render() {
      const y = view.getFullYear(), m = view.getMonth();
      const first = new Date(y, m, 1).getDay();
      const days = new Date(y, m + 1, 0).getDate();
      const sel = (el.value || '').replace(/-/g, '/');
      const today = fmt(new Date());
      const minM = minDate ? minDate.slice(0, 7) : '', maxM = maxDate ? maxDate.slice(0, 7) : '';
      const curM = `${y}/${pad(m + 1)}`;
      let h = `<div class="mdp-head"><button type="button" class="mdp-nav" data-nav="-1" ${minM && curM <= minM ? 'disabled' : ''}>‹</button>
        ${y} 年 ${m + 1} 月<button type="button" class="mdp-nav" data-nav="1" ${maxM && curM >= maxM ? 'disabled' : ''}>›</button></div><div class="mdp-grid">`;
      '日一二三四五六'.split('').forEach(w => h += `<div class="mdp-wd">${w}</div>`);
      for (let i = 0; i < first; i++) h += '<div></div>';
      for (let d = 1; d <= days; d++) {
        const key = `${y}/${pad(m + 1)}/${pad(d)}`;
        const s = info(key);
        const cls = ['mdp-day', s.outOfRange ? 'off' : (s.gray ? 'gray' : ''), key === sel ? 'sel' : '', key === today ? 'today' : ''].join(' ');
        h += s.outOfRange ? `<div class="${cls}">${d}</div>`
          : `<button type="button" class="${cls}" data-d="${key}" title="${describe(key)}">${d}</button>`;
      }
      h += `</div><div class="mdp-hint"></div><div class="mdp-legend"><b>黑色</b>：資料完整　<i>淡灰</i>：無資料或有缺漏</div>`;
      pop.innerHTML = h;
    }

    function open() {
      const v = parse(el.value) || parse(maxDate) || new Date();
      view = new Date(v.getFullYear(), v.getMonth(), 1);
      render();
      document.querySelectorAll('.mdp-pop.open').forEach(p => p !== pop && p.classList.remove('open'));
      pop.classList.add('open');
    }
    el.addEventListener('click', () => pop.classList.contains('open') ? pop.classList.remove('open') : open());
    pop.addEventListener('mouseover', e => {
      const b = e.target.closest('[data-d]');
      pop.querySelector('.mdp-hint').textContent = b ? `${b.dataset.d}：${describe(b.dataset.d)}` : '';
    });
    pop.addEventListener('click', e => {
      e.stopPropagation();
      const nav = e.target.closest('[data-nav]');
      if (nav) { view.setMonth(view.getMonth() + Number(nav.dataset.nav)); render(); return; }
      const b = e.target.closest('[data-d]');
      if (!b) return;
      el.value = b.dataset.d.replace(/\//g, '-');
      pop.classList.remove('open');
      el.dispatchEvent(new Event('change', { bubbles: true }));
    });
    document.addEventListener('click', e => { if (!wrap.contains(e.target)) pop.classList.remove('open'); });
    inputs.push(el);
    refreshInput(el);
  }

  window.MomoDates = { build, attach, info, describe, SLOTS };
})();
