# Hackstore.fo → Prowlarr Cardigann Indexer

## Architecture

```
Radarr/Sonarr → Prowlarr → Cardigann YML → localhost:8080 (proxy) → hackstore.fo
                                                 ↓
                                     decrypts acortalink URLs
                                     rewrites HTML before Cardigann sees it
```

The YML defines `http://localhost:8080` as the base URL. All traffic flows through
the proxy. The proxy forwards requests to the real `hackstore.fo`, but on the way
back, it scans HTML for `acortalink.net/s.php?i=...` URLs, decrypts them with
`decrypt_url.py`, and replaces the `href` with the real .torrent/magnet URL.
Cardigann sees clean, decrypted links.

---

## Files to Create

### 1. `proxy.py` — Local reverse proxy

- Listens on `localhost:8080`
- Forwards all GET requests to `https://www.hackstore.fo` (setting correct Host header)
- On HTML responses (`Content-Type: text/html`):
  - Finds all `<a href="https://acortalink.net/s.php?i=...">` elements
  - Extracts the `i=` query parameter (base64-encoded encrypted data)
  - Calls `decrypt_acortalink(i)` from `decrypt_url.py` to get the real URL
  - Replaces the `href` with the decrypted URL
  - Also handles `script`, `link`, `img`, `form` tags — rewrites relative URLs to
    point through the proxy (`/foo/bar` → `http://localhost:8080/foo/bar`) so the
    page loads correctly
- Passes non-HTML responses (images, CSS, JS, fonts) through unchanged
- Uses Flask or aiohttp for the HTTP server

### 2. `hackstore.yml` — Cardigann definition

```yaml
---
id: hackstore
name: Hackstore
description: "Hackstore.fo - Peliculas, Series y Animes (Latino)"
language: es-ES
type: public
encoding: UTF-8
requestDelay: 2
followredirect: true
testlinktorrent: false
links:
  - http://localhost:8080/

caps:
  categories:
    2000: Movies
    5000: TV
    5070: TV/Anime

  modes:
    search: [q]
    movie-search: [q]
    tv-search: [q, season, ep]

settings: []

search:
  paths:
    - path: "{{ if .Keywords }}?s={{ .Keywords }}{{ else }}/peliculas/{{ end }}"
      categories: [2000]
    - path: "{{ if .Keywords }}?s={{ .Keywords }}{{ else }}/series/{{ end }}"
      categories: [5000]
    - path: "{{ if .Keywords }}?s={{ .Keywords }}{{ else }}/animes/{{ end }}"
      categories: [5070]

  keywordsfilters:
    - name: re_replace
      args: ["\\s+", "+"]   # WordPress search uses +

  rows:
    # EXACT SELECTOR TBD — need to inspect actual listing/search page HTML
    # Candidates:
    #   "div.movies-list > article.movie-item"
    #   "div.block-content > div.estreno-thumbnail"
    #   "div#main-content article"
    selector: "TBD"
    filters:
      - name: andmatch

  fields:
    title:
      # EXACT SELECTOR TBD
      selector: "TBD"
    details:
      # Link to the detail page (/peliculas/foo-2026/)
      selector: "TBD"
      attribute: href
    year:
      # EXACT SELECTOR TBD — may need regexp filter from title
      selector: "TBD"
      optional: true
    category:
      # DEPENDS ON WHICH PATH MATCHED — use conditionals
      text: "{{ if eq .Query.Type \"tv-search\" }}5000{{ else if eq .Query.Type \"movie-search\" }}2000{{ else }}2000{{ end }}"
    seeders:
      text: 1
    leechers:
      text: 1
    size:
      text: "1 GB"
    date:
      text: now
    downloadvolumefactor:
      text: 0
    uploadvolumefactor:
      text: 1

download:
  # Cardigann visits each detail page (from the 'details' field above).
  # The proxy decrypts acortalink URLs in the response HTML.
  # Selector grabs the first Bittorrent download button.
  selectors:
    - selector: "a.btn-slide[href*='torrent']"
      attribute: href
    # Fallback: any download button (proxy already decrypted the href)
    - selector: "table.newtab a.btn-slide"
      attribute: href
```

