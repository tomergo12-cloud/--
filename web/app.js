/* ===== קרוב — לוגיקת צד לקוח ===== */
'use strict';

const state = {
  token: localStorage.getItem('pronear_token') || null,
  user: null,
  professional: null,
  meta: null,
  loc: null,
  results: [],
  profession: '',
  filters: { now: false, verified: false },
  bookingRole: 'client',
  adminTab: 'pros',
  authMode: 'login',
  authRole: 'client',
  slots: [],
  mapReady: false,
};

/* ---------- עזרים ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = (n) => '₪' + Number(n || 0).toLocaleString('he-IL');

function toast(message, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = message;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function stars(avg) {
  if (!avg) return '<span class="muted small">אין דירוג</span>';
  const full = Math.round(avg);
  return `<span class="stars">${'★'.repeat(full)}${'☆'.repeat(5 - full)}</span>`;
}

function fmtWhen(ts) {
  const d = new Date(ts * 1000);
  const today = new Date();
  const time = d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' });
  if (d.toDateString() === today.toDateString()) return `היום ${time}`;
  if (new Date(today.getTime() + 864e5).toDateString() === d.toDateString()) return `מחר ${time}`;
  return d.toLocaleDateString('he-IL', { weekday: 'short', day: 'numeric', month: 'numeric' }) + ' ' + time;
}

function toLocalInput(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/* ---------- API ---------- */
async function api(path, { method = 'GET', body = null } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers.Authorization = 'Bearer ' + state.token;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : null });
  let data = {};
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) {
    const err = new Error(data.error || `שגיאה ${res.status}`);
    err.status = res.status;
    err.field = data.field;
    throw err;
  }
  return data;
}

