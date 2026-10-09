const CACHE = 'gge-app-vi-thong-minh-quan-tri-thu-chi-25c8906d-v1';
self.addEventListener('install', function(e) { self.skipWaiting(); });
self.addEventListener('activate', function(e) {
  e.waitUntil(caches.keys().then(function(keys) {
    return Promise.all(keys.filter(function(k) { return k.indexOf('gge-app-vi-thong-minh-quan-tri-thu-chi-25c8906d-') === 0 && k !== CACHE; }).map(function(k) { return caches.delete(k); }));
  }).then(function() { return self.clients.claim(); }));
});
self.addEventListener('fetch', function(e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin === location.origin && url.pathname.indexOf('/api/') === 0) return;
  e.respondWith(fetch(req).then(function(res) {
    if (res && (res.ok || res.type === 'opaque')) { var copy = res.clone(); caches.open(CACHE).then(function(c) { c.put(req, copy); }); }
    return res;
  }).catch(function() {
    return caches.match(req).then(function(hit) {
      if (hit) return hit;
      if (req.mode === 'navigate') return new Response('<meta charset="utf-8"><body style="background:#030712;color:#e2e8f0;font-family:sans-serif;text-align:center;padding:48px">Đang ngoại tuyến. Vui lòng kết nối mạng và mở lại ứng dụng.</body>', { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
      return Response.error();
    });
  }));
});
