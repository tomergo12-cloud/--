/* ===== שכבת מפה =====
   ספק ראשי: Google Maps. אם אין מפתח, או שהטעינה נכשלה (מפתח שגוי,
   חיוב כבוי, אין רשת) - נופלים חזרה למפת SVG מקומית, כדי שהאפליקציה
   תמשיך לעבוד במקום להציג ריבוע ריק. */
'use strict';

const MapLayer = (() => {
  let provider = 'local';          // 'google' | 'local'
  let gmap = null;                 // מופע google.maps.Map
  let markers = [];
  let meMarker = null;
  let infoWindow = null;
  let onPick = null;               // callback בלחיצה על איש מקצוע
  let container = null;
  let center = { lat: 32.0853, lng: 34.7818 };
  let radiusCircle = null;
  let lastData = { results: [], radius: 15 };
  let statusEl = null;

  function setStatus(text, tone = '') {
    if (!statusEl) return;
    statusEl.textContent = text || '';
    statusEl.className = 'map-status ' + tone;
  }

  /* ---------- טעינת Google Maps ---------- */
  function loadGoogle(key) {
    return new Promise((resolve, reject) => {
      if (window.google && window.google.maps) return resolve();
      // Google קורא לפונקציה הזו כשהמפתח נדחה (חיוב כבוי, הפניה חסומה וכו')
      window.gm_authFailure = () => reject(new Error('auth'));
      const script = document.createElement('script');
      script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}`
        + '&libraries=places&language=he&region=IL&loading=async';
      script.async = true;
      script.onerror = () => reject(new Error('network'));
      script.onload = () => resolve();
      document.head.appendChild(script);
      setTimeout(() => reject(new Error('timeout')), 10000);
    });
  }

  async function init(opts) {
    container = opts.container;
    statusEl = opts.statusEl || null;
    center = opts.center || center;
    onPick = opts.onPick || null;

    if (!opts.key) {
      provider = 'local';
      setStatus('מפה מקומית — הוסיפו מפתח Google Maps למפה מלאה', 'hint');
      return provider;
    }
    try {
      await loadGoogle(opts.key);
      gmap = new google.maps.Map(container, {
        center, zoom: 12, mapTypeControl: false, streetViewControl: false,
        fullscreenControl: false, clickableIcons: false,
        styles: [{ featureType: 'poi', stylers: [{ visibility: 'off' }] }],
      });
      infoWindow = new google.maps.InfoWindow();
      meMarker = new google.maps.Marker({
        map: gmap, position: center, title: 'המיקום שלי', zIndex: 999,
        icon: dotIcon(getComputedStyle(document.body).getPropertyValue('--accent') || '#0f6fff', 9),
      });
      provider = 'google';
      setStatus('');
      return provider;
    } catch (err) {
      provider = 'local';
      const why = err && err.message === 'auth'
        ? 'מפתח Google Maps נדחה — בודקים אותו בקונסולת Google Cloud. בינתיים מוצגת מפה מקומית.'
        : 'לא הצלחנו לטעון את Google Maps. בינתיים מוצגת מפה מקומית.';
      setStatus(why, 'warn');
      return provider;
    }
  }

  function dotIcon(color, size) {
    return {
      path: google.maps.SymbolPath.CIRCLE,
      scale: size,
      fillColor: color.trim() || '#0f6fff',
      fillOpacity: 1,
      strokeColor: '#ffffff',
      strokeWeight: 2,
    };
  }

  /* ---------- ציור תוצאות ---------- */
  function render(data, loc) {
    center = { lat: loc.lat, lng: loc.lng };
    lastData = { results: data.results || [], radius: data.query ? data.query.radius_km : 15 };
    if (provider === 'google' && gmap) return renderGoogle();
    return renderLocal();
  }

  function clearMarkers() {
    markers.forEach((m) => m.setMap(null));
    markers = [];
  }

  function renderGoogle() {
    clearMarkers();
    meMarker.setPosition(center);
    gmap.setCenter(center);

    if (radiusCircle) radiusCircle.setMap(null);
    radiusCircle = new google.maps.Circle({
      map: gmap, center, radius: lastData.radius * 1000,
      strokeColor: '#0f6fff', strokeOpacity: .35, strokeWeight: 1,
      fillColor: '#0f6fff', fillOpacity: .05, clickable: false,
    });
    gmap.fitBounds(radiusCircle.getBounds());

    const style = getComputedStyle(document.body);
    const green = style.getPropertyValue('--green') || '#0b8a4e';
    const amber = style.getPropertyValue('--amber') || '#a8650a';

    lastData.results.forEach((pro) => {
      const marker = new google.maps.Marker({
        map: gmap, position: { lat: pro.lat, lng: pro.lng },
        title: `${pro.name} · ${pro.profession}`,
        icon: dotIcon(pro.available_now ? green : amber, 7),
      });
      marker.addListener('click', () => {
        infoWindow.setContent(
          `<div style="font-family:Rubik,sans-serif;direction:rtl;min-width:150px">
             <b>${escapeHtml(pro.name)}</b><br>
             <span style="color:#5a6779">${escapeHtml(pro.profession)} · ${pro.distance_km} ק״מ</span><br>
             <span style="color:${pro.available_now ? '#0b8a4e' : '#a8650a'}">
               ${pro.available_now ? 'פנוי עכשיו' : escapeHtml(pro.eta_text)}</span>
           </div>`);
        infoWindow.open(gmap, marker);
        if (onPick) onPick(pro.id);
      });
      markers.push(marker);
    });
  }

  /* ---------- מפת SVG מקומית ---------- */
  function renderLocal() {
    const size = 320, mid = size / 2;
    const radius = lastData.radius || 15;
    const scale = (mid - 24) / radius;
    const kmPerLng = 111.320 * Math.cos(center.lat * Math.PI / 180);
    const project = (lat, lng) => ({
      x: mid + (lng - center.lng) * kmPerLng * scale,
      y: mid - (lat - center.lat) * 110.574 * scale,
    });

    const rings = [radius / 3, (radius * 2) / 3, radius].map((r) => `
      <circle cx="${mid}" cy="${mid}" r="${(r * scale).toFixed(1)}" fill="none"
        stroke="var(--line)" stroke-dasharray="3 4"/>
      <text x="${mid}" y="${(mid + r * scale - 5).toFixed(1)}" font-size="8.5" fill="var(--muted)"
        text-anchor="middle" stroke="var(--surface-2)" stroke-width="3"
        paint-order="stroke">${Math.round(r)} ק״מ</text>`).join('');

    const dots = lastData.results.map((pro) => {
      const p = project(pro.lat, pro.lng);
      const color = pro.available_now ? 'var(--green)' : 'var(--amber)';
      const r = 5 + Math.min(4, pro.score / 25);
      return `<g class="map-dot" data-pro="${pro.id}">
        <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${r.toFixed(1)}" fill="${color}"
          fill-opacity=".85" stroke="var(--surface)" stroke-width="1"/>
        <title>${escapeHtml(pro.name)} · ${escapeHtml(pro.profession)} · ${pro.distance_km} ק״מ</title></g>`;
    }).join('');

    container.innerHTML = `<svg viewBox="0 0 ${size} ${size}" class="local-map"
      role="img" aria-label="מפת אנשי מקצוע באזור">${rings}${dots}
      <circle cx="${mid}" cy="${mid}" r="14" fill="var(--accent)" fill-opacity=".18"/>
      <circle cx="${mid}" cy="${mid}" r="7" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>
    </svg>`;
    container.querySelectorAll('.map-dot').forEach((dot) => {
      dot.addEventListener('click', () => onPick && onPick(+dot.dataset.pro));
    });
  }

  /* ---------- השלמת כתובות ---------- */
  function attachAutocomplete(input, onPlace) {
    if (provider !== 'google' || !window.google.maps.places) return false;
    const auto = new google.maps.places.Autocomplete(input, {
      componentRestrictions: { country: 'il' },
      fields: ['geometry', 'formatted_address', 'name'],
    });
    auto.addListener('place_changed', () => {
      const place = auto.getPlace();
      if (!place.geometry) return;
      onPlace({
        lat: place.geometry.location.lat(),
        lng: place.geometry.location.lng(),
        label: place.name || place.formatted_address,
      });
    });
    return true;
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  return { init, render, attachAutocomplete, get provider() { return provider; } };
})();