/* ---------- חלוניות ---------- */
function openModal(html) {
  $('#modal').innerHTML = `<button class="x" type="button" aria-label="סגירה">✕</button>` + html;
  $('#overlay').classList.remove('hidden');
  $('.x', $('#modal')).onclick = closeModal;
}
function closeModal() { $('#overlay').classList.add('hidden'); $('#modal').innerHTML = ''; }
$('#overlay').addEventListener('click', (e) => { if (e.target.id === 'overlay') closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

/* ---------- ניווט והרשאות ---------- */
const VIEW_FOR_ROLE = { admin: 'admin', pro: 'home', client: 'home' };

function show(view) {
  if (view !== 'login' && !state.user) view = 'login';
  $$('.view').forEach((el) => el.classList.add('hidden'));
  const target = $('#view-' + view);
  if (target) target.classList.remove('hidden');
  window.scrollTo({ top: 0 });
  if (view === 'home') ensureMap().then(runSearch);
  if (view === 'bookings') {
    // איש מקצוע מגיע לכאן בשביל הבקשות שקיבל - לא בשביל מה שהוא עצמו הזמין
    const isPro = state.user && (state.user.role === 'pro' || state.user.pro_id);
    state.bookingRole = isPro ? 'pro' : 'client';
    $$('#bookingTabs .tab').forEach((t) =>
      t.classList.toggle('active', t.dataset.role === state.bookingRole));
    loadBookings();
  }
  if (view === 'dashboard') loadDashboard();
  if (view === 'admin') loadAdmin();
}

$$('[data-nav]').forEach((btn) => btn.addEventListener('click', () => show(btn.dataset.nav)));

function applyRoleUI() {
  const role = state.user ? state.user.role : null;
  const isPro = role === 'pro' || (state.user && state.user.pro_id);
  $$('.auth-only').forEach((el) => el.classList.toggle('hidden', !state.user));
  $$('.anon-only').forEach((el) => el.classList.toggle('hidden', !!state.user));
  $$('.pro-only').forEach((el) => el.classList.toggle('hidden', !isPro));
  $$('.admin-only').forEach((el) => el.classList.toggle('hidden', role !== 'admin'));
  $$('.client-only').forEach((el) => el.classList.toggle('hidden', role === 'admin'));
  if (state.user) {
    const roleName = { client: 'לקוח', pro: 'איש מקצוע', admin: 'מנהל' }[role] || '';
    $('#whoami').textContent = `${state.user.name} · ${roleName}`;
    $('#bookingsLabel').textContent = role === 'pro' ? 'בקשות והזמנות' : 'ההזמנות שלי';
  }
}

async function refreshMe() {
  if (!state.token) { state.user = null; state.professional = null; applyRoleUI(); return; }
  try {
    const data = await api('/api/auth/me');
    state.user = data.user;
    state.professional = data.professional || null;
  } catch (_) {
    state.token = null; state.user = null; state.professional = null;
    localStorage.removeItem('pronear_token');
  }
  applyRoleUI();
  if (state.user) { refreshBookingsBadge(); refreshChatBadge(); }
}

function setChatBadge(count) {
  const badge = $('#chatBadge');
  badge.textContent = count;
  badge.classList.toggle('hidden', !count);
}

async function refreshChatBadge() {
  if (!state.user) return;
  try {
    const data = await api('/api/conversations');
    setChatBadge(data.unread);
  } catch (_) {}
}

async function refreshBookingsBadge() {
  try {
    const data = await api('/api/bookings?status=pending');
    const badge = $('#bookingsBadge');
    badge.textContent = data.bookings.length;
    badge.classList.toggle('hidden', data.bookings.length === 0);
  } catch (_) {}
}

/* ---------- התחברות ---------- */
const ROLE_HINTS = {
  client: 'חיפוש אנשי מקצוע פנויים באזור שלך והזמנה שלהם.',
  pro: 'ניהול לוח הזמינות שלך וקבלת בקשות עבודה מלקוחות.',
  admin: 'צפייה וניהול של כל אנשי המקצוע, המשתמשים, ההזמנות והביקורות.',
};
const ROLE_ICONS = {
  client: 'M12 3a5 5 0 1 1 0 10 5 5 0 0 1 0-10zM4 21c0-4 3.6-6 8-6s8 2 8 6',
  pro: 'M14.5 3.5a5 5 0 0 0-6.2 6.2L3 15l3 3 5.3-5.3a5 5 0 0 0 6.2-6.2L15 9l-2-2z',
  admin: 'M12 3l8 3v5c0 4.5-3.2 8.4-8 10-4.8-1.6-8-5.5-8-10V6z',
};

function renderAuth() {
  const isLogin = state.authMode === 'login';
  $('#roleHint').textContent = ROLE_HINTS[state.authRole];
  $('#authSubmit').textContent = isLogin ? 'כניסה' : 'יצירת חשבון';
  $('#authSwitch').textContent = isLogin ? 'אין לך חשבון? הרשמה' : 'יש לך כבר חשבון? כניסה';
  // מנהלים לא נרשמים מהאתר - החשבון נוצר בצד השרת
  const canRegister = state.authRole !== 'admin';
  $('#authSwitch').classList.toggle('hidden', !canRegister);
  $$('.reg-only').forEach((el) => el.classList.toggle('hidden', isLogin || !canRegister));
  $('#auName').required = !isLogin && canRegister;
  $('#authErr').classList.add('hidden');
  $$('.role-tab').forEach((tab) => tab.classList.toggle('on', tab.dataset.role === state.authRole));
  $$('.role-ico').forEach((el) => {
    el.innerHTML = `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"
      stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="${ROLE_ICONS[el.dataset.icon]}"/></svg>`;
  });
}

$$('.role-tab').forEach((tab) => tab.onclick = () => {
  state.authRole = tab.dataset.role;
  if (state.authRole === 'admin') state.authMode = 'login';
  renderAuth();
});
$('#authSwitch').onclick = () => {
  state.authMode = state.authMode === 'login' ? 'register' : 'login';
  renderAuth();
};
$$('.demo-fill').forEach((btn) => btn.onclick = () => {
  state.authRole = btn.dataset.role;
  state.authMode = 'login';
  renderAuth();
  $('#auEmail').value = btn.dataset.email;
  $('#auPass').value = btn.dataset.pass;
});

$('#authForm').onsubmit = async (e) => {
  e.preventDefault();
  const isLogin = state.authMode === 'login';
  const payload = { email: $('#auEmail').value.trim(), password: $('#auPass').value };
  if (!isLogin) {
    payload.name = $('#auName').value.trim();
    payload.phone = $('#auPhone').value.trim();
    payload.role = state.authRole;      // client או pro בלבד; השרת אוכף
  }
  try {
    const data = await api(isLogin ? '/api/auth/login' : '/api/auth/register',
      { method: 'POST', body: payload });
    state.token = data.token;
    localStorage.setItem('pronear_token', data.token);
    await refreshMe();
    // הכניסה נקבעת לפי התפקיד האמיתי מהשרת, לא לפי הלשונית שנבחרה
    if (state.authRole === 'admin' && state.user.role !== 'admin') {
      toast('החשבון הזה אינו חשבון ניהול — נכנסת כמשתמש רגיל', 'bad');
    }
    show(VIEW_FOR_ROLE[state.user.role] || 'home');
    toast(`שלום ${data.user.name}!`, 'ok');
    if (!isLogin && state.authRole === 'pro') {
      toast('עכשיו נשלים את הפרופיל המקצועי שלך');
      show('dashboard');
    }
  } catch (err) {
    const box = $('#authErr');
    box.textContent = err.message;
    box.classList.remove('hidden');
  }
};

$('#logoutBtn').onclick = async () => {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch (_) {}
  state.token = null; state.user = null; state.professional = null;
  localStorage.removeItem('pronear_token');
  Chat.close();
  setChatBadge(0);
  applyRoleUI();
  show('login');
  toast('התנתקת');
};

/* ---------- מיקום ---------- */
function setLocation(lat, lng, label) {
  state.loc = { lat: +(+lat).toFixed(5), lng: +(+lng).toFixed(5), label };
  $('#locLabel').textContent = label;
  $('#addrInput').value = label;
  localStorage.setItem('pronear_loc', JSON.stringify(state.loc));
}

function useDefaultLocation() {
  const def = state.meta ? state.meta.default_location : { lat: 32.0853, lng: 34.7818 };
  setLocation(def.lat, def.lng, 'תל אביב (ברירת מחדל)');
}

function detectLocation(announce = false) {
  if (!navigator.geolocation) {
    if (announce) toast('הדפדפן לא תומך באיתור מיקום', 'bad');
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => { setLocation(pos.coords.latitude, pos.coords.longitude, 'המיקום הנוכחי שלי'); runSearch(); },
    () => { if (announce) toast('לא הצלחנו לאתר את המיקום', 'bad'); },
    { timeout: 7000, maximumAge: 300000 }
  );
}
$('#useGps').onclick = () => detectLocation(true);
$('#locChip').onclick = () => $('#addrInput').focus();

/* ---------- מפה ---------- */
async function ensureMap() {
  if (state.mapReady) return;
  state.mapReady = true;
  await MapLayer.init({
    container: $('#mapBox'),
    statusEl: $('#mapStatus'),
    key: state.meta.maps_key,
    center: state.loc || state.meta.default_location,
    onPick: (proId) => openProfile(proId),
  });
  // חיפוש כתובות של Google, אם המפתח נטען בהצלחה
  const attached = MapLayer.attachAutocomplete($('#addrInput'), (place) => {
    setLocation(place.lat, place.lng, place.label);
    runSearch();
  });
  if (!attached) {
    $('#addrInput').placeholder = 'לחיפוש כתובת נדרש מפתח Google Maps — אפשר להשתמש במיקום הנוכחי';
  }
}

/* ---------- חיפוש ---------- */
function buildQuery() {
  const p = new URLSearchParams();
  p.set('lat', state.loc.lat);
  p.set('lng', state.loc.lng);
  p.set('radius_km', $('#radiusInput').value);
  p.set('duration', $('#durationSel').value);
  p.set('sort', $('#sortSel').value);
  const text = $('#qText').value.trim();
  if (text) p.set('q', text);
  if (state.profession) p.set('profession', state.profession);
  if ($('#whenSel').value === 'at' && $('#atInput').value) {
    p.set('when', 'at');
    p.set('at', $('#atInput').value);
  }
  if (state.filters.now) p.set('available_now', '1');
  if (state.filters.verified) p.set('verified', '1');
  if ($('#maxRate').value) p.set('max_rate', $('#maxRate').value);
  if ($('#minRating').value) p.set('min_rating', $('#minRating').value);
  return p.toString();
}

let searchSeq = 0;
async function runSearch() {
  if (!state.loc || !state.user) return;
  const seq = ++searchSeq;
  $('#results').innerHTML = '<div class="skeleton"></div>'.repeat(3);
  try {
    const data = await api('/api/search?' + buildQuery());
    if (seq !== searchSeq) return;
    state.results = data.results;
    renderResults(data);
    MapLayer.render(data, state.loc);
    $('#mapMeta').textContent = `${data.results.length} על המפה`;
  } catch (err) {
    $('#results').innerHTML = `<div class="empty">${esc(err.message)}</div>`;
  }
}

function renderResults(data) {
  const box = $('#results');
  $('#resTitle').textContent = state.profession ? `${state.profession} באזור שלך` : 'אנשי מקצוע באזור שלך';
  $('#resMeta').textContent =
    `${data.total} נמצאו · ${data.available_now_count} פנויים עכשיו · רדיוס ${data.query.radius_km} ק״מ`;

  if (!data.results.length) {
    box.innerHTML = `<div class="empty"><h3>לא נמצאו אנשי מקצוע מתאימים</h3>
      <p>אפשר להגדיל את הרדיוס, לבטל סינון או לחפש בזמן אחר.</p></div>`;
    return;
  }

  box.innerHTML = data.results.map((pro) => `
    <article class="card pro-card" data-pro="${pro.id}">
      <div class="pro-photo">${avatarHtml(pro, 64)}</div>
      <div class="pro-main">
        <div class="pro-top">
          <b>${esc(pro.name)}</b>
          <span class="cat-inline">${iconSvg(pro.profession, 15)}${esc(pro.profession)}</span>
          ${pro.verified ? '<span class="pill verified">מאומת</span>' : ''}
          ${pro.emergency ? '<span class="pill emergency">חירום</span>' : ''}
        </div>
        <div class="pro-sub">${esc(pro.headline || '')}</div>
        <div class="facts">
          <span>📍 <b class="num">${pro.distance_km}</b> ק״מ${pro.city ? ' · ' + esc(pro.city) : ''}</span>
          <span>⏱ ${esc(pro.eta_text)}</span>
          <span>💰 <b class="num">${money(pro.hourly_rate)}</b>/שעה</span>
          <span>${stars(pro.rating.avg)} ${pro.rating.count ? `<b class="num">${pro.rating.avg}</b> (${pro.rating.count})` : ''}</span>
        </div>
        ${pro.tags.length ? `<div class="tagline">${pro.tags.slice(0, 4).map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>` : ''}
      </div>
      <div class="pro-side">
        <div class="ring" style="background:conic-gradient(var(--accent) ${pro.score * 3.6}deg, var(--surface-2) 0)"
          title="ציון התאמה"><span class="num">${pro.score}</span></div>
        ${pro.available_now
          ? '<span class="pill free">● פנוי עכשיו</span>'
          : `<span class="pill soon">${esc(pro.next_free ? fmtWhen(pro.next_free.start) : 'ללא זמינות')}</span>`}
        <button class="primary" data-book="${pro.id}" type="button">הזמנה</button>
      </div>
    </article>`).join('');

  $$('.pro-card', box).forEach((card) => card.addEventListener('click', (e) => {
    const id = +card.dataset.pro;
    if (e.target.dataset.book) openBooking(id); else openProfile(id);
  }));
}

/* ---------- קטגוריות ---------- */
function renderCategories() {
  const inUse = state.meta.professions_in_use;
  const list = (inUse.length ? inUse : state.meta.professions.map((n) => ({ name: n, count: 0 }))).slice(0, 14);
  $('#catGrid').innerHTML = list.map((cat) => `
    <button class="cat-tile ${state.profession === cat.name ? 'on' : ''}" data-cat="${esc(cat.name)}" type="button">
      <span class="cat-ico" style="--hue:${hueFor(cat.name)}">${iconSvg(cat.name, 26)}</span>
      <span class="cat-name">${esc(cat.name)}</span>
      ${cat.count ? `<span class="cat-count num">${cat.count}</span>` : ''}
    </button>`).join('');
  $$('#catGrid .cat-tile').forEach((tile) => tile.onclick = () => {
    state.profession = state.profession === tile.dataset.cat ? '' : tile.dataset.cat;
    renderCategories();
    $('#clearCat').classList.toggle('hidden', !state.profession);
    runSearch();
  });
}
$('#clearCat').onclick = () => {
  state.profession = '';
  renderCategories();
  $('#clearCat').classList.add('hidden');
  runSearch();
};

/* ---------- פרופיל ---------- */
async function openProfile(proId) {
  openModal('<p class="muted">טוען…</p>');
  try {
    const pro = await api('/api/pros/' + proId);
    const listed = state.results.find((r) => r.id === proId);
    const parts = listed ? listed.score_parts : null;
    const labels = { availability: 'זמינות', distance: 'קרבה', rating: 'דירוג', price: 'מחיר', trust: 'אמינות' };
    openModal(`
      <div class="profile-head">
        <div class="pro-photo lg">${avatarHtml(pro, 84)}</div>
        <div>
          <h2>${esc(pro.name)}</h2>
          <p class="muted">${iconSvg(pro.profession, 15)} ${esc(pro.profession)}${pro.city ? ' · ' + esc(pro.city) : ''}</p>
          <div class="pro-top">
            ${pro.verified ? '<span class="pill verified">מאומת</span>' : ''}
            ${pro.available_now ? '<span class="pill free">פנוי עכשיו</span>'
              : (pro.next_free ? `<span class="pill soon">פנוי ${esc(fmtWhen(pro.next_free.start))}</span>` : '')}
            ${pro.emergency ? '<span class="pill emergency">קריאות חירום</span>' : ''}
          </div>
        </div>
      </div>
      <p>${esc(pro.headline || '')}</p>
      <p class="muted small">${esc(pro.bio || '')}</p>
      <div class="facts" style="margin:12px 0">
        <span>💰 <b class="num">${money(pro.hourly_rate)}</b>/שעה</span>
        <span>🧰 ${pro.years_experience} שנות ניסיון</span>
        <span>✅ ${pro.jobs_done} עבודות</span>
        <span>📏 רדיוס ${pro.service_radius_km} ק״מ</span>
        ${listed ? `<span>📍 ${listed.distance_km} ק״מ ממך</span>` : ''}
        ${pro.phone ? `<span>📞 ${esc(pro.phone)}</span>` : ''}
      </div>
      ${parts ? `<h3 class="sec-label">מדוע הוא הותאם לך</h3><div class="bars">${
        Object.entries(parts).map(([k, v]) =>
          `<div><span>${labels[k] || k}</span><span class="bar"><i style="width:${v}%"></i></span><span class="num">${Math.round(v)}</span></div>`).join('')
      }</div>` : ''}
      <h3 class="sec-label">לוח זמינות</h3>
      <p class="small">${pro.availability.length
        ? pro.availability.map((a) => `${esc(a.weekday_name)} ${a.start}–${a.end}`).join(' · ')
        : 'לא הוגדר לוח'}</p>
      <div class="row" style="margin:14px 0">
        <button class="primary big" id="pfBook" type="button">בחירת מועד והזמנה</button>
        <button class="ghost" id="pfChat" type="button">שליחת הודעה</button>
      </div>
      <h3 class="sec-label">ביקורות (${pro.rating.count})</h3>
      ${pro.reviews.length ? pro.reviews.map((r) => `
        <div class="review"><b>${esc(r.name)}</b> ${stars(r.rating)}
          <div class="muted small">${esc(r.comment)}</div></div>`).join('')
        : '<p class="muted small">אין עדיין ביקורות.</p>'}`);
    $('#pfBook').onclick = () => openBooking(proId);
    $('#pfChat').onclick = () => {
      if (!state.user) return show('login');
      closeModal();
      Chat.openFor({ proId, name: pro.name });
    };
  } catch (err) {
    openModal(`<h2>שגיאה</h2><p class="err">${esc(err.message)}</p>`);
  }
}

/* ---------- הזמנה ---------- */
async function openBooking(proId) {
  if (!state.user) return show('login');
  openModal('<p class="muted">טוען מועדים פנויים…</p>');
  try {
    const pro = await api('/api/pros/' + proId);
    const duration = Math.max(pro.min_job_minutes, +$('#durationSel').value);
    const data = await api(`/api/pros/${proId}/slots?days=7&duration=${duration}&step=30`);
    state.slots = data.slots;
    if (!data.slots.length) {
      return openModal(`<h2>${esc(pro.name)}</h2>
        <p>אין מועדים פנויים בשבוע הקרוב לעבודה של ${duration} דקות.</p>`);
    }
    let day = '';
    const slotsHtml = data.slots.slice(0, 60).map((slot, i) => {
      const label = new Date(slot.start * 1000).toLocaleDateString('he-IL',
        { weekday: 'long', day: 'numeric', month: 'numeric' });
      const header = label !== day ? `<div class="slot-day">${esc(label)}</div>` : '';
      day = label;
      const time = new Date(slot.start * 1000).toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' });
      return `${header}<button class="slot" type="button" data-slot="${i}">${time}</button>`;
    }).join('');

    openModal(`
      <h2>הזמנת ${esc(pro.name)}</h2>
      <p class="muted small">${esc(pro.profession)} · ${money(pro.hourly_rate)}/שעה · מינימום ${pro.min_job_minutes} דק׳</p>
      <div id="bkErr" class="err hidden"></div>
      <label>בחירת מועד (${duration} דקות)</label>
      <div class="slot-grid" id="slotGrid">${slotsHtml}</div>
      <form id="bookForm" class="stack" style="margin-top:14px">
        <div class="field"><label for="bkAddress">כתובת</label>
          <input id="bkAddress" value="${esc(state.loc.label.startsWith('המיקום') ? '' : state.loc.label)}"
            placeholder="רחוב, מספר, עיר" required></div>
        <div class="field"><label for="bkNote">מה צריך לעשות?</label>
          <textarea id="bkNote" rows="2" placeholder="תיאור קצר של העבודה"></textarea></div>
        <div class="row between">
          <span class="muted small">עלות משוערת: <b class="num">${money(Math.round(pro.hourly_rate * duration / 60))}</b></span>
          <button class="primary" type="submit" id="bkSubmit" disabled>שליחת בקשה</button>
        </div>
      </form>`);

    let picked = null;
    $$('#slotGrid .slot').forEach((btn) => btn.onclick = () => {
      $$('#slotGrid .slot').forEach((b) => b.classList.remove('on'));
      btn.classList.add('on');
      picked = state.slots[+btn.dataset.slot];
      $('#bkSubmit').disabled = false;
    });

    $('#bookForm').onsubmit = async (e) => {
      e.preventDefault();
      if (!picked) return;
      $('#bkSubmit').disabled = true;
      try {
        await api('/api/bookings', { method: 'POST', body: {
          pro_id: proId, start: picked.start, duration_minutes: duration,
          address: $('#bkAddress').value.trim(), note: $('#bkNote').value.trim(),
          lat: state.loc.lat, lng: state.loc.lng,
        }});
        closeModal();
        toast('הבקשה נשלחה! ממתינה לאישור איש המקצוע.', 'ok');
        refreshBookingsBadge();
        runSearch();
      } catch (err) {
        const box = $('#bkErr');
        box.textContent = err.message;
        box.classList.remove('hidden');
        $('#bkSubmit').disabled = false;
      }
    };
  } catch (err) {
    openModal(`<h2>שגיאה</h2><p class="err">${esc(err.message)}</p>`);
  }
}

/* ---------- הזמנות ---------- */
const STATUS_TEXT = { pending: 'ממתין לאישור', confirmed: 'מאושר', done: 'הושלם', declined: 'נדחה', cancelled: 'בוטל' };

async function loadBookings() {
  const box = $('#bookingsList');
  box.innerHTML = '<div class="skeleton"></div>';
  try {
    const data = await api('/api/bookings?role=' + state.bookingRole);
    if (!data.bookings.length) {
      box.innerHTML = '<div class="empty">אין הזמנות להצגה.</div>';
      return;
    }
    box.innerHTML = data.bookings.map((b) => {
      const who = b.role === 'client' ? `${esc(b.pro_name)} · ${esc(b.profession)}` : `${esc(b.client_name)} (לקוח)`;
      const actions = [];
      if (b.role === 'pro' && b.status === 'pending') {
        actions.push(`<button class="primary" data-act="confirmed" data-id="${b.id}" type="button">אישור</button>`);
        actions.push(`<button class="ghost" data-act="declined" data-id="${b.id}" type="button">דחייה</button>`);
      }
      if (b.role === 'pro' && b.status === 'confirmed') {
        actions.push(`<button class="primary" data-act="done" data-id="${b.id}" type="button">סיום עבודה</button>`);
      }
      if (['pending', 'confirmed'].includes(b.status)) {
        actions.push(`<button class="danger" data-act="cancelled" data-id="${b.id}" type="button">ביטול</button>`);
      }
      if (b.role === 'client' && b.status === 'done' && !b.reviewed) {
        actions.push(`<button class="ghost" data-review="${b.id}" type="button">כתיבת ביקורת</button>`);
      }
      actions.push(`<button class="ghost" data-chat="${b.id}" data-name="${esc(
        b.role === 'client' ? b.pro_name : b.client_name)}" type="button">צ׳אט</button>`);
      return `<article class="card booking">
        <div>
          <b>${who}</b>
          <div class="muted small">${esc(fmtWhen(b.start))} · ${b.duration_minutes} דק׳ · ${esc(b.address || 'ללא כתובת')}</div>
          ${b.note ? `<div class="muted small">📝 ${esc(b.note)}</div>` : ''}
          ${b.contact_phone ? `<div class="small">📞 ${esc(b.contact_phone)}</div>` : ''}
        </div>
        <div class="row" style="align-items:center">
          <span class="muted small num">${money(b.estimated_price)}</span>
          <span class="status ${b.status}">${STATUS_TEXT[b.status] || b.status}</span>
          ${actions.join('')}
        </div>
      </article>`;
    }).join('');

    $$('[data-act]', box).forEach((btn) => btn.onclick = async () => {
      btn.disabled = true;
      try {
        await api(`/api/bookings/${btn.dataset.id}/status`, { method: 'POST', body: { status: btn.dataset.act } });
        toast('ההזמנה עודכנה', 'ok');
        loadBookings(); refreshBookingsBadge();
      } catch (err) { toast(err.message, 'bad'); btn.disabled = false; }
    });
    $$('[data-review]', box).forEach((btn) => btn.onclick = () => openReview(+btn.dataset.review));
    $$('[data-chat]', box).forEach((btn) => btn.onclick = () =>
      Chat.openFor({ bookingId: +btn.dataset.chat, name: btn.dataset.name }));
  } catch (err) {
    box.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
  }
}

$$('#bookingTabs .tab').forEach((tab) => tab.onclick = () => {
  $$('#bookingTabs .tab').forEach((t) => t.classList.remove('active'));
  tab.classList.add('active');
  state.bookingRole = tab.dataset.role;
  loadBookings();
});

function openReview(bookingId) {
  openModal(`
    <h2>איך הייתה העבודה?</h2>
    <form id="revForm" class="stack">
      <div id="revErr" class="err hidden"></div>
      <div class="field"><label for="revRating">דירוג</label>
        <select id="revRating">
          <option value="5">★★★★★ מצוין</option><option value="4">★★★★ טוב</option>
          <option value="3">★★★ בסדר</option><option value="2">★★ חלש</option><option value="1">★ גרוע</option>
        </select></div>
      <div class="field"><label for="revComment">מה תרצו לספר?</label><textarea id="revComment" rows="3"></textarea></div>
      <button class="primary" type="submit">שליחת ביקורת</button>
    </form>`);
  $('#revForm').onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api(`/api/bookings/${bookingId}/review`, { method: 'POST', body: {
        rating: +$('#revRating').value, comment: $('#revComment').value.trim() } });
      closeModal(); toast('תודה על הביקורת!', 'ok'); loadBookings();
    } catch (err) {
      const box = $('#revErr'); box.textContent = err.message; box.classList.remove('hidden');
    }
  };
}

/* ---------- אזור איש המקצוע ---------- */
const DEFAULT_AVAIL = [0, 1, 2, 3, 4].map((d) => ({ weekday: d, start: '08:00', end: '17:00' }))
  .concat([{ weekday: 5, start: '08:00', end: '13:00' }]);

function renderAvailEditor(rules) {
  const byDay = {};
  (rules && rules.length ? rules : DEFAULT_AVAIL).forEach((r) => { byDay[r.weekday] = r; });
  $('#availEditor').innerHTML = state.meta.weekdays.map((name, day) => {
    const rule = byDay[day];
    return `<div class="avail-row ${rule ? '' : 'off'}" data-day="${day}">
      <input type="checkbox" ${rule ? 'checked' : ''} data-on aria-label="יום ${name}">
      <span>יום ${esc(name)}</span>
      <input type="time" value="${rule ? rule.start : '08:00'}" data-start>
      <input type="time" value="${rule ? rule.end : '17:00'}" data-end>
    </div>`;
  }).join('');
  $$('#availEditor [data-on]').forEach((cb) => cb.onchange = () =>
    cb.closest('.avail-row').classList.toggle('off', !cb.checked));
}

function collectAvailability() {
  return $$('#availEditor .avail-row')
    .filter((row) => $('[data-on]', row).checked)
    .map((row) => ({ weekday: +row.dataset.day, start: $('[data-start]', row).value, end: $('[data-end]', row).value }));
}

function renderPhoto() {
  const pro = state.professional;
  const preview = $('#photoPreview');
  if (!pro) { preview.innerHTML = ''; return; }
  preview.innerHTML = avatarHtml(pro, 96);
  $('#photoClear').classList.toggle('hidden', !pro.photo);
}

async function loadDashboard() {
  $('#professionList').innerHTML = state.meta.professions.map((p) => `<option value="${esc(p)}">`).join('');
  const pro = state.professional;
  $('#dashIntro').textContent = pro
    ? 'עדכון הפרופיל, לוח הזמינות והחסימות שלך.'
    : 'עוד לא יצרת פרופיל מקצועי — מלא את הפרטים כדי להופיע בחיפושים.';
  if (pro) {
    $('#pfProfession').value = pro.profession;
    $('#pfCity').value = pro.city || '';
    $('#pfHeadline').value = pro.headline || '';
    $('#pfBio').value = pro.bio || '';
    $('#pfRate').value = pro.hourly_rate;
    $('#pfRadius').value = pro.service_radius_km;
    $('#pfMin').value = pro.min_job_minutes;
    $('#pfYears').value = pro.years_experience;
    $('#pfTags').value = (pro.tags || []).join(',');
    $('#pfEmergency').checked = !!pro.emergency;
    $('#pfActive').checked = !!pro.active;
    $('#pfLat').value = pro.lat;
    $('#pfLng').value = pro.lng;
    renderAvailEditor(pro.availability);
    renderPhoto();
    loadTimeOff();
  } else {
    if (state.loc) { $('#pfLat').value = state.loc.lat; $('#pfLng').value = state.loc.lng; }
    renderAvailEditor(null);
  }
  await ensureMap();
  MapLayer.attachAutocomplete($('#pfAddr'), (place) => {
    $('#pfLat').value = place.lat.toFixed(5);
    $('#pfLng').value = place.lng.toFixed(5);
    if (!$('#pfCity').value) $('#pfCity').value = place.label;
  });
  applyRoleUI();
}

$('#useMyLoc').onclick = () => {
  if (!state.loc) return toast('אין מיקום זמין', 'bad');
  $('#pfLat').value = state.loc.lat;
  $('#pfLng').value = state.loc.lng;
};

$('#proForm').onsubmit = async (e) => {
  e.preventDefault();
  const body = {
    profession: $('#pfProfession').value.trim(), city: $('#pfCity').value.trim(),
    headline: $('#pfHeadline').value.trim(), bio: $('#pfBio').value.trim(),
    hourly_rate: +$('#pfRate').value, service_radius_km: +$('#pfRadius').value,
    min_job_minutes: +$('#pfMin').value, years_experience: +$('#pfYears').value,
    tags: $('#pfTags').value, emergency: $('#pfEmergency').checked, active: $('#pfActive').checked,
    lat: +$('#pfLat').value, lng: +$('#pfLng').value, availability: collectAvailability(),
  };
  try {
    const pro = state.professional
      ? await api('/api/pros/' + state.professional.id, { method: 'PUT', body })
      : await api('/api/pros', { method: 'POST', body });
    state.professional = pro;
    await refreshMe();
    renderAvailEditor(pro.availability);
    renderPhoto();
    toast('הפרופיל נשמר', 'ok');
    loadTimeOff();
  } catch (err) { toast(err.message, 'bad'); }
};

$('#saveAvail').onclick = async () => {
  if (!state.professional) return toast('קודם שומרים פרופיל', 'bad');
  try {
    const data = await api(`/api/pros/${state.professional.id}/availability`,
      { method: 'PUT', body: { availability: collectAvailability() } });
    state.professional.availability = data.availability;
    toast('לוח הזמינות עודכן', 'ok');
  } catch (err) { toast(err.message, 'bad'); }
};

/* העלאת תמונה: נקראת כ-data URL ונשלחת ב-JSON */
$('#photoPick').onclick = () => {
  if (!state.professional) return toast('קודם שומרים פרופיל', 'bad');
  $('#photoInput').click();
};
$('#photoInput').onchange = () => {
  const file = $('#photoInput').files[0];
  if (!file) return;
  if (file.size > 3 * 1024 * 1024) return toast('התמונה גדולה מדי (עד 3MB)', 'bad');
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const data = await api(`/api/pros/${state.professional.id}/photo`,
        { method: 'POST', body: { photo: reader.result } });
      state.professional.photo = data.photo;
      renderPhoto();
      toast('התמונה עודכנה', 'ok');
    } catch (err) { toast(err.message, 'bad'); }
    $('#photoInput').value = '';
  };
  reader.readAsDataURL(file);
};
$('#photoClear').onclick = async () => {
  try {
    await api(`/api/pros/${state.professional.id}/photo`, { method: 'DELETE' });
    state.professional.photo = '';
    renderPhoto();
    toast('התמונה הוסרה');
  } catch (err) { toast(err.message, 'bad'); }
};

