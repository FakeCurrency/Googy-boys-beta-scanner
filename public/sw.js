/* Melbourne Property service worker — conservative network-first.
   Always tries the network (so deploys are picked up immediately) and falls
   back to the last cached copy only when offline. Cross-origin requests
   (map tiles, geocoding) are left alone. */
const CACHE = "mp-v2";

/* Cache-busted URLs look like path?v=<deploy run number>; higher = newer.
   -1 means "no / non-numeric version" so plain URLs never outrank real ones. */
const vNum = search => {
  const m = /^\?v=(\d+)$/.exec(search);
  return m ? +m[1] : -1;
};

self.addEventListener("install", e => self.skipWaiting());

self.addEventListener("activate", e => {
  e.waitUntil((async () => {
    /* Migrate the freshest variant of each path out of older cache versions
       before deleting them, so existing users keep working offline through
       the rename instead of starting from an empty cache. */
    for (const key of await caches.keys()) {
      if (key === CACHE) continue;
      const old = await caches.open(key);
      const cur = await caches.open(CACHE);
      const best = new Map();                    // pathname -> [version, request]
      for (const req of await old.keys()) {
        const u = new URL(req.url), v = vNum(u.search);
        const prev = best.get(u.pathname);
        if (!prev || v >= prev[0]) best.set(u.pathname, [v, req]);
      }
      for (const [, req] of best.values()) {
        if (!(await cur.match(req))) {
          const res = await old.match(req);
          if (res) await cur.put(req, res);
        }
      }
      await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(
    fetch(e.request)
      .then(res => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then(c => {
            c.put(e.request, copy);
            /* Evict strictly OLDER ?v= variants of the same path so cache-busted
               URLs don't accumulate. Only-older matters: GitHub Pages ignores the
               query string, so a stale CDN copy of index.html can still request
               ?v=N after ?v=N+1 is cached — that fetch must never evict N+1.
               Fire-and-forget — never delays the page. */
            const v = vNum(url.search);
            if (v >= 0) {
              c.keys().then(reqs => Promise.all(
                reqs.filter(r => {
                  const old = new URL(r.url);
                  return old.pathname === url.pathname && vNum(old.search) < v;
                }).map(r => c.delete(r))
              ));
            }
          });
        }
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
