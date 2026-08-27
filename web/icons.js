/* ===== אייקוני קטגוריה ותמונות שנוצרות בקוד =====
   כל אייקון הוא צורה גיאומטרית פשוטה על רשת 24x24, בקו אחיד -
   כך הם נראים כמשפחה אחת גם כשהם מוגדלים לאריחי הקטגוריות. */
'use strict';

const ICON_PATHS = {
  'חשמלאי':                'M13 2 4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5z',
  'אינסטלטור':             'M12 3c3.2 3.6 5 6.4 5 9a5 5 0 0 1-10 0c0-2.6 1.8-5.4 5-9z',
  'מנעולן':                'M15.5 3a5.5 5.5 0 1 0 3.9 9.4L21 14l-1.5 1.5L18 14l-1.5 1.5L15 14l-2.4 2.4A5.5 5.5 0 0 0 15.5 3zm0 3.6a1.6 1.6 0 1 1 0 3.2 1.6 1.6 0 0 1 0-3.2z',
  'טכנאי מזגנים':          'M12 2v20M4.5 6.5 19.5 17.5M19.5 6.5 4.5 17.5M8 4l4 3 4-3M8 20l4-3 4 3',
  'טכנאי מחשבים':          'M4 5h16v10H4zM2 19h20M9 15h6',
  'הובלות':                'M2 7h11v9H2zM13 10h4l3 3v3h-7zM6 19a2 2 0 1 0 0-.1M17 19a2 2 0 1 0 0-.1',
  'שיפוצניק':              'M3 21 9 15M8 14l-3-3 8-8 3 3zM14 14h7v7h-7z',
  'נגר':                   'M3 8h12l5 5-3 3-5-5H3zM3 16h9',
  'צבע':                   'M4 4h13v6H4zM10 10v4h3v7h-3',
  'גנן':                   'M12 21c0-6 3-11 9-13-1 7-4 11-9 13zM12 21C9 16 6 13 3 12c1 5 4 8 9 9z',
  'מנקה':                  'M9 3h6v6H9zM7 9h10l1 12H6zM12 13v4',
  'טכנאי מכונות כביסה':    'M4 3h16v18H4zM12 8a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM7 6h2',
  'מורה פרטי':             'M3 5h8v14H3zM13 5h8v14h-8zM11 7c.7-1 1.3-1 2 0',
  'מאמן כושר':             'M3 9v6M6 6v12M18 6v12M21 9v6M6 12h12',
  'ספר':                   'M6 3v9M18 3v9M6 12a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM18 12a3 3 0 1 0 0 6 3 3 0 0 0 0-6z',
  'קוסמטיקאית':            'M12 2l2.2 5.3L20 9l-4.5 3.8L17 19l-5-3-5 3 1.5-6.2L4 9l5.8-1.7z',
  'צלם':                   'M3 7h4l2-3h6l2 3h4v13H3zM12 10a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
  'וטרינר':                'M12 12c3 0 5 2.2 5 4.5S14.8 21 12 21s-5-2.2-5-4.5S9 12 12 12zM6.5 5a2 2 0 1 1 0 4 2 2 0 0 1 0-4zM17.5 5a2 2 0 1 1 0 4 2 2 0 0 1 0-4z',
  'בייביסיטר':             'M12 3a5 5 0 1 1 0 10 5 5 0 0 1 0-10zM4 21c0-4 3.6-6 8-6s8 2 8 6',
};
const ICON_FALLBACK = 'M14.5 3.5a5 5 0 0 0-6.2 6.2L3 15l3 3 5.3-5.3a5 5 0 0 0 6.2-6.2L15 9l-2-2z';

// גוון קבוע לכל מקצוע - אותו מקצוע מקבל תמיד את אותו צבע
function hueFor(text) {
  let hash = 0;
  for (let i = 0; i < String(text).length; i++) hash = (hash * 31 + String(text).charCodeAt(i)) % 360;
  return hash;
}

function iconSvg(profession, size = 26, color = 'currentColor') {
  const path = ICON_PATHS[profession] || ICON_FALLBACK;
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="${color}"
    stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>`;
}

// כרטיס תמונה שנוצר בקוד: מדרג צבע לפי המקצוע + האייקון כסימן מים
function coverSvg(profession, name, width = 96, height = 96) {
  const hue = hueFor(profession);
  const id = 'g' + hue + Math.round(width);
  const letters = String(name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join('');
  // direction=ltr: בהקשר RTL עוגן הטקסט מתהפך והכיתוב נגזר מחוץ לקנבס
  return `<svg viewBox="0 0 96 96" width="${width}" height="${height}" direction="ltr"
      role="img" aria-label="${name || profession}">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="hsl(${hue} 62% 56%)"/><stop offset="1" stop-color="hsl(${(hue + 38) % 360} 60% 42%)"/>
    </linearGradient></defs>
    <rect width="96" height="96" rx="18" fill="url(#${id})"/>
    <g transform="translate(19.2 11) scale(2.4)" opacity=".95" stroke="#fff" fill="none"
       stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <path d="${ICON_PATHS[profession] || ICON_FALLBACK}"/></g>
    <text x="48" y="88" text-anchor="middle" font-family="Rubik,Segoe UI,sans-serif" font-size="17"
      font-weight="500" fill="#fff" fill-opacity=".92">${letters}</text>
  </svg>`;
}

// תמונת פרופיל: קובץ שהועלה אם יש, אחרת הכרטיס שנוצר בקוד
function avatarHtml(pro, size = 56) {
  if (pro.photo) {
    return `<img class="avatar-img" src="${pro.photo}" width="${size}" height="${size}"
      alt="${(pro.name || '').replace(/"/g, '&quot;')}" loading="lazy">`;
  }
  return coverSvg(pro.profession, pro.name, size, size);
}