async function loadTimeOff() {
  if (!state.professional) return;
  try {
    const data = await api(`/api/pros/${state.professional.id}/time-off`);
    $('#timeOffList').innerHTML = data.time_off.length
      ? data.time_off.map((off) => `<li><span>${esc(fmtWhen(off.start))} – ${esc(fmtWhen(off.end))}
          ${off.reason ? '· ' + esc(off.reason) : ''}</span>
          <button class="link" data-off="${off.id}" type="button">מחיקה</button></li>`).join('')
      : '<li class="muted small">אין חסימות עתידיות.</li>';
    $$('#timeOffList [data-off]').forEach((btn) => btn.onclick = async () => {
      await api(`/api/pros/${state.professional.id}/time-off/${btn.dataset.off}`, { method: 'DELETE' });
      loadTimeOff();
    });
  } catch (_) {}
}

$('#timeOffForm').onsubmit = async (e) => {
  e.preventDefault();
  if (!state.professional) return toast('קודם שומרים פרופיל', 'bad');
  try {
    await api(`/api/pros/${state.professional.id}/time-off`, { method: 'POST', body: {
      start: $('#offStart').value, end: $('#offEnd').value, reason: $('#offReason').value.trim() } });
    $('#offReason').value = '';
    toast('החסימה נוספה', 'ok');
    loadTimeOff();
  } catch (err) { toast(err.message, 'bad'); }
};

