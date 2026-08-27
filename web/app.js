/* ===== קרוב — לוגיקת צד לקוח (ללא ספריות) ===== */
'use strict';

const state = {
  token: localStorage.getItem('pronear_token') || null,
  user: null,
  professional: null,
  meta: null,
  loc: null,
  results: [],
  profession: '',
  bookingRole: 'client',
  slots: [],
};

/* ---------- עזרים ---------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = (n) => '₪' + Number(n || 0).toLocaleString('he-IL');
const initials = (name) => String(name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join('');

function toast(message, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = message;
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

function stars(avg) {
  if (!avg) return '<span class="muted small">אין דירוג עדיין</span>';
  const full = Math.round(avg);
  return `<span class="stars">${'★'.repeat(full)}${'☆'.repeat(5 - full)}</span>`;
}

function fmtWhen(ts) {
  const d = new Date(ts * 1000);
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  const tomorrow = new Date(today.getTime() + 864e5).toDateString() === d.toDateString();
  const time = d.toLocaleTimeString('he-IL', { hour: '2-digit', minute: '2-digit' });
  if (sameDay) return `היום ${time}`;
  if (tomorrow) return `מחר ${time}`;
  return d.toLocaleDateString('he-IL', { weekday: 'short', day: 'numeric', month: 'numeric' }) + ' ' + time;
}

function toLocalInput(date) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/* ---------- שכבת API ---------- */
async function api(path, { method = 'GET', body = null } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (state.token) headers.Authorization = 'Bearer ' + state.token;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : null });
  let data = {};
  try { data = await res.json(); } catch (_) { /* גוף ריק */ }
  if (!res.ok) {
    const err = new Error(data.error || `שגיאה ${res.status}`);
    err.status = res.status;
    err.field = data.field;
    throw err;
  }
  return data;
}

/* ---------- מיקום ---------- */
function setLocation(lat, lng, label) {
  state.loc = { lat, lng, label };
  $('#locLabel').textContent = label;
  localStorage.setItem('pronear_loc', JSON.stringify(state.loc));
}

function detectLocation() {
  const saved = localStorage.getItem('pronear_loc');
  if (saved) {
    try { const loc = JSON.parse(saved); setLocation(loc.lat, loc.lng, loc.label); } catch (_) {}
  }
  if (!navigator.geolocation) {
    if (!state.loc) useDefaultLocation();
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      setLocation(+pos.coords.latitude.toFixed(5), +pos.coords.longitude.toFixed(5), 'המיקום הנוכחי שלי');
      runSearch();
    },
    () => { if (!state.loc) { useDefaultLocation(); runSearch(); } },
    { timeout: 7000, maximumAge: 300000 }
  );
}

function useDefaultLocation() {
  const def = state.meta ? state.meta.default_location : { lat: 32.0853, lng: 34.7818 };
  setLocation(def.lat, def.lng, 'תל אביב (ברירת מחדל)');
}

function openLocationPicker() {
  openModal(`
    <h2>מאיפה לחפש?</h2>
    <p class="muted small">אפשר לאתר אוטומטית או להזין קואורדינטות ידנית.</p>
    <div class="stack">
      <button class="primary" id="mlAuto" type="button">אתר את המיקום שלי</button>
      <div class="row">
        <div class="field grow"><label>קו רוחב</label><input id="mlLat" type="number" step="0.0001" value="${state.loc ? state.loc.lat : ''}"></div>
        <div class="field grow"><label>קו אורך</label><input id="mlLng" type="number" step="0.0001" value="${state.loc ? state.loc.lng : ''}"></div>
      </div>
      <div class="field"><label>שם המקום (לתצוגה)</label><input id="mlLabel" value="${esc(state.loc ? state.loc.label : '')}"></div>
      <button class="ghost" id="mlSave" type="button">שמירה</button>
    </div>`);
  $('#mlAuto').onclick = () => { closeModal(); detectLocation(); };
  $('#mlSave').onclick = () => {
    const lat = parseFloat($('#mlLat').value), lng = parseFloat($('#mlLng').value);
    if (Number.isNaN(lat) || Number.isNaN(lng)) return toast('קואורדינטות לא תקינות', 'bad');
    setLocation(lat, lng, $('#mlLabel').value.trim() || 'מיקום מותאם');
    closeModal();
    runSearch();
  };
}

