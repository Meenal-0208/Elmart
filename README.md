# 🛍️ Elmart — Retail Analytics Platform

A fully local, real-time **Retail Analytics Platform** built with **Python + NiceGUI**.
It renders a professional 50 / 50 split screen in a clean **"Bright White"
theme** — a white background with dark, high-contrast text and vivid pops
of color for accents, badges and charts:

- **Left** — **Elmart**, a shoppable electronics storefront with 500 products
  across 20 categories, **real product photographs**, search, filters,
  flash-sale/trending toggles, quantity selectors, an "Add to Cart" flow, and
  infinite scroll.
- **Right** — *Live Admin Dashboard*: KPI cards, 6 live Plotly charts, a live
  activity feed, and an editable inventory table — all updating automatically
  every 2.5 seconds with **no page refresh**.

No Streamlit is used anywhere in this project.

---

## 🎨 Theme — "Bright White"

Backgrounds are clean white, and text is dark/high-contrast so it pops
clearly, with vivid saturated colors reserved for accents, badges and chart
lines — all defined once in `styles.py`:

| Token                | Value      | Used for                             |
|----------------------|-----------|----------------------------------------|
| Background           | `#FFFFFF` | Page background (white)                |
| Card background       | `#FFFFFF` | Cards, KPI tiles, product tiles        |
| Border                | `#E4E6EF` | Card borders, dividers                 |
| Primary text          | `#1A1A2E` | Body text (near-black navy)            |
| Secondary text        | `#495057` | Captions, labels (dark slate grey)     |
| Accent                | `#C2255C` | Headings, key numbers, chart lines     |
| Success / Bulk badge  | `#2F9E44` | Savings, healthy status                |
| Danger / Flash badge  | `#E03131` | Flash-sale badge, critical flags       |
| Trending badge        | `#7048E8` | Trending badge                         |

Cards keep rounded corners (16px) and soft shadows, with a subtle hover-lift
+ pink-glow shadow animation.

---

## 🎁 Discounts, Sound & Celebration Effects

Elmart now tracks **two independent kinds of discount**, both shown clearly
on every product card:

1. **Product discount** — the existing flash/regular discount stored per
   product (shown as a `-X%` badge and struck-through original price).
2. **Bulk-order discount** — a *separate* discount that kicks in purely
   based on the quantity added to the cart, stacking on top of the product
   discount:
   - 5–9 units → extra **-5%**
   - 10–19 units → extra **-10%**
   - 20+ units → extra **-15%**

   Each card shows the bulk tiers and a live-updating total that recomputes
   as you change the quantity, so you can see the savings before you buy.

When you click **Add to Cart**:
- If **any discount applied** (product and/or bulk) → 🎈 **balloons float up
  the screen** with a cheerful chime.
- If the order had **no discount at all** → 🎉 **party crackers/confetti**
  burst on screen with a short pop sound.

Both effects are generated entirely in the browser (Web Audio API + CSS/JS
animations) — no external sound files or images are downloaded.

---

## 📸 Real Product Photos

Every product card shows an actual **photograph**, not an illustration.

At startup, for each of the 20 categories, the app queries the
[Openverse API](https://openverse.org) — a free search engine (no API key
needed) over openly-licensed photographs aggregated from Wikimedia Commons,
Flickr, museums, and other sources. Unlike a random tag-based placeholder
service, Openverse runs a real relevance search, so a query like
"refrigerator" reliably returns actual photos of refrigerators rather than
unrelated images — this is what fixes the earlier issue of mismatched/wrong
category photos.

A few notes on how this works:
- Results are **cached** to `assets/image_cache.json` after the first run, so
  the app only needs to hit the network once — subsequent launches reuse the
  cached photo URLs instantly. Delete that file if you ever want to re-fetch
  a fresh set of photos.
- **An internet connection is required the first time** the app runs (to
  fetch the initial photo set and to load the images in your browser
  afterwards) — exactly like any real e-commerce site loading product images
  from a CDN.