/* ---------- ניהול ---------- */
const ADMIN_FILTERS = {
  pros: [['all', 'הכול'], ['active', 'פעילים'], ['inactive', 'מושבתים'],
         ['verified', 'מאומתים'], ['unverified', 'לא מאומתים']],
  users: [['all', 'כל התפקידים'], ['client', 'לקוחות'], ['pro', 'אנשי מקצוע'], ['admin', 'מנהלים']],
  bookings: [['all', 'כל הסטטוסים'], ['pending', 'ממתין'], ['confirmed', 'מאושר'],
             ['done', 'הושלם'], ['cancelled', 'בוטל'], ['declined', 'נדחה']],
  reviews: [['', 'כל הביקורות'], ['3', '3 כוכבים ומטה'], ['2', '2 כוכבים ומטה']],
  chats: [['', 'כל השיחות']],
};

async function loadAdmin() {
  try {
    const stats = await api('/api/admin/stats');
    $('#adminStats').innerHTML = [
      ['אנשי מקצוע', stats.pros_total, `${stats.pros_active} פעילים`],
      ['פנויים עכשיו', stats.available_now, `מתוך ${stats.pros_active}`],
      ['מאומתים', stats.pros_verified, `${Math.round(stats.pros_verified / Math.max(1, stats.pros_total) * 100)}%`],
      ['משתמשים', stats.users, `${stats.clients} לקוחות`],
      ['הזמנות', stats.bookings, `${stats.bookings_pending} ממתינות`],
      ['דירוג ממוצע', stats.rating_avg ?? '—', `${stats.reviews} ביקורות`],
    ].map(([label, value, sub]) => `<div class="stat">
        <span class="stat-label">${label}</span>
        <b class="stat-value num">${value}</b>
        <span class="stat-sub">${sub}</span></div>`).join('');
  } catch (err) {
    $('#adminStats').innerHTML = `<div class="err">${esc(err.message)}</div>`;
    return;
  }
  const filters = ADMIN_FILTERS[state.adminTab];
  $('#adminFilter').innerHTML = filters.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  loadAdminTable();
}

