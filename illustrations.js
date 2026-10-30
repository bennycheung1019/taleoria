/* Images decorate existing game surfaces; never add a second story panel. */
(() => {
  'use strict';
  const node = (tag, cls = '', text = '') => {const n = document.createElement(tag); n.className = cls; n.textContent = text; return n;};
  const current = () => typeof state !== 'undefined' ? state : null;
  const scopeOf = s => (s?.session_id || '') + ':' + (s?.campaign_id || '');
  const token = () => ({'X-RPG-Token': window.RPG_TOKEN, 'X-RPG-Session': current()?.session_id || ''});
  const working = row => ['queued', 'translating', 'generating'].includes(row.status);
  let snapshot, scope = '', signature = '', polling = false, sending = false, viewerTarget, paintVersion = 0, needsPaint = true, lastBusy = '';
  const urls = new Map(), downloads = new Map(), controls = new WeakMap();
  const announcement = node('p', 'sr-only'); announcement.setAttribute('role', 'status'); announcement.setAttribute('aria-live', 'polite');
  document.body.append(announcement);

  function icon(kind) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
    const paths = kind === 'generate'
      ? ['M12 3l2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3L12 3Z', 'M20 3v4M18 5h4']
      : ['M3 4h18v16H3z', 'M3 16l5-5 4 4 3-3 6 6', 'M16 8h.01'];
    for (const d of paths) {const p = document.createElementNS(svg.namespaceURI, 'path'); p.setAttribute('d', d); svg.append(p);}
    return svg;
  }
  function imageButton(kind, label) {
    const button = node('button', 'media-button media-' + kind); button.type = 'button';
    button.append(icon(kind)); button.title = label; button.setAttribute('aria-label', label); return button;
  }
  async function json(path, body) {
    const response = await (window.TaleoriaConnection?.fetch||fetch)(path, {method: body ? 'POST' : 'GET', headers: {...token(), 'Content-Type': 'application/json'},
      body: body ? JSON.stringify({...body, session_id: current()?.session_id || ''}) : undefined});
    const data = await response.json(); if (!response.ok) throw Error(data.error || '圖片暫時無法讀取。'); return data;
  }
  function subject(target) {
    if (!snapshot || scope !== scopeOf(current())) return null;
    if (target.kind === 'scene') return target.subject === snapshot.scene.subject ? snapshot.scene : null;
    return (target.kind === 'portrait' ? snapshot.characters : snapshot.items || []).find(p => p.id === target.subject);
  }
  function rowsFor(target) {
    const info = subject(target);
    return info ? snapshot.images.filter(r => r.kind === target.kind && r.subject === target.subject && r.fingerprint === info.fingerprint) : [];
  }
  const completed = target => rowsFor(target).find(r => r.status === 'done');
  function statusFor(target) {
    const rows = rowsFor(target), job = rows.find(working);
    if (job) return {queued:'已排隊，等待文字工作完成…', translating:'正在整理畫面描述…', generating:'正在繪製圖片…'}[job.status];
    if (rows[0]?.status === 'error') return rows[0].error;
    return completed(target) ? '圖片已保存，可點開檢視' : '尚未生成圖片';
  }
  function report(message) {announcement.textContent = message; if (typeof notify === 'function') notify(message);}
  async function urlFor(row, capturedScope) {
    if (urls.has(row.id)) return urls.get(row.id);
    if (!downloads.has(row.id)) {
      const request = (async () => {
        const response = await (window.TaleoriaConnection?.fetch||fetch)(row.url, {headers: token()});
        if (!response.ok) throw Error('圖片無法讀取，請重新整理後再試。');
        const blob = await response.blob();
        if (scope !== capturedScope || scopeOf(current()) !== capturedScope) return null;
        const url = URL.createObjectURL(blob); urls.set(row.id, url); return url;
      })();
      downloads.set(row.id, request);
      request.finally(() => {if (downloads.get(row.id) === request) downloads.delete(row.id);}).catch(() => {});
    }
    return downloads.get(row.id);
  }
  function clearPicture(holder) {
    holder.classList.remove('illustration-filled'); delete holder.dataset.illustrationId;
    holder.querySelector('img.illustration-cover')?.remove();
  }
  async function decorate(holder, target, version) {
    const row = completed(target);
    if (!row) {clearPicture(holder); return;}
    if (holder.dataset.illustrationId === row.id) return;
    const capturedScope = scope, src = await urlFor(row, capturedScope);
    if (!src || capturedScope !== scope || version !== paintVersion || !holder.isConnected || completed(target)?.id !== row.id) return;
    clearPicture(holder);
    const image = node('img', 'illustration-cover'); image.alt = ''; image.src = src;
    holder.append(image); holder.dataset.illustrationId = row.id; holder.classList.add('illustration-filled');
  }

  const viewer = node('dialog', 'media-viewer'); viewer.setAttribute('aria-labelledby', 'mediaViewerTitle');
  const viewerHead = node('div', 'media-viewer-heading');
  const viewerTitle = node('h2'); viewerTitle.id = 'mediaViewerTitle';
  const close = node('button', 'icon-button', '×'); close.type = 'button'; close.title = '關閉圖片'; close.setAttribute('aria-label', '關閉圖片');
  viewerHead.append(viewerTitle, close);
  const viewerImage = node('img', 'media-full-image'); viewerImage.alt = ''; viewerImage.hidden = true;
  const empty = node('div', 'media-empty', '尚未有圖片，按下生成來繪製。');
  const viewerStatus = node('p', 'subtle media-viewer-status'); viewerStatus.setAttribute('role', 'status');
  const viewerActions = node('div', 'media-viewer-actions');
  const viewerGenerate = node('button', 'secondary', '生成圖片'); viewerGenerate.type = 'button';
  const download = node('a', 'quiet-link', '下載圖片 ↗'); download.hidden = true;
  viewerActions.append(viewerGenerate, download);
  const details = node('details', 'media-custom'); details.append(node('summary', '', '調整畫面描述'));
  const promptLabel = node('label', '', '補充英文構圖（可留白，依已知資料繪製）');
  const prompt = node('textarea'); prompt.rows = 3; prompt.maxLength = 1600; promptLabel.append(prompt); details.append(promptLabel);
  viewer.append(viewerHead, viewerImage, empty, viewerStatus, viewerActions, details,
    node('small', 'subtle', '圖片是視覺詮釋，不會改動故事、角色或物品設定。'));
  document.body.append(viewer);
  close.onclick = () => viewer.close();
  viewer.addEventListener('click', event => {if (event.target === viewer) {const r = viewer.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) viewer.close();}});
  viewer.addEventListener('close', () => {viewerTarget = null; prompt.value = ''; details.open = false;});
  function openViewer(target) {
    if (!subject(target)) return;
    if (!viewer.open) {viewerTarget = {...target}; prompt.value = ''; viewer.showModal();}
    else viewerTarget = {...target};
    paintViewer().catch(e => report(e.message));
  }
  function blocked() {return sending || snapshot?.images.some(working) || (typeof busy !== 'undefined' && busy) || (typeof syncing !== 'undefined' && syncing);}
  async function paintViewer() {
    if (!viewer.open || !viewerTarget) return;
    const target = {...viewerTarget}, info = subject(target);
    if (!info) {viewer.close(); return;}
    viewerTitle.textContent = info.name; viewerStatus.textContent = statusFor(target);
    viewerGenerate.disabled = blocked(); viewerGenerate.textContent = completed(target) ? '重新生成' : '生成圖片';
    const row = completed(target); viewerImage.hidden = !row; empty.hidden = Boolean(row); download.hidden = !row;
    if (!row) {viewerImage.removeAttribute('src'); download.removeAttribute('href'); return;}
    const capturedScope = scope, src = await urlFor(row, capturedScope);
    if (!src || !viewer.open || capturedScope !== scope || !viewerTarget || viewerTarget.kind !== target.kind || viewerTarget.subject !== target.subject || completed(target)?.id !== row.id) return;
    viewerImage.src = src; viewerImage.alt = info.name + '圖片';
    download.href = src; download.download = 'Taleoria-' + target.kind + '-' + row.id + '.png';
  }
  async function generate(target, customPrompt = '') {
    if (!subject(target) || blocked()) return;
    const capturedScope = scope; sending = true; announcement.textContent = '正在提交圖片…'; paint().catch(() => {});
    try {
      await json('/api/illustrations/generate', {...target, revision: current().revision, request_id: crypto.randomUUID(),
        prompt: customPrompt, regenerate: Boolean(completed(target))});
      if (capturedScope === scopeOf(current())) {await poll(true); report('圖片已排隊，完成後會顯示在原來的位置。');}
    } catch (e) {report(e.message);}
    finally {sending = false; await paint();}
  }
  viewerGenerate.onclick = () => viewerTarget && generate({...viewerTarget}, prompt.value.trim());

  function toolbar(host, target, cls = '', text = false) {
    let entry = controls.get(host);
    if (!entry) {
      const tools = node('div', 'media-tools ' + cls);
      const draw = imageButton('generate', '生成圖片'), view = imageButton('view', '檢視圖片');
      if (text) view.append(node('span', '', '檢視圖片'));
      const status = node('span', 'sr-only'); status.setAttribute('role', 'status');
      tools.append(draw, view, status); host.append(tools);
      entry = {tools, draw, view, status}; controls.set(host, entry);
    }
    const rows = rowsFor(target), info = subject(target), label = info?.name || '圖片', job = rows.find(working), failed = rows[0]?.status === 'error';
    entry.draw.disabled = !info || blocked(); entry.view.disabled = !completed(target);
    entry.draw.classList.toggle('media-working', Boolean(job));
    entry.draw.classList.toggle('media-failed', failed);
    entry.draw.setAttribute('aria-busy', String(Boolean(job)));
    entry.draw.title = job ? statusFor(target) : failed ? '生成未完成：' + statusFor(target) + ' 點此重試。' : (completed(target) ? '重新生成' : '生成') + label + '圖片';
    entry.draw.setAttribute('aria-label', entry.draw.title);
    entry.view.title = completed(target) ? '檢視' + label + '圖片' : label + '尚未有圖片';
    entry.view.setAttribute('aria-label', entry.view.title);
    if (entry.status.textContent !== statusFor(target)) entry.status.textContent = statusFor(target);
    entry.draw.onclick = event => {event.stopPropagation(); generate({...target});};
    entry.view.onclick = event => {event.stopPropagation(); openViewer(target);};
  }
  function clickable(holder, target) {
    holder.setAttribute('role', 'button'); holder.tabIndex = 0;
    holder.setAttribute('aria-label', '檢視' + (subject(target)?.name || '') + '圖片');
    holder.title = '檢視圖片';
    holder.onclick = event => {event.stopPropagation(); openViewer(target);};
    holder.onkeydown = event => {if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); openViewer(target);}};
  }
  async function paint() {
    if (!snapshot || scope !== scopeOf(current())) return;
    const version = ++paintVersion, painting = [];
    const banner = document.querySelector('.scene-banner');
    if (banner) {
      const target = {kind:'scene', subject:current().pc.location};
      toolbar(banner, target, 'media-scene-tools', true);
      const art = banner.querySelector('.scene-art'); if (art) painting.push(decorate(art, target, version));
      const reserved = banner.querySelector('.image-reserved'); if (reserved) reserved.hidden = true;
      banner.classList.toggle('has-illustration', Boolean(completed(target)));
    }
    for (const holder of document.querySelectorAll('.portrait, .character-portrait')) {
      const target = {kind:'portrait', subject:current().pc.id};
      if (!holder.parentNode.classList.contains('media-avatar')) {
        const wrap = node('div', 'media-avatar ' + (holder.classList.contains('portrait') ? 'media-sidebar-avatar' : 'media-sheet-avatar'));
        holder.before(wrap); wrap.append(holder);
      }
      toolbar(holder.parentNode, target, 'media-avatar-tools');
      if (holder.classList.contains('character-portrait')) clickable(holder, target);
      painting.push(decorate(holder, target, version));
    }
    for (const holder of document.querySelectorAll('.person-portrait[data-media-key]')) {
      const target = {kind:'portrait', subject:holder.dataset.mediaKey}, heading = holder.closest('.person-heading');
      if (heading) toolbar(heading, target, 'media-person-tools');
      clickable(holder, target); painting.push(decorate(holder, target, version));
    }
    for (const card of document.querySelectorAll('.item-card[data-media-key]')) {
      const target = {kind:'item', subject:card.dataset.mediaKey};
      toolbar(card, target, 'media-item-tools');
      const holder = card.querySelector('.item-image'); if (holder) painting.push(decorate(holder, target, version));
    }
    const itemImage = document.querySelector('#itemDialog .item-image[data-media-key]');
    if (itemImage) {
      const target = {kind:'item', subject:itemImage.dataset.mediaKey};
      toolbar(document.getElementById('itemDialog'), target, 'media-item-dialog-tools');
      itemImage.removeAttribute('aria-hidden'); clickable(itemImage, target); painting.push(decorate(itemImage, target, version));
    }
    await Promise.all(painting); await paintViewer();
  }
  async function poll(force = false) {
    const s = current(); if (!s?.pc || polling || (document.hidden && !force)) return;
    const nextScope = scopeOf(s), nextSignature = nextScope + ':' + s.revision + ':' + s.pc.location;
    const busyState = String(typeof busy !== 'undefined' && busy) + ':' + String(typeof syncing !== 'undefined' && syncing);
    if (!force && signature === nextSignature && !snapshot?.images.some(working)) {
      if (needsPaint || lastBusy !== busyState) {needsPaint = false; lastBusy = busyState; await paint();}
      return;
    }
    polling = true;
    try {
      const data = await json('/api/illustrations');
      if (nextScope !== scopeOf(current()) || s.revision !== current().revision) return;
      if (nextScope !== scope) {
        viewer.close(); for (const u of urls.values()) URL.revokeObjectURL(u); urls.clear(); downloads.clear();
        for (const holder of document.querySelectorAll('.illustration-filled')) clearPicture(holder);
      }
      scope = nextScope; snapshot = data; signature = nextSignature; needsPaint = false; lastBusy = busyState;
      if (!settings.contains(document.activeElement)) {endpoint.value = data.settings.endpoint; style.value = data.settings.style;}
      await paint();
    } catch (e) {if (force) report(e.message);} finally {polling = false;}
  }

  const settings = node('article', 'reading-card spacer illustration-settings');
  settings.append(node('h3', '', '插畫 · Draw Things'));
  const endpointLabel = node('label', '', '遊戲電腦上的 Draw Things 網址');
  const endpoint = node('input'); endpoint.type = 'url'; endpoint.value = 'http://127.0.0.1:7860'; endpointLabel.append(endpoint);
  const styleLabel = node('label', '', '共用美術風格（英文）');
  const style = node('textarea'); style.rows = 3; style.maxLength = 600; styleLabel.append(style);
  const save = node('button', 'secondary', '儲存並測試連線'); save.type = 'button';
  const connection = node('p', 'subtle', 'Draw Things 開啟後，可在場景、人物與物品旁生成圖片。'); connection.setAttribute('role', 'status');
  settings.append(endpointLabel, styleLabel, save, connection);
  const old = [...document.querySelectorAll('#page-settings article')].find(n => n.querySelector('h3')?.textContent === '插畫');
  if (old) old.replaceWith(settings); else document.getElementById('page-settings')?.append(settings);
  save.onclick = async () => {
    save.disabled = true; connection.textContent = '正在測試連線…';
    try {await json('/api/illustrations/settings', {endpoint:endpoint.value.trim(), style:style.value.trim()});
      const result = await json('/api/illustrations/connection'); connection.textContent = result.connected ? '已連接 Draw Things · ' + result.model : result.error;
      await poll(true);
    } catch (e) {connection.textContent = e.message;} finally {save.disabled = false;}
  };
  window.addEventListener('hashchange', () => {needsPaint = true; poll();});
  document.addEventListener('taleoria:media', () => {needsPaint = true; poll();});
  document.addEventListener('visibilitychange', () => {if (!document.hidden) poll(true);});
  setInterval(() => {poll().catch(e => report(e.message));}, 1200);
  poll(true).catch(e => report(e.message));
})();