### 3. `decrypt_url.py` — Already exists

No changes needed. Contains `decrypt_acortalink(encoded)` function.

---

## Selectors to Determine (Critical)

Before the YML is usable, the following must be verified by inspecting actual HTML
of listing/search pages:

| Page URL | What to determine |
|---|---|
| `GET /peliculas/` | Row selector for movie items on listing page |
| `GET /series/` | Row selector for TV items on listing page |
| `GET /animes/` | Row selector for anime items on listing page |
| `GET /?s=test` | Row selector on search results page |
| `GET /peliculas/foo-2026/` | Verify that acortalink URLs exist in raw HTML source |

For each row item, determine selectors for:
- **title** — the movie/series name
- **details** — the `<a href>` linking to the detail page
- **year** — year from the card/poster (may need regex from title)
- **poster** — the `<img>` poster thumbnail

---

## Usage

1. **Start the proxy:**
   ```bash
   python proxy.py
   # or: uv run proxy.py
   ```
   Verify it works: `curl http://localhost:8080/` should return hackstore homepage.

2. **Install the YML:**
   ```bash
   cp hackstore.yml <Prowlarr_Config>/Definitions/Custom/
   ```

3. **Restart Prowlarr.** Hackstore will appear in the indexer list.

4. **Add the indexer** via Prowlarr UI → Indexers → Add → search "Hackstore".

5. **Test** using the built-in Test button, then try a manual search.

---

## Edge Cases & Notes

- **No seeders/leechers:** Hackstore is not a tracker. Set static values (1/1).
- **No .torrent file extension:** The decrypted URL may be a magnet link or direct
  .torrent URL. Both work with Prowlarr if `followredirect: true`.
- **Social share wall:** Download links are present in the raw HTML source despite
  being hidden by JS. Cardigann sees them. No JS execution needed.
- **Multiple quality versions:** Each detail page has 3-5 quality panels (4K, 1080p,
  720p, etc.). The selector grabs the first Bittorrent link (highest quality).
  A settings checkbox could optionally let the user prefer a specific quality.
- **Rate limiting:** Included `requestDelay: 2` to avoid overwhelming the site.
- **Encoding:** The site uses UTF-8 with Spanish content. Accented characters in
  titles should pass through correctly.
- **WordPress pagination:** If search results span multiple pages, Cardigann v11
  pagination support can handle it by adding `pageSize` and using
  `{{ .Query.Page }}` in the path.

---

## Testing the Decryption

Before building the proxy, verify the decrypt function works on a real URL:

```bash
python decrypt_url.py "VTJGc2RHVmtYMSsveGNVSFRONlQ1eGhmYldpWHptd3ZhUnBYaStIN2V5ZGhKeElUVDZCRXpzYnpNbEdOUXhKbm03UnZFOVQzaFpvS3dGTFBhNXM2STBsS0lJRTR6RGhWT2VWcmxHREdPL2xsdm9hLzdTa0kxeGtmQVdDV29xS2l0Y3FUM1J5eVNIemljRTJIN2xEcjNyT0ZEaVhaUXYvZzA0NFFVWFhQbzNTaGVwN3lYU3RKTURIWGJ3bk1lSk5raTZHbGIyN09Rd0Rabm9DQTNBUHRJczZwbFY4VWdZOE15d2VPTWRIN1JJcWgrc1l4bUlHTmxCeHh2Q3d6dUMzb21TZWJld1FESUR4dlBEZktpT1JkK1U4WWJYUXQ1bEo1S2h2MCtzTlQ3ak0rRTBsQjBScUZaK3RBckFlQzhiaDVqdzMxK1lmTkxacG83NVNWbzdMSW0zZk4xNXNwYnhlKzl5MzJCMGhlbFR1UWNYZndYK3RuMStmSEtnbU43RnJCZjZLMFlZUklqQm9QVXVUYlYrbjkwUG44SFNqbDY3SlZveHpIQVlvQTVqND0="
```

If it outputs a valid `.torrent` URL or `magnet:?` link, everything works.
If it outputs a different URL format (e.g., another redirect), update the plan.