async function loadAdminTable() {
  const body = $('#adminBody');
  body.innerHTML = '<div class="skeleton"></div>';
  const query = encodeURIComponent($('#adminSearch').value.trim());
  const filter = $('#adminFilter').value;
  try {
    if (state.adminTab === 'pros') {
      const { pros } = await api(`/api/admin/pros?q=${query}&status=${filter}`);
      body.innerHTML = adminTable(
        ['איש מקצוע', 'מקצוע', 'עיר', 'מחיר', 'דירוג', 'עבודות', 'סטטוס', ''],
        pros.map((p) => [
          `<div class="cell-user">${avatarHtml(p, 34)}<div><b>${esc(p.name)}</b>
             <div class="muted small">${esc(p.email)}</div></div></div>`,
          `<span class="cat-inline">${iconSvg(p.profession, 14)}${esc(p.profession)}</span>`,
          esc(p.city || '—'),
          `<span class="num">${money(p.hourly_rate)}</span>`,
          p.rating.count ? `<span class="num">${p.rating.avg} (${p.rating.count})</span>` : '—',
          `<span class="num">${p.jobs_done}</span>`,
          `${p.verified ? '<span class="pill verified">מאומת</span>' : ''}
           ${p.active ? '' : '<span class="pill off">מושבת</span>'}
           ${p.available_now ? '<span class="pill free">פנוי</span>' : ''}
           ${p.blocked ? '<span class="pill emergency">חסום</span>' : ''}`,
          `<button class="link" data-edit="${p.id}" type="button">עריכה</button>`,
        ]));
      $$('[data-edit]', body).forEach((btn) => btn.onclick = () =>
        openAdminEditor(pros.find((p) => p.id === +btn.dataset.edit)));

    } else if (state.adminTab === 'users') {
      const { users } = await api(`/api/admin/users?q=${query}&role=${filter}`);
      const roleName = { client: 'לקוח', pro: 'איש מקצוע', admin: 'מנהל' };
      body.innerHTML = adminTable(
        ['שם', 'אימייל', 'טלפון', 'תפקיד', 'הזמנות', 'סטטוס', ''],
        users.map((u) => [
          esc(u.name), esc(u.email), esc(u.phone || '—'),
          `<span class="pill ${u.role}">${roleName[u.role] || u.role}</span>`,
          `<span class="num">${u.bookings}</span>`,
          u.blocked ? '<span class="pill emergency">חסום</span>' : '<span class="pill free">פעיל</span>',
          u.role === 'admin' ? '' :
            `<button class="link" data-block="${u.id}" data-to="${u.blocked ? 0 : 1}" type="button">
               ${u.blocked ? 'ביטול חסימה' : 'חסימה'}</button>`,
        ]));
      $$('[data-block]', body).forEach((btn) => btn.onclick = async () => {
        try {
          await api(`/api/admin/users/${btn.dataset.block}/blocked`,
            { method: 'POST', body: { blocked: btn.dataset.to === '1' } });
          toast('המשתמש עודכן', 'ok');
          loadAdminTable();
        } catch (err) { toast(err.message, 'bad'); }
      });

    } else if (state.adminTab === 'bookings') {
      const { bookings } = await api(`/api/admin/bookings?status=${filter}`);
      body.innerHTML = adminTable(
        ['לקוח', 'איש מקצוע', 'מועד', 'משך', 'כתובת', 'מחיר', 'סטטוס'],
        bookings.map((b) => [
          `<b>${esc(b.client_name)}</b><div class="muted small">${esc(b.client_email)}</div>`,
          `<b>${esc(b.pro_name)}</b> · ${esc(b.profession)}
           <div class="muted small">${esc(b.pro_email)}</div>`,
          esc(fmtWhen(b.start)), `${b.duration_minutes} דק׳`, esc(b.address || '—'),
          `<span class="num">${money(b.estimated_price)}</span>`,
          `<span class="status ${b.status}">${STATUS_TEXT[b.status] || b.status}</span>`,
        ]));

    } else if (state.adminTab === 'chats') {
      const { conversations } = await api('/api/admin/conversations');
      body.innerHTML = adminTable(
        ['לקוח', 'איש מקצוע', 'הודעות', 'אחרונה', 'עודכן', ''],
        conversations.map((c) => [
          `<b>${esc(c.client_name)}</b><div class="muted small">${esc(c.client_email)}</div>`,
          `<b>${esc(c.pro_name)}</b> · ${esc(c.profession)}
           <div class="muted small">${esc(c.pro_email)}</div>`,
          `<span class="num">${c.messages}</span>`,
          esc(c.last_body.slice(0, 60)), esc(fmtWhen(c.last_message_at)),
          `<button class="link" data-conv="${c.id}" type="button">קריאה</button>`,
        ]));
      $$('[data-conv]', body).forEach((btn) => btn.onclick = () => openAdminChat(+btn.dataset.conv));

    } else {
      const { reviews } = await api(`/api/admin/reviews?max_rating=${filter}`);
      body.innerHTML = adminTable(
        ['לקוח', 'איש מקצוע', 'דירוג', 'תוכן', 'תאריך', ''],
        reviews.map((r) => [
          esc(r.client_name), `${esc(r.pro_name)} · ${esc(r.profession)}`,
          stars(r.rating), esc(r.comment || '—'), esc(fmtWhen(r.created_at)),
          `<button class="link danger-link" data-del="${r.id}" type="button">מחיקה</button>`,
        ]));
      $$('[data-del]', body).forEach((btn) => btn.onclick = async () => {
        if (!confirm('למחוק את הביקורת? הפעולה בלתי הפיכה.')) return;
        try {
          await api(`/api/admin/reviews/${btn.dataset.del}`, { method: 'DELETE' });
          toast('הביקורת נמחקה', 'ok');
          loadAdminTable();
        } catch (err) { toast(err.message, 'bad'); }
      });
    }
  } catch (err) {
    body.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
  }
}