/* ---------- חלוניות ---------- */
function openModal(html) {
  $('#modal').innerHTML = `<button class="modal-close" type="button" aria-label="סגירה">✕</button>` + html;
  $('#overlay').classList.remove('hidden');
  $('.modal-close').onclick = closeModal;
}
function closeModal() { $('#overlay').classList.add('hidden'); $('#modal').innerHTML = ''; }
$('#overlay').addEventListener('click', (e) => { if (e.target.id === 'overlay') closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

/* ---------- ניווט ---------- */
function show(view) {
  $$('.view').forEach((el) => el.classList.add('hidden'));
  $('#view-' + view).classList.remove('hidden');
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (view === 'bookings') loadBookings();
  if (view === 'dashboard') loadDashboard();
}
$$('[data-nav]').forEach((btn) => btn.addEventListener('click', () => {
  const view = btn.dataset.nav;
  if (view !== 'search' && !state.user) return openAuth();
  show(view);
}));

/* ---------- הרשאות ותצוגה ---------- */
function applyAuthUI() {
  const authed = !!state.user;
  $$('.auth-only').forEach((el) => el.classList.toggle('hidden', !authed));
  $$('.anon-only').forEach((el) => el.classList.toggle('hidden', authed));
  $$('.pro-only').forEach((el) => el.classList.toggle('hidden', !state.professional));
}

async function refreshMe() {
  if (!state.token) { state.user = null; state.professional = null; applyAuthUI(); return; }
  try {
    const data = await api('/api/auth/me');
    state.user = data.user;
    state.professional = data.professional || null;
  } catch (_) {
    state.token = null; state.user = null; state.professional = null;
    localStorage.removeItem('pronear_token');
  }
  applyAuthUI();
  if (state.user) refreshBookingsBadge();
}

async function refreshBookingsBadge() {
  try {
    const data = await api('/api/bookings?status=pending');
    const badge = $('#bookingsBadge');
    badge.textContent = data.bookings.length;
    badge.classList.toggle('hidden', data.bookings.length === 0);
  } catch (_) {}
}

/* ---------- כניסה / הרשמה ---------- */
function openAuth(mode = 'login') {
  const isLogin = mode === 'login';
  openModal(`
    <h2>${isLogin ? 'כניסה לחשבון' : 'הרשמה'}</h2>
    <form id="authForm" class="stack">
      <div id="authErr" class="err hidden"></div>
      ${isLogin ? '' : `<div class="field"><label>שם מלא</label><input id="auName" required minlength="2"></div>`}
      <div class="field"><label>אימייל</label><input id="auEmail" type="email" required autocomplete="email"></div>
      ${isLogin ? '' : `<div class="field"><label>טלפון</label><input id="auPhone" placeholder="050-0000000"></div>`}
      <div class="field"><label>סיסמה</label><input id="auPass" type="password" required minlength="8" autocomplete="current-password"></div>
      <button class="primary" type="submit">${isLogin ? 'כניסה' : 'יצירת חשבון'}</button>
      <button class="link" id="authSwitch" type="button">
        ${isLogin ? 'אין לך חשבון? הרשמה' : 'יש לך כבר חשבון? כניסה'}
      </button>
    </form>`);
  $('#authSwitch').onclick = () => openAuth(isLogin ? 'register' : 'login');
  $('#authForm').onsubmit = async (e) => {
    e.preventDefault();
    const payload = { email: $('#auEmail').value.trim(), password: $('#auPass').value };
    if (!isLogin) { payload.name = $('#auName').value.trim(); payload.phone = $('#auPhone').value.trim(); }
    try {
      const data = await api(isLogin ? '/api/auth/login' : '/api/auth/register', { method: 'POST', body: payload });
      state.token = data.token;
      localStorage.setItem('pronear_token', data.token);
      await refreshMe();
      closeModal();
      toast(`שלום ${data.user.name}!`, 'ok');
    } catch (err) {
      const box = $('#authErr');
      box.textContent = err.message;
      box.classList.remove('hidden');
    }
  };
}
$('#loginBtn').onclick = () => openAuth();
$('#logoutBtn').onclick = async () => {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch (_) {}
  state.token = null; state.user = null; state.professional = null;
  localStorage.removeItem('pronear_token');
  applyAuthUI(); show('search');
  toast('התנתקת');
};
$('#locChip').onclick = openLocationPicker;

/* ---------- חיפוש ---------- */
function buildQuery() {
  const params = new URLSearchParams();
  params.set('lat', state.loc.lat);
  params.set('lng', state.loc.lng);
  params.set('radius_km', $('#radiusInput').value);
  params.set('duration', $('#durationSel').value);
  params.set('sort', $('#sortSel').value);
  const text = $('#qText').value.trim();
  if (text) params.set('q', text);
  if (state.profession) params.set('profession', state.profession);
  const when = $('#whenSel').value;
  if (when === 'at' && $('#atInput').value) {
    params.set('when', 'at');
    params.set('at', $('#atInput').value);
  }
  if (when === 'soon') params.set('sort', 'soonest');
  if ($('#onlyNow').checked) params.set('available_now', '1');
  if ($('#onlyVerified').checked) params.set('verified', '1');
  if ($('#maxRate').value) params.set('max_rate', $('#maxRate').value);
  if ($('#minRating').value) params.set('min_rating', $('#minRating').value);
  return params.toString();
}

let searchSeq = 0;
async function runSearch() {
  if (!state.loc) return;
  const seq = ++searchSeq;
  $('#results').innerHTML = '<div class="skeleton"></div>'.repeat(3);
  try {
    const data = await api('/api/search?' + buildQuery());
    if (seq !== searchSeq) return;   // תגובה מאוחרת של חיפוש ישן
    state.results = data.results;
    renderResults(data);
    renderMap(data);
  } catch (err) {
    $('#results').innerHTML = `<div class="empty">${esc(err.message)}</div>`;
  }
}

function renderResults(data) {
  const box = $('#results');
  $('#resultsTitle').textContent = state.profession ? `${state.profession} באזור שלך` : 'תוצאות באזור שלך';
  $('#resultsMeta').textContent =
    `${data.total} נמצאו · ${data.available_now_count} פנויים עכשיו · רדיוס ${data.query.radius_km} ק״מ`;

  if (!data.results.length) {
    box.innerHTML = `<div class="empty">
      <h3>לא נמצאו אנשי מקצוע מתאימים</h3>
      <p>אפשר להגדיל את הרדיוס, לבטל סינונים או לחפש בזמן אחר.</p></div>`;
    return;
  }

  box.innerHTML = data.results.map((pro) => {
    const availPill = pro.available_now
      ? '<span class="pill free">● פנוי עכשיו</span>'
      : `<span class="pill soon">${esc(pro.next_free ? fmtWhen(pro.next_free.start) : 'ללא זמינות')}</span>`;
    const ring = `conic-gradient(var(--accent) ${pro.score * 3.6}deg, var(--surface-2) 0)`;
    return `
    <article class="card pro-card" data-pro="${pro.id}">
      <div class="avatar">${esc(initials(pro.name))}</div>
      <div class="pro-main">
        <div class="pro-name">
          <b>${esc(pro.name)}</b>
          <span class="muted">· ${esc(pro.profession)}</span>
          ${pro.verified ? '<span class="pill verified">מאומת</span>' : ''}
          ${pro.emergency ? '<span class="pill emergency">חירום</span>' : ''}
        </div>
        <div class="pro-sub">${esc(pro.headline || '')}</div>
        <div class="facts">
          <span>📍 <b>${pro.distance_km}</b> ק״מ${pro.city ? ' · ' + esc(pro.city) : ''}</span>
          <span>⏱ ${esc(pro.eta_text)}</span>
          <span>💰 <b>${money(pro.hourly_rate)}</b>/שעה</span>
          <span>${stars(pro.rating.avg)} ${pro.rating.count ? `<b>${pro.rating.avg}</b> (${pro.rating.count})` : ''}</span>
        </div>
        ${pro.tags.length ? `<div class="tagline">${pro.tags.slice(0, 5).map((t) => `<span class="tag">${esc(t)}</span>`).join('')}</div>` : ''}
      </div>
      <div class="pro-side">
        <div class="score-ring" style="background:${ring}" title="ציון התאמה"><span>${pro.score}</span></div>
        ${availPill}
        <button class="primary" data-book="${pro.id}" type="button">הזמנה</button>
      </div>
    </article>`;
  }).join('');

  $$('.pro-card', box).forEach((card) => card.addEventListener('click', (e) => {
    const id = +card.dataset.pro;
    if (e.target.dataset.book) openBooking(id); else openProfile(id);
  }));
}

/* ---------- מפה (SVG מקומי, ללא שירות חיצוני) ---------- */
function renderMap(data) {
  const svg = $('#map');
  const size = 320, center = size / 2;
  const radius = parseFloat(data.query.radius_km) || 15;
  const scale = (center - 22) / radius;              // פיקסלים לק"מ
  const kmPerLng = 111.320 * Math.cos(state.loc.lat * Math.PI / 180);

  const project = (lat, lng) => ({
    // ציר x הפוך: במפה RTL מזרח נשאר ימינה, לכן נשמר כיוון גאוגרפי רגיל
    x: center + (lng - state.loc.lng) * kmPerLng * scale,
    y: center - (lat - state.loc.lat) * 110.574 * scale,
  });

  const rings = [radius / 3, (radius * 2) / 3, radius].map((r) => `
    <circle cx="${center}" cy="${center}" r="${r * scale}" fill="none" stroke="var(--line)" stroke-dasharray="3 4"/>
    <text x="${center}" y="${center + r * scale - 5}" font-size="8.5" fill="var(--muted)" text-anchor="middle"
      stroke="var(--surface-2)" stroke-width="3" paint-order="stroke">${Math.round(r)} ק״מ</text>`).join('');

  const dots = data.results.map((pro) => {
    const p = project(pro.lat, pro.lng);
    const color = pro.available_now ? 'var(--green)' : 'var(--amber)';
    const r = 5 + Math.min(4, pro.score / 25);
    return `<g class="pro-dot" data-pro="${pro.id}">
      <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r.toFixed(1)}" fill="${color}"
        fill-opacity=".85" stroke="var(--surface)" stroke-width="1"/>
      <title>${esc(pro.name)} · ${esc(pro.profession)} · ${pro.distance_km} ק״מ</title></g>`;
  }).join('');

  svg.innerHTML = `${rings}
    ${dots}
    <circle cx="${center}" cy="${center}" r="14" fill="var(--accent)" fill-opacity=".18"/>
    <circle cx="${center}" cy="${center}" r="7" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>`;
  $('#mapMeta').textContent = `${data.results.length} על המפה`;
  $$('.pro-dot', svg).forEach((dot) => dot.addEventListener('click', () => openProfile(+dot.dataset.pro)));
}

/* ---------- פרופיל איש מקצוע ---------- */
async function openProfile(proId) {
  openModal('<p class="muted">טוען…</p>');
  try {
    const pro = await api('/api/pros/' + proId);
    const listed = state.results.find((r) => r.id === proId);
    const parts = listed ? listed.score_parts : null;
    const labels = { availability: 'זמינות', distance: 'קרבה', rating: 'דירוג', price: 'מחיר', trust: 'אמינות' };
    openModal(`
      <h2>${esc(pro.name)} · ${esc(pro.profession)}</h2>
      <div class="pro-name" style="margin-bottom:8px">
        ${pro.verified ? '<span class="pill verified">מאומת</span>' : ''}
        ${pro.available_now ? '<span class="pill free">פנוי עכשיו</span>'
          : (pro.next_free ? `<span class="pill soon">פנוי ${esc(fmtWhen(pro.next_free.start))}</span>` : '')}
        ${pro.emergency ? '<span class="pill emergency">קריאות חירום</span>' : ''}
      </div>
      <p>${esc(pro.headline || '')}</p>
      <p class="muted small">${esc(pro.bio || '')}</p>
      <div class="facts" style="margin:10px 0">
        <span>💰 <b>${money(pro.hourly_rate)}</b>/שעה</span>
        <span>🧰 ${pro.years_experience} שנות ניסיון</span>
        <span>✅ ${pro.jobs_done} עבודות שהושלמו</span>
        <span>📏 רדיוס שירות ${pro.service_radius_km} ק״מ</span>
        ${listed ? `<span>📍 ${listed.distance_km} ק״מ ממך</span>` : ''}
        ${pro.phone ? `<span>📞 ${esc(pro.phone)}</span>` : ''}
      </div>
      ${parts ? `<h3 class="small muted">מדוע הוא הותאם לך</h3><div class="score-bars">${
        Object.entries(parts).map(([k, v]) =>
          `<div><span>${labels[k] || k}</span><span class="bar"><i style="width:${v}%"></i></span><span>${Math.round(v)}</span></div>`).join('')
      }</div>` : ''}
      <h3 class="small muted">לוח זמינות שבועי</h3>
      <p class="small">${pro.availability.length
        ? pro.availability.map((a) => `${esc(a.weekday_name)} ${a.start}–${a.end}`).join(' · ')
        : 'לא הוגדר לוח זמינות'}</p>
      <div class="row" style="margin:14px 0">
        <button class="primary" id="pfBook" type="button">בחירת מועד והזמנה</button>
      </div>
      <h3 class="small muted">ביקורות (${pro.rating.count})</h3>
      ${pro.reviews.length ? pro.reviews.map((r) => `
        <div class="review"><b>${esc(r.name)}</b> ${stars(r.rating)}<div class="muted small">${esc(r.comment)}</div></div>`).join('')
        : '<p class="muted small">אין עדיין ביקורות.</p>'}`);
    $('#pfBook').onclick = () => openBooking(proId);
  } catch (err) {
    openModal(`<h2>שגיאה</h2><p class="err">${esc(err.message)}</p>`);
  }
}

/* ---------- הזמנה ---------- */
async function openBooking(proId) {
  if (!state.user) { openAuth(); return toast('צריך להתחבר כדי להזמין'); }
  openModal('<p class="muted">טוען מועדים פנויים…</p>');
  try {
    const pro = await api('/api/pros/' + proId);
    const duration = Math.max(pro.min_job_minutes, +$('#durationSel').value);
    const data = await api(`/api/pros/${proId}/slots?days=7&duration=${duration}&step=30`);
    state.slots = data.slots;
    if (!data.slots.length) {
      return openModal(`<h2>${esc(pro.name)}</h2><p>אין מועדים פנויים בשבוע הקרוב לעבודה של ${duration} דקות.</p>`);
    }
    let currentDay = '';
    const slotsHtml = data.slots.slice(0, 60).map((slot, i) => {
      const day = new Date(slot.start * 1000).toLocaleDateString('he-IL', { weekday: 'long', day: 'numeric', month: 'numeric' });
      const header = day !== currentDay ? `<div class="slot-day">${esc(day)}</div>` : '';
      currentDay = day;
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
        <div class="field"><label>כתובת</label><input id="bkAddress" placeholder="רחוב, מספר, עיר" required></div>
        <div class="field"><label>מה צריך לעשות?</label><textarea id="bkNote" rows="2" placeholder="תיאור קצר של העבודה"></textarea></div>
        <div class="row between">
          <span class="muted small">עלות משוערת: <b id="bkPrice">${money(Math.round(pro.hourly_rate * duration / 60))}</b></span>
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
          pro_id: proId,
          start: picked.start,
          duration_minutes: duration,
          address: $('#bkAddress').value.trim(),
          note: $('#bkNote').value.trim(),
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

/* ---------- ההזמנות שלי ---------- */
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
      return `<article class="card booking">
        <div>
          <b>${who}</b>
          <div class="muted small">${esc(fmtWhen(b.start))} · ${b.duration_minutes} דק׳ · ${esc(b.address || 'ללא כתובת')}</div>
          ${b.note ? `<div class="muted small">📝 ${esc(b.note)}</div>` : ''}
          ${b.contact_phone ? `<div class="small">📞 ${esc(b.contact_phone)}</div>` : ''}
        </div>
        <div class="row" style="align-items:center">
          <span class="muted small">${money(b.estimated_price)}</span>
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
      <div class="field"><label>דירוג</label>
        <select id="revRating">
          <option value="5">★★★★★ מצוין</option><option value="4">★★★★ טוב</option>
          <option value="3">★★★ בסדר</option><option value="2">★★ חלש</option><option value="1">★ גרוע</option>
        </select></div>
      <div class="field"><label>מה תרצו לספר?</label><textarea id="revComment" rows="3"></textarea></div>
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

/* ---------- אזור אישי ---------- */
const DEFAULT_AVAIL = [0, 1, 2, 3, 4].map((d) => ({ weekday: d, start: '08:00', end: '17:00' }))
  .concat([{ weekday: 5, start: '08:00', end: '13:00' }]);

function renderAvailEditor(rules) {
  const byDay = {};
  (rules && rules.length ? rules : DEFAULT_AVAIL).forEach((r) => { byDay[r.weekday] = r; });
  $('#availEditor').innerHTML = state.meta.weekdays.map((name, day) => {
    const rule = byDay[day];
    return `<div class="avail-row ${rule ? '' : 'off'}" data-day="${day}">
      <input type="checkbox" ${rule ? 'checked' : ''} data-on>
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
    .map((row) => ({
      weekday: +row.dataset.day,
      start: $('[data-start]', row).value,
      end: $('[data-end]', row).value,
    }));
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
    loadTimeOff();
  } else {
    if (state.loc) { $('#pfLat').value = state.loc.lat; $('#pfLng').value = state.loc.lng; }
    renderAvailEditor(null);
  }
  applyAuthUI();
}

$('#useMyLoc').onclick = () => {
  if (!state.loc) return toast('אין מיקום זמין', 'bad');
  $('#pfLat').value = state.loc.lat;
  $('#pfLng').value = state.loc.lng;
};

$('#proForm').onsubmit = async (e) => {
  e.preventDefault();
  const body = {
    profession: $('#pfProfession').value.trim(),
    city: $('#pfCity').value.trim(),
    headline: $('#pfHeadline').value.trim(),
    bio: $('#pfBio').value.trim(),
    hourly_rate: +$('#pfRate').value,
    service_radius_km: +$('#pfRadius').value,
    min_job_minutes: +$('#pfMin').value,
    years_experience: +$('#pfYears').value,
    tags: $('#pfTags').value,
    emergency: $('#pfEmergency').checked,
    active: $('#pfActive').checked,
    lat: +$('#pfLat').value,
    lng: +$('#pfLng').value,
    availability: collectAvailability(),
  };
  try {
    const pro = state.professional
      ? await api('/api/pros/' + state.professional.id, { method: 'PUT', body })
      : await api('/api/pros', { method: 'POST', body });
    state.professional = pro;
    applyAuthUI();
    renderAvailEditor(pro.availability);
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

async function loadTimeOff() {
  if (!state.professional) return;
  try {
    const data = await api(`/api/pros/${state.professional.id}/time-off`);
    $('#timeOffList').innerHTML = data.time_off.length
      ? data.time_off.map((off) => `<li><span>${esc(fmtWhen(off.start))} – ${esc(fmtWhen(off.end))} ${off.reason ? '· ' + esc(off.reason) : ''}</span>
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

/* ---------- אתחול ---------- */
function renderProfessionChips() {
  const inUse = state.meta.professions_in_use.map((p) => p.name);
  const list = inUse.length ? inUse.slice(0, 12) : state.meta.professions.slice(0, 12);
  $('#professionChips').innerHTML =
    `<button class="chip on" data-prof="" type="button">הכול</button>` +
    list.map((p) => `<button class="chip" data-prof="${esc(p)}" type="button">${esc(p)}</button>`).join('');
  $$('#professionChips .chip').forEach((chip) => chip.onclick = () => {
    $$('#professionChips .chip').forEach((c) => c.classList.remove('on'));
    chip.classList.add('on');
    state.profession = chip.dataset.prof;
    runSearch();
  });
}

function wireSearchControls() {
  $('#searchForm').onsubmit = (e) => { e.preventDefault(); runSearch(); };
  $('#radiusInput').oninput = (e) => { $('#radiusVal').textContent = e.target.value; };
  $('#radiusInput').onchange = runSearch;
  $('#whenSel').onchange = (e) => {
    $('#atField').classList.toggle('hidden', e.target.value !== 'at');
    if (e.target.value === 'at' && !$('#atInput').value) {
      $('#atInput').value = toLocalInput(new Date(Date.now() + 36e5));
    }
    runSearch();
  };
  ['#atInput', '#durationSel', '#sortSel', '#onlyNow', '#onlyVerified', '#minRating']
    .forEach((sel) => { $(sel).onchange = runSearch; });
  let typing;
  $('#qText').oninput = () => { clearTimeout(typing); typing = setTimeout(runSearch, 400); };
  $('#maxRate').oninput = () => { clearTimeout(typing); typing = setTimeout(runSearch, 500); };
}

async function init() {
  wireSearchControls();
  try {
    state.meta = await api('/api/meta');
  } catch (_) {
    state.meta = { professions: [], professions_in_use: [], weekdays: ['ראשון','שני','שלישי','רביעי','חמישי','שישי','שבת'],
                   default_location: { lat: 32.0853, lng: 34.7818 }, default_radius_km: 15 };
  }
  renderProfessionChips();
  await refreshMe();
  if (!state.loc) useDefaultLocation();
  runSearch();
  detectLocation();
}

init();
