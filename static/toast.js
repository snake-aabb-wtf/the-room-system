// Toast 通知 + 模态确认/输入。v2.1.0 起全站用此替代 alert/confirm/prompt。
(function () {
  function ensureHost() {
    let h = document.getElementById('toast-host');
    if (!h) {
      h = document.createElement('div');
      h.id = 'toast-host';
      h.className = 'toast-host';
      h.setAttribute('aria-live', 'polite');
      h.setAttribute('aria-atomic', 'true');
      document.body.appendChild(h);
    }
    return h;
  }

  const ICON = { info: 'ℹ️', success: '✅', error: '⚠️' };
  function show(msg, type, ms) {
    type = type || 'info';
    ms = ms == null ? 3000 : ms;
    const host = ensureHost();
    const t = document.createElement('div');
    t.className = 'toast ' + type;
    t.setAttribute('role', type === 'error' ? 'alert' : 'status');
    t.innerHTML =
      '<span class="ico" aria-hidden="true">' + (ICON[type] || '') + '</span>' +
      '<span class="msg"></span>' +
      '<button class="x" aria-label="关闭通知">×</button>';
    t.querySelector('.msg').textContent = msg;
    const close = () => {
      t.style.animation = 'toast-out .2s ease-in forwards';
      setTimeout(() => t.remove(), 200);
    };
    t.querySelector('.x').onclick = close;
    host.appendChild(t);
    if (ms > 0) setTimeout(close, ms);
  }

  window.toast = {
    info: (m, ms) => show(m, 'info', ms),
    success: (m, ms) => show(m, 'success', ms),
    error: (m, ms) => show(m, 'error', ms || 5000),
  };

  // 模态确认框：resolve(true/false)。参数 {title, body, confirmText, cancelText, danger}
  window.modalConfirm = function (opts) {
    return new Promise((resolve) => {
      const m = document.createElement('div');
      m.className = 'modal-confirm show';
      m.setAttribute('role', 'dialog');
      m.setAttribute('aria-modal', 'true');
      m.innerHTML =
        '<div class="box" role="document">' +
        '<h3 id="mc-title"></h3>' +
        '<p id="mc-body"></p>' +
        '<div class="actions">' +
        '<button class="btn sec" data-act="cancel"></button>' +
        '<button class="btn" data-act="ok"></button>' +
        '</div></div>';
      m.querySelector('#mc-title').textContent = opts.title || '确认';
      m.querySelector('#mc-body').textContent = opts.body || '';
      const cancelBtn = m.querySelector('[data-act="cancel"]');
      const okBtn = m.querySelector('[data-act="ok"]');
      cancelBtn.textContent = opts.cancelText || '取消';
      okBtn.textContent = opts.confirmText || '确定';
      if (opts.danger) okBtn.classList.add('danger');
      const done = (v) => { m.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
      const onKey = (e) => {
        if (e.key === 'Escape') done(false);
        else if (e.key === 'Enter') done(true);
      };
      cancelBtn.onclick = () => done(false);
      okBtn.onclick = () => done(true);
      m.addEventListener('click', (e) => { if (e.target === m) done(false); });
      document.addEventListener('keydown', onKey);
      document.body.appendChild(m);
      setTimeout(() => okBtn.focus(), 30);
    });
  };

  // 模态输入框：resolve(string|null)。参数 {title, label, defaultValue, confirmText}
  window.modalPrompt = function (opts) {
    return new Promise((resolve) => {
      const m = document.createElement('div');
      m.className = 'modal-confirm show';
      m.setAttribute('role', 'dialog');
      m.setAttribute('aria-modal', 'true');
      m.innerHTML =
        '<div class="box" role="document">' +
        '<h3 id="mp-title"></h3>' +
        '<p id="mp-body" style="margin-bottom:10px"></p>' +
        '<input id="mp-input" />' +
        '<div class="actions">' +
        '<button class="btn sec" data-act="cancel"></button>' +
        '<button class="btn" data-act="ok"></button>' +
        '</div></div>';
      m.querySelector('#mp-title').textContent = opts.title || '输入';
      m.querySelector('#mp-body').textContent = opts.label || '';
      const input = m.querySelector('#mp-input');
      input.value = opts.defaultValue || '';
      m.querySelector('[data-act="cancel"]').textContent = '取消';
      m.querySelector('[data-act="ok"]').textContent = opts.confirmText || '确定';
      const done = (v) => { m.remove(); document.removeEventListener('keydown', onKey); resolve(v); };
      const onKey = (e) => {
        if (e.key === 'Escape') done(null);
        else if (e.key === 'Enter') done(input.value.trim());
      };
      m.querySelector('[data-act="cancel"]').onclick = () => done(null);
      m.querySelector('[data-act="ok"]').onclick = () => done(input.value.trim());
      m.addEventListener('click', (e) => { if (e.target === m) done(null); });
      document.addEventListener('keydown', onKey);
      document.body.appendChild(m);
      setTimeout(() => { input.focus(); input.select(); }, 30);
    });
  };
})();