- If Openverse can't be reached (no internet, or a rate limit), each affected
  category **automatically falls back** to a simple offline illustration
  (rendered locally with Pillow into `assets/category_fallback/`), so the
  storefront still works without a network connection — just without real
  photos for those categories.
- These are openly-licensed stock photographs, great for a personal
  project/prototype. If you ever take this to production, swap in your own
  licensed product photography instead (see `build_category_image_pools()`
  and `generate_products()` in `products.py`).

The **Elmart logo** (the pink shopping-bag monogram in the store header) is
generated locally and offline with **Pillow** — no downloads involved.

---

## ✨ Features

### Elmart storefront (left panel)
- Logo & "Elmart" header
- Search bar (matches product name & brand)
- Category filter (20 electronics categories)
- Sort filter (Newest, Price ↑/↓, Rating, Highest Discount)
- Flash Sale / Trending toggle switches
- Product cards with **real photo**, brand, category, rating, price + strikethrough
  original price, live stock count
- **Flash-sale countdown timer** — any product currently in a flash sale shows
  a live "⏳ Ends in mm:ss" badge that ticks down every second in the browser
  and disappears automatically once the sale ends
- **Low-stock warnings** — products at or below 15 units show an "⚠️ Only N
  left — order soon!" note
- **Out-of-stock handling** — once a product's stock hits 0, its "Add to
  Cart" button is automatically disabled and relabeled "Out of Stock" (and
  the quantity selector is disabled too), both at page load and live as stock
  changes from the simulation
- Quantity selector with a live bulk-discount preview + Add to Cart button
  that stages items in a cart (nothing is charged yet)