function adminTable(headers, rows) {
  if (!rows.length) return '<div class="empty">אין רשומות להצגה.</div>';
  return `<table class="admin-table">
    <thead><tr>${headers.map((h) => `<th>${h}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((cells) => `<tr>${cells.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody>
  </table>`;
}

async function openAdminChat(conversationId) {
  openModal('<p class="muted">טוען…</p>');
  try {
    const conv = await api('/api/admin/conversations/' + conversationId);
    openModal(`
      <h2>שיחה: ${esc(conv.client_name)} ו${esc(conv.pro_name)}</h2>
      <p class="muted small">תצוגה בלבד — מנהל אינו יכול לכתוב בשיחה.</p>
      <div class="admin-chat">
        ${conv.messages.map((m) => `
          <div class="bubble ${m.from_pro ? 'theirs' : 'mine'}">
            <div class="bubble-body">${esc(m.body)}</div>
            <div class="bubble-meta">${esc(m.sender_name)} · ${esc(fmtWhen(m.created_at))}</div>
          </div>`).join('') || '<p class="muted">אין הודעות.</p>'}
      </div>`);
  } catch (err) {
    openModal(`<h2>שגיאה</h2><p class="err">${esc(err.message)}</p>`);
  }
}

function openAdminEditor(pro) {
  if (!pro) return;
  openModal(`
    <h2>עריכת ${esc(pro.name)}</h2>
    <p class="muted small">${esc(pro.email)}</p>
    <div id="aeErr" class="err hidden"></div>
    <form id="aeForm" class="stack">
      <div class="row">
        <div class="field grow"><label for="aeProfession">מקצוע</label>
          <input id="aeProfession" value="${esc(pro.profession)}"></div>
        <div class="field grow"><label for="aeCity">עיר</label>
          <input id="aeCity" value="${esc(pro.city || '')}"></div>
      </div>
      <div class="field"><label for="aeHeadline">כותרת</label>
        <input id="aeHeadline" value="${esc(pro.headline || '')}"></div>
      <div class="row">
        <div class="field"><label for="aeRate">מחיר לשעה</label>
          <input id="aeRate" type="number" min="0" step="10" value="${pro.hourly_rate}"></div>
        <div class="field"><label for="aeRadius">רדיוס שירות</label>
          <input id="aeRadius" type="number" min="1" max="200" value="${pro.service_radius_km}"></div>
        <div class="field"><label for="aeYears">ותק</label>
          <input id="aeYears" type="number" min="0" max="70" value="${pro.years_experience}"></div>
      </div>
      <div class="row between">
        <label class="check"><input type="checkbox" id="aeVerified" ${pro.verified ? 'checked' : ''}> מאומת</label>
        <label class="check"><input type="checkbox" id="aeActive" ${pro.active ? 'checked' : ''}> פעיל בחיפוש</label>
      </div>
      <div class="row between">
        <button class="danger" id="aeDelete" type="button">מחיקת איש המקצוע</button>
        <button class="primary" type="submit">שמירה</button>
      </div>
    </form>`);

  $('#aeForm').onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api('/api/admin/pros/' + pro.id, { method: 'PATCH', body: {
        profession: $('#aeProfession').value.trim(), city: $('#aeCity').value.trim(),
        headline: $('#aeHeadline').value.trim(), hourly_rate: +$('#aeRate').value,
        service_radius_km: +$('#aeRadius').value, years_experience: +$('#aeYears').value,
        verified: $('#aeVerified').checked, active: $('#aeActive').checked } });
      closeModal(); toast('הפרופיל עודכן', 'ok'); loadAdmin();
    } catch (err) {
      const box = $('#aeErr'); box.textContent = err.message; box.classList.remove('hidden');
    }
  };
  $('#aeDelete').onclick = async () => {
    if (!confirm(`למחוק את הפרופיל של ${pro.name}? ההזמנות והביקורות שלו יימחקו גם הן.`)) return;
    try {
      await api('/api/admin/pros/' + pro.id, { method: 'DELETE' });
      closeModal(); toast('איש המקצוע נמחק', 'ok'); loadAdmin();
    } catch (err) { toast(err.message, 'bad'); }
  };
}

