/* 바다 구조대 서비스워커: 인터넷이 없어도 열리게 파일을 저장해 둔다.
   화면 파일(index.html)은 인터넷이 되면 새 버전을 먼저 받고, 안 되면 저장본을 쓴다.
   나머지(아이콘, 폰트)는 저장본을 먼저 쓰고 뒤에서 새로 받아 둔다. */
const CACHE = 'sea-rescue-v1';
const CORE = ['./', './index.html', './manifest.json', './icons/icon-192.png', './icons/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // 같은 사이트의 다른 페이지(블록 타워 등)는 건드리지 않는다. 바다 구조대 저장본을 덮어쓰지 않게.
  if (url.pathname.includes('/block-tower/')) return;
  const isPage = req.mode === 'navigate';
  const isFont = url.host === 'fonts.googleapis.com' || url.host === 'fonts.gstatic.com';
  if (url.origin !== location.origin && !isFont) return;

  if (isPage) {
    e.respondWith(
      fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put('./index.html', copy));
        return res;
      }).catch(() => caches.match('./index.html'))
    );
    return;
  }

  e.respondWith(
    caches.match(req).then(hit => {
      const net = fetch(req).then(res => {
        if (res && (res.ok || res.type === 'opaque')) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
        }
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
