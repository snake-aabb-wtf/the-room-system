// v2.2.0 上传队列：并发限流 + 取消 + 失败重试 + 预估剩余 + FIFO 顺序。
// 挂载到 window.UQ；调用 UQ.enqueue(file, room) 即可。
(function () {
  const MAX_CONCURRENT = 3;
  const queue = [];      // 等待中的项 {file, room, id, row}
  const active = new Set(); // 进行中的 xhr
  let _uid = 0;

  function nextId() { return 'uq' + Date.now() + (++_uid); }

  function fmtTime(seconds) {
    if (!isFinite(seconds) || seconds <= 0) return '剩余 --';
    if (seconds < 60) return '剩余 ' + Math.round(seconds) + ' 秒';
    if (seconds < 3600) return '剩余 ' + Math.round(seconds / 60) + ' 分';
    return '剩余 ' + (seconds / 3600).toFixed(1) + ' 时';
  }

  function makeRow(file) {
    const id = nextId();
    const row = document.createElement('div');
    row.className = 'uq-item';
    row.dataset.id = id;
    row.innerHTML =
      '<div class="uq-name">' +
        '<span class="fname"></span>' +
        '<span class="actions" style="display:flex;gap:6px;align-items:center">' +
          '<span class="tiny stat"></span>' +
          '<button class="btn small ghost act-cancel" aria-label="取消上传">×</button>' +
        '</span>' +
      '</div>' +
      '<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">' +
        '<i style="width:0%"></i>' +
      '</div>';
    row.querySelector('.fname').textContent = file.name;
    return row;
  }

  function setProgress(row, pct, statusText) {
    const bar = row.querySelector('.bar');
    const i = bar.querySelector('i');
    i.style.width = pct + '%';
    bar.setAttribute('aria-valuenow', Math.round(pct));
    if (statusText) row.querySelector('.stat').textContent = statusText;
  }

  function setState(row, state) {
    const bar = row.querySelector('.bar');
    bar.classList.remove('ok', 'err');
    if (state === 'ok') bar.classList.add('ok');
    else if (state === 'err') bar.classList.add('err');
  }

  function pump() {
    // 启动等待中的项直到达到并发上限
    while (active.size < MAX_CONCURRENT && queue.length) {
      const item = queue.shift();
      startItem(item);
    }
  }

  function startItem(item) {
    const { file, room, row } = item;
    const xhr = new XMLHttpRequest();
    item.xhr = xhr;
    item.startedAt = Date.now();
    item.lastLoaded = 0;
    item.lastTs = item.startedAt;
    active.add(xhr);

    const fd = new FormData();
    fd.append('file', file);
    fd.append('ttl', window.UPLOAD_TTL || '');

    xhr.upload.onprogress = e => {
      if (!e.lengthComputable) return;
      const pct = e.loaded / e.total * 100;
      const now = Date.now();
      const dt = (now - item.lastTs) / 1000;
      const db = e.loaded - item.lastLoaded;
      const speed = dt > 0 ? db / dt : 0;     // bytes/s
      const remain = speed > 0 ? (e.total - e.loaded) / speed : Infinity;
      const status = Math.round(pct) + '% · ' + fmtTime(remain);
      setProgress(row, pct, status);
      item.lastLoaded = e.loaded;
      item.lastTs = now;
    };
    xhr.onload = () => {
      active.delete(xhr);
      if (xhr.status === 200) {
        try {
          const d = JSON.parse(xhr.responseText);
          setProgress(row, 100, '✓ ' + (d.size_h || ''));
          setState(row, 'ok');
          if (typeof window.onUploadComplete === 'function') window.onUploadComplete(d, file);
          // 成功后 1.5s 自动移除
          setTimeout(() => row.remove(), 1500);
        } catch (e) {
          toError(row, item, '响应异常');
        }
      } else {
        toError(row, item, '失败 ' + xhr.status);
      }
      pump();
    };
    xhr.onerror = () => { active.delete(xhr); toError(row, item, '网络错误'); pump(); };
    xhr.onabort = () => { active.delete(xhr); toCancelled(row); pump(); };

    // 取消按钮
    row.querySelector('.act-cancel').onclick = () => {
      try { xhr.abort(); } catch (e) {}
    };
    // 重试按钮（DOM 上动态加）
    row._retry = () => {
      // 复用原行：清状态，重新入队
      setProgress(row, 0, '重试中…');
      setState(row, '');
      row.querySelector('.stat').textContent = '排队中…';
      row.querySelector('.act-retry')?.remove();
      row.querySelector('.act-cancel').style.display = '';
      queue.push(item);
      pump();
    };

    xhr.open('POST', '/upload/' + room);
    xhr.send(fd);
  }

  function toError(row, item, msg) {
    setProgress(row, 0, msg);
    setState(row, 'err');
    // 显示重试 + 移除
    let actions = row.querySelector('.actions');
    if (!row.querySelector('.act-retry')) {
      const btn = document.createElement('button');
      btn.className = 'btn small ghost act-retry';
      btn.textContent = '↻ 重试';
      btn.setAttribute('aria-label', '重试上传');
      btn.onclick = row._retry;
      actions.insertBefore(btn, actions.querySelector('.act-cancel'));
    }
    row.querySelector('.act-cancel').title = '移除';
    row.querySelector('.act-cancel').onclick = () => row.remove();
  }
  function toCancelled(row) {
    setProgress(row, 0, '已取消');
    setState(row, 'err');
    // 5s 后自动消失，避免积压
    setTimeout(() => row.remove(), 5000);
  }

  // 对外 API
  function enqueue(files, room) {
    if (!files || !files.length) return;
    const host = document.getElementById('queue');
    for (const file of files) {
      const row = makeRow(file);
      host.appendChild(row);  // FIFO：在末尾追加
      const item = { file, room, row };
      queue.push(item);
    }
    pump();
  }

  // 简单 IDB 包装（不引 idb-keyval）：仅存"待恢复"的失败项，方便刷新后看到
  const IDB_NAME = 'room_uploads';
  function idb() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(IDB_NAME, 1);
      req.onupgradeneeded = () => req.result.createObjectStore('failed');
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }
  async function rememberFailed(name, size, room) {
    if (!('indexedDB' in window)) return;
    try {
      const db = await idb();
      const tx = db.transaction('failed', 'readwrite');
      tx.objectStore('failed').put({ name, size, room, ts: Date.now() }, name);
    } catch (e) {}
  }

  window.UQ = { enqueue };
})();