$$('#adminTabs .tab').forEach((tab) => tab.onclick = () => {
  $$('#adminTabs .tab').forEach((t) => t.classList.remove('active'));
  tab.classList.add('active');
  state.adminTab = tab.dataset.tab;
  $('#adminSearch').value = '';
  $('#adminSearch').classList.toggle('hidden', !['pros', 'users'].includes(state.adminTab));
  loadAdmin();
});
let adminTyping;
$('#adminSearch').oninput = () => { clearTimeout(adminTyping); adminTyping = setTimeout(loadAdminTable, 350); };
$('#adminFilter').onchange = loadAdminTable;

/* ---------- אתחול ---------- */
function wireSearchControls() {
  $('#radiusInput').oninput = (e) => { $('#radiusVal').textContent = e.target.value; };
  $('#radiusInput').onchange = runSearch;
  $('#whenSel').onchange = (e) => {
    $('#atField').classList.toggle('hidden', e.target.value !== 'at');
    if (e.target.value === 'at' && !$('#atInput').value) {
      $('#atInput').value = toLocalInput(new Date(Date.now() + 36e5));
    }
    runSearch();
  };
  ['#atInput', '#durationSel', '#sortSel', '#minRating'].forEach((sel) => { $(sel).onchange = runSearch; });
  $$('.fchip').forEach((chip) => chip.onclick = () => {
    const key = chip.dataset.filter;
    state.filters[key] = !state.filters[key];
    chip.classList.toggle('on', state.filters[key]);
    runSearch();
  });
  let typing;
  $('#qText').oninput = () => { clearTimeout(typing); typing = setTimeout(runSearch, 400); };
  $('#maxRate').oninput = () => { clearTimeout(typing); typing = setTimeout(runSearch, 500); };
  $('#addrInput').onkeydown = (e) => { if (e.key === 'Enter') e.preventDefault(); };
}

async function init() {
  wireSearchControls();
  Chat.build(api, setChatBadge);
  $('#chatBtn').onclick = () => { if (state.user) Chat.openInbox(); else show('login'); };
  renderAuth();
  try {
    state.meta = await api('/api/meta');
  } catch (_) {
    state.meta = { professions: [], professions_in_use: [], weekdays: ['ראשון','שני','שלישי','רביעי','חמישי','שישי','שבת'],
                   default_location: { lat: 32.0853, lng: 34.7818 }, default_radius_km: 15, maps_key: '' };
  }
  const saved = localStorage.getItem('pronear_loc');
  if (saved) { try { const l = JSON.parse(saved); setLocation(l.lat, l.lng, l.label); } catch (_) {} }
  if (!state.loc) useDefaultLocation();
  renderCategories();
  await refreshMe();
  show(state.user ? (VIEW_FOR_ROLE[state.user.role] || 'home') : 'login');
  // רענון עדין של המונה כשהצ'אט סגור
  setInterval(() => { if (state.user) refreshChatBadge(); }, 30000);
}

init();
