/* ===== צ'אט בין לקוח לאיש מקצוע =====
   חלון עגינה בתחתית המסך עם שני מצבים: רשימת שיחות ושיחה פתוחה.
   ההודעות מגיעות ב-long polling: הבקשה ממתינה בשרת עד שנשלחת הודעה. */
'use strict';

const Chat = (() => {
  let dock, listEl, threadEl, titleEl, subtitleEl, backBtn, form, input;
  let conversationId = null;
  let lastId = 0;
  let polling = false;
  let pollToken = 0;
  let onUnreadChange = null;

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function timeLabel(ts) {
    const d = new Date(ts * 1000);
    const today = new Date();
    const time = d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' });
    if (d.toDateString() === today.toDateString()) return time;
    return d.toLocaleDateString('he-IL', { day: 'numeric', month: 'numeric' }) + ' ' + time;
  }

  function build(apiFn, unreadCallback) {
    Chat.api = apiFn;
    onUnreadChange = unreadCallback;
    dock = document.createElement('section');
    dock.className = 'chat-dock hidden';
    dock.innerHTML = `
      <header class="chat-head">
        <button class="chat-back hidden" type="button" aria-label="חזרה לרשימה">›</button>
        <div class="chat-titles">
          <b id="chatTitle">הודעות</b>
          <span class="muted small" id="chatSubtitle"></span>
        </div>
        <button class="chat-close" type="button" aria-label="סגירה">✕</button>
      </header>
      <div class="chat-list" id="chatList"></div>
      <div class="chat-thread hidden" id="chatThread"></div>
      <form class="chat-input hidden" id="chatForm">
        <textarea id="chatText" rows="1" maxlength="2000" placeholder="כתבו הודעה…"></textarea>
        <button class="primary" type="submit" aria-label="שליחה">שליחה</button>
      </form>`;
    document.body.appendChild(dock);

    listEl = dock.querySelector('#chatList');
    threadEl = dock.querySelector('#chatThread');
    titleEl = dock.querySelector('#chatTitle');
    subtitleEl = dock.querySelector('#chatSubtitle');
    backBtn = dock.querySelector('.chat-back');
    form = dock.querySelector('#chatForm');
    input = dock.querySelector('#chatText');

    dock.querySelector('.chat-close').onclick = close;
    backBtn.onclick = openInbox;
    form.onsubmit = onSend;
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = Math.min(110, input.scrollHeight) + 'px';
    });
  }

  /* ---------- רשימת שיחות ---------- */
  async function openInbox() {
    dock.classList.remove('hidden');
    stopPolling();
    conversationId = null;
    titleEl.textContent = 'הודעות';
    subtitleEl.textContent = '';
    backBtn.classList.add('hidden');
    form.classList.add('hidden');
    threadEl.classList.add('hidden');
    listEl.classList.remove('hidden');
    listEl.innerHTML = '<div class="chat-empty">טוען…</div>';
    try {
      const data = await Chat.api('/api/conversations');
      if (onUnreadChange) onUnreadChange(data.unread);
      if (!data.conversations.length) {
        listEl.innerHTML = `<div class="chat-empty">
          <p>אין עדיין שיחות.</p>
          <p class="muted small">אפשר לפתוח שיחה מכרטיס של איש מקצוע או מתוך הזמנה.</p></div>`;
        return;
      }
      listEl.innerHTML = data.conversations.map((c) => `
        <button class="chat-row" data-conv="${c.id}" type="button">
          <span class="chat-avatar">${c.other_name.trim().charAt(0)}</span>
          <span class="chat-row-main">
            <b>${esc(c.other_name)}</b>
            <span class="muted small">${esc(c.last_message
              ? (c.last_message.mine ? 'את/ה: ' : '') + c.last_message.body.slice(0, 46)
              : esc(c.profession))}</span>
          </span>
          <span class="chat-row-side">
            ${c.last_message ? `<span class="muted small">${timeLabel(c.last_message.created_at)}</span>` : ''}
            ${c.unread ? `<span class="chat-badge">${c.unread}</span>` : ''}
          </span>
        </button>`).join('');
      listEl.querySelectorAll('[data-conv]').forEach((row) =>
        row.onclick = () => openThread(+row.dataset.conv));
    } catch (err) {
      listEl.innerHTML = `<div class="chat-empty">${esc(err.message)}</div>`;
    }
  }

  /* ---------- שיחה פתוחה ---------- */
  async function openThread(id, meta) {
    dock.classList.remove('hidden');
    stopPolling();
    conversationId = id;
    lastId = 0;
    listEl.classList.add('hidden');
    threadEl.classList.remove('hidden');
    form.classList.remove('hidden');
    backBtn.classList.remove('hidden');
    threadEl.innerHTML = '<div class="chat-empty">טוען…</div>';
    try {
      const conv = meta || await Chat.api('/api/conversations/' + id);
      titleEl.textContent = conv.other_name;
      subtitleEl.textContent = conv.role === 'client' ? conv.profession : 'לקוח';
      threadEl.innerHTML = '';
      const data = await Chat.api(`/api/conversations/${id}/messages?after=0`);
      if (!data.messages.length) {
        threadEl.innerHTML = '<div class="chat-empty">אין עדיין הודעות. אפשר לפתוח בשאלה.</div>';
      }
      append(data.messages);
      markRead(data.read_up_to);
      lastId = data.last_id;
      input.focus();
      startPolling();
      if (onUnreadChange) refreshUnread();
    } catch (err) {
      threadEl.innerHTML = `<div class="chat-empty">${esc(err.message)}</div>`;
    }
  }

  async function openFor({ proId, bookingId, name }) {
    dock.classList.remove('hidden');
    threadEl.classList.remove('hidden');
    listEl.classList.add('hidden');
    threadEl.innerHTML = '<div class="chat-empty">פותח שיחה…</div>';
    titleEl.textContent = name || 'שיחה';
    try {
      const conv = await Chat.api('/api/conversations', { method: 'POST',
        body: bookingId ? { booking_id: bookingId } : { pro_id: proId } });
      await openThread(conv.id, conv);
    } catch (err) {
      threadEl.innerHTML = `<div class="chat-empty">${esc(err.message)}</div>`;
    }
  }

  function append(messages) {
    // ההודעה שנשלחה מוצגת מיד, ומיד אחריה מגיעה גם מהשרת ל-long poll שממתין.
    // סינון לפי מזהה מונע כפילות, ומגן גם על כל מסירה כפולה אחרת.
    messages = messages.filter((m) => !threadEl.querySelector(`.bubble[data-id="${m.id}"]`));
    if (!messages.length) return;
    const placeholder = threadEl.querySelector('.chat-empty');
    if (placeholder) placeholder.remove();
    threadEl.insertAdjacentHTML('beforeend', messages.map((m) => `
      <div class="bubble ${m.mine ? 'mine' : 'theirs'}" data-id="${m.id}" data-time="${m.created_at}">
        <div class="bubble-body">${esc(m.body)}</div>
        <div class="bubble-meta">${timeLabel(m.created_at)}${m.mine && m.read ? ' · נקרא' : ''}</div>
      </div>`).join(''));
    threadEl.scrollTop = threadEl.scrollHeight;
  }

  // סימון "נקרא" על בועות שכבר על המסך, בלי לצייר אותן מחדש
  function markRead(upTo) {
    if (!upTo) return;
    threadEl.querySelectorAll('.bubble.mine').forEach((bubble) => {
      const meta = bubble.querySelector('.bubble-meta');
      if (+bubble.dataset.id <= upTo && !meta.textContent.includes('נקרא')) {
        meta.textContent = timeLabel(+bubble.dataset.time) + ' · נקרא';
      }
    });
  }

  /* ---------- long polling ---------- */
  function startPolling() {
    polling = true;
    const token = ++pollToken;
    (async function loop() {
      while (polling && token === pollToken && conversationId) {
        try {
          const data = await Chat.api(
            `/api/conversations/${conversationId}/messages?after=${lastId}&wait=1`);
          if (token !== pollToken) return;
          if (data.messages.length) {
            append(data.messages);
            lastId = data.last_id;
            refreshUnread();
          }
          markRead(data.read_up_to);   // אישור קריאה על הודעות שכבר מוצגות
        } catch (err) {
          if (token !== pollToken) return;
          await new Promise((r) => setTimeout(r, 4000));   // רשת נפלה - ננסה שוב
        }
      }
    })();
  }

  function stopPolling() {
    polling = false;
    pollToken++;
  }

  async function onSend(e) {
    e.preventDefault();
    const body = input.value.trim();
    if (!body || !conversationId) return;
    input.value = '';
    input.style.height = 'auto';
    try {
      const msg = await Chat.api(`/api/conversations/${conversationId}/messages`,
        { method: 'POST', body: { body } });
      append([{ ...msg, mine: true }]);
      lastId = Math.max(lastId, msg.id);
    } catch (err) {
      input.value = body;      // לא מאבדים את מה שנכתב
      append([]);
      alert(err.message);
    }
  }

  async function refreshUnread() {
    if (!onUnreadChange) return;
    try {
      const data = await Chat.api('/api/conversations');
      onUnreadChange(data.unread);
    } catch (_) {}
  }

  function close() {
    stopPolling();
    conversationId = null;
    dock.classList.add('hidden');
    refreshUnread();
  }

  return { build, openInbox, openThread, openFor, close, refreshUnread };
})();