- A cart icon with a live item-count badge opens the **cart dialog**, which
  shows a **free-shipping progress bar** (🚚 unlocks at ₹999 — the bar fills
  as the cart subtotal grows, and switches to a "You've unlocked FREE
  shipping!" message once crossed)
- **Checkout** — choose a payment method and pay; a short simulated
  "processing" delay leads to an **Order Confirmation dialog** with an order
  number, items/total paid, and a **simulated delivery date estimate** (2-6
  days out from the current simulated time)
- Infinite scroll (loads more products as you scroll down)

### Live Admin Dashboard (right panel)
- **KPI cards**: Revenue, Profit, Orders, Customers Today, Budget Remaining,
  Inventory Value, Inventory Health
- **Charts** (Plotly, live-refreshing, pink palette on dark cards):
  1. Revenue vs Profit (time series)
  2. Revenue by Category (bar)
  3. Sales Trend / cumulative orders (line)
  4. Hourly Customer Traffic (bar)
  5. Top 10 Products by Revenue (horizontal bar)
  6. Inventory Status (donut: Out of Stock / Low / In Stock / Overstocked)
- **Live Activity Feed** — rolling log of simulated events (orders, returns,
  restocks, flash sales)
- **Editable Inventory Table** — paginated, category-filterable, with editable
  Selling Price / Cost Price / Discount / Stock fields and a **Save** button
  per row that writes straight back into the database

### Business simulation engine
Runs automatically every **2.5 seconds** (`simulation.py`):
- Spawns new customers on an accelerated clock (up to 100,000/day, shaped by
  a realistic hourly traffic curve)
- Converts a fraction of new customers into purchases
- Randomly issues returns
- Restocks low inventory
- Starts/ends Flash Sales on random products
- Nudges selling prices up/down (simulated market fluctuation)
- Accrues fixed daily expenses: 5 employees, rent, utilities, marketing,
  logistics — all subtracted from the **₹20,00,000** starting budget

`Budget Remaining = ₹20,00,000 + Net Profit (Revenue − COGS − Expenses)`,
recalculated continuously and shown live on the dashboard.

---

## 📁 Project Structure

```
retail_dashboard/
├── app.py              # Entry point: page layout, split screen, timers
├── simulation.py         # Live business simulation engine
├── products.py             # 500-product generator + real photo URLs + Pillow logo
├── dashboard.py              # Right panel: KPIs, charts, editable inventory table
├── store.py                    # Left panel: Elmart storefront UI, filters, cart, infinite scroll
├── database.py                   # DuckDB data-access layer
├── charts.py                       # Plotly chart builders (Midnight Pink theme)
├── styles.py                         # Theme constants & global CSS
├── requirements.txt
├── README.md
└── assets/
    ├── logo.png                         # Auto-generated Elmart logo (Pillow)
    ├── image_cache.json                 # Cached real photo URLs (auto-created)
    └── category_fallback/                # Offline fallback illustrations (auto-created if needed)
```

---

## 🛠️ Requirements

- Python 3.10+
- Libraries (see `requirements.txt`): `nicegui`, `pandas`, `polars`, `duckdb`,
  `plotly`, `faker`, `numpy`, `pillow`, `pyarrow`
- An internet connection (for fetching real product photos from Openverse on
  first run, and for loading images in the browser)

`pyarrow` is required internally for Polars ↔ Pandas conversion when loading
the generated product catalogue into DuckDB — no other libraries are used
anywhere in the project.

---

## 🚀 Getting Started (VS Code / local machine)

1. **Clone / copy** the `retail_dashboard/` folder into VS Code.

2. **Create a virtual environment** (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate      # on Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the app**:
   ```bash
   python app.py
   ```

5. NiceGUI will start a local server and automatically open your browser at:
   ```
   http://localhost:8080
   ```

That's it — the storefront and dashboard both come alive immediately, and the
simulation starts ticking every 2.5 seconds.

---

## 🧩 Notes on Implementation

- **DuckDB is the single source of truth** for products and orders. Both the
  storefront and the dashboard query it live — there is no duplicated state
  to keep in sync.
- **Polars + Faker + NumPy** are used purely for generating the initial
  500-product catalogue (`products.py`); once generated, everything is stored
  and queried through DuckDB.
- **Pillow** renders the offline Elmart logo mark — no external downloads
  needed for that piece.
- Product **photos** are real photographs fetched from Openverse on first run
  (see the "Real Product Photos" section above), cached locally, with an
  offline Pillow-rendered fallback per category if there's no network.
- The database is **in-memory** (`duckdb.connect(":memory:")`), so every time
  you restart `app.py` you get a freshly generated, fully-stocked catalogue.
  If you'd like the data to persist across restarts, change the connection
  string in `database.py`'s `Database.__init__` from `":memory:"` to a file
  path such as `"retail.duckdb"`.
- Clicking **Add to Cart** places a real order into the same order pipeline
  used by the simulation, so your own purchases immediately move the KPIs
  and charts on the right — a nice way to see the two panels are truly
  connected.

Enjoy exploring Elmart! 🎉
<img width="1920" height="1080" alt="Screenshot (116)" src="https://github.com/user-attachments/assets/2bd83316-9bc9-40e2-a719-2102df41028e" />
<img width="1920" height="1080" alt="Screenshot (118)" src="https://github.com/user-attachments/assets/e028ffa2-3c50-4eae-a6c7-a7cacf89a102" />
<img width="1920" height="1080" alt="Screenshot (119)" src="https://github.com/user-attachments/assets/cebfb7f4-de5f-441d-bfee-093784d231b7" />
<img width="1920" height="1080" alt="Screenshot (120)" src="https://github.com/user-attachments/assets/59a981fa-1c15-471f-9b45-71c5dc412825" />
<img width="1920" height="1080" alt="Screenshot (121)" src="https://github.com/user-attachments/assets/15509b8f-12fe-41e4-bb3f-b7c1e0c0f217" />
<img width="1920" height="1080" alt="Screenshot (122)" src="https://github.com/user-attachments/assets/2abb0995-08ee-4399-8bb8-b7ff33313315" />
