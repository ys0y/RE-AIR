/* =========================================================
   RE:AIR 서비스 워커 (앱 설치 + 오프라인 화면)
   - 화면 파일(HTML/CSS/JS/아이콘/시연용 데이터)을 저장해 두고
   - 인터넷이 끊기면 저장된 화면을 보여 줍니다.
   - AI 요청(/api/...)은 저장하지 않고 항상 서버로 보냅니다.
   ========================================================= */
const CACHE = "reair-v2";
const APP_FILES = [
  "/",
  "/static/style.css",
  "/static/script.js",
  "/static/demo_data.json",
  "/static/manifest.webmanifest",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(APP_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // 예전 버전 저장소 정리
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) {
    return; // AI 요청 등은 그대로 서버로
  }
  // 네트워크 우선: 최신 화면을 받아 저장하고, 실패하면 저장된 화면 사용
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return res;
      })
      .catch(() => caches.match(event.request).then((hit) => hit || caches.match("/")))
  );
});
