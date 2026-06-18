<!-- TEST ARTIFACT — write-spec at `light` (T1) rigor, code-free (v0.16.0), for comparison against the full grounded spec in `cdn-site-fronting.md`. Same change, authored as if it were a trivial T1 board issue. -->

# CDN Static-Asset Delivery — Spec (T1 / light)

> Front the site with a CDN so static assets are edge-cached and the web tier is offloaded, without changing any dynamic or authenticated behavior.

## Acceptance Criteria

| AC | Criterion |
|----|-----------|
| 1 | Static-asset URLs are served from a CDN edge cache, not directly by the web tier. |
| 2 | Dynamic, authenticated, and per-tenant responses (pages, dashboard, checkout, APIs, and any per-tenant file such as `robots.txt` / `sitemap.xml` / `favicon.ico`) are never served from cache — every tenant always receives its own content. |
| 3 | After a release, a changed asset reaches every visitor immediately — no stale asset is ever served. |
| 4 | The correct brand/tenant site renders for every host, with no content leaking between tenants. |
| 5 | Checkout completes end-to-end, including multi-megabyte licence / insurance image uploads. |
| 6 | The real visitor IP is preserved end-to-end, so controls that act on client IP (rate-limits, IP bans, abuse logging) target the actual visitor and never the CDN's edge. |
| 7 | The IP-based blocking and managed security rules in force today remain effective once the CDN is in front. |
| 8 | The origin is reachable only through the CDN — a direct-to-origin request from outside is refused — and that lock-down is verified before any existing protection is relaxed. |
| 9 | All traffic is HTTPS with no redirect loop and no mixed content; session / auth cookies are marked secure. |
| 10 | Long-running requests (large imports / exports) complete without failing at the edge. |
| 11 | Uploaded user images are served correctly through the CDN. |
| 12 | Each brand host is cut over to the CDN one brand at a time, and a documented rollback restores direct-origin serving for a host. |
