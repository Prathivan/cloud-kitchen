# Butterfly Cloud Kitchen

A Django food-ordering website for a home-based cloud kitchen, with a
customer-facing site and a custom-branded admin panel for running the
kitchen day to day.

## Tech stack

- Python 3 / Django (see `requirements.txt` for the exact version)
- SQLite by default (no server to install) — the project is already
  wired to switch to PostgreSQL later with just a config change; see
  "Database setup" below
- APScheduler / django-apscheduler (in-process background job for
  pre-order reminders — see "Pre-order reminders" below)
- Plain HTML/CSS/JavaScript on the front end (no build step, no
  Node.js required)

## Getting started

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional for now) copy the example env file
cp .env.example .env

# 3. Set up the database (SQLite by default -- nothing else needed)
python manage.py migrate

# 4. Create your own admin/staff account
python manage.py createsuperuser

# 5. Run the site
python manage.py runserver
```

Then visit:
- **Customer site:** http://127.0.0.1:8000/
- **Admin panel:** http://127.0.0.1:8000/admin/

Run the test suite at any time with:

```bash
python manage.py test
```

## Database setup

**Right now, the project runs on SQLite** — nothing to install or
configure. `python manage.py migrate` creates `db.sqlite3` and you're
ready to go.

**Switching to PostgreSQL later** is a config change, not a code
change:

```bash
# 1. Install Postgres (Ubuntu/Debian example)
sudo apt install postgresql postgresql-contrib

# 2. Create the database + a user for the app
sudo -u postgres psql
  CREATE DATABASE butterfly_cloud_kitchen;
  CREATE USER butterfly WITH PASSWORD 'change-me';
  GRANT ALL PRIVILEGES ON DATABASE butterfly_cloud_kitchen TO butterfly;
  \q

# 3. Uncomment psycopg2-binary in requirements.txt, then:
pip install -r requirements.txt
```

Then in `.env` (copied from `.env.example`), uncomment and fill in:

```
DB_ENGINE=postgres
DB_NAME=butterfly_cloud_kitchen
DB_USER=butterfly
DB_PASSWORD=change-me
DB_HOST=localhost
DB_PORT=5432
```

Run `python manage.py migrate` again and you're on Postgres — the
existing SQLite data won't carry over automatically (that's a separate
data-migration step if/when you need it).

## Apps

| App        | What it owns                                                         |
|------------|-----------------------------------------------------------------------|
| `accounts` | Customer signup/login/logout, the "My Account" page, the home page view, and the custom admin dashboard/theme (`config/admin_dashboard.py`) |
| `menu`     | Categories, menu items, Chef Specials, Popular Dishes, Running Offers, and Customer Reviews |
| `cart`     | The shopping cart (add/update/remove items, live cart-count badge)  |
| `orders`   | Checkout, order history, and the kitchen order-status workflow      |
| `config`   | Django project settings, URLs, and the admin theme/dashboard logic  |

## Customer workflow

1. **Browse** the home page (Chef Specials, Popular Dishes, Running
   Offers) or the full Menu, filterable by category.
2. **Sign up** with full name, mobile number, email, and password —
   this always creates a plain **customer** account (see "Roles &
   security" below).
3. **Add items to cart.** The cart count in the navbar updates
   instantly without a page reload.
4. **Checkout.** This creates an `Order` with a snapshot of each
   item's name/price/quantity, and clears the cart.
5. **Track the order** from "My Account" or "My Orders" — each order
   shows a live status badge and a step-by-step progress tracker
   (Order Placed → Confirmed → Preparing → Ready → Out for Delivery →
   Delivered), or a cancellation notice if it was cancelled.
6. **My Account** shows the customer's own profile (editable) and
   their full order history on one page.

## Order status workflow

An order moves through these statuses, one step at a time:

```
pending → confirmed → preparing → ready → out_for_delivery → delivered
```

`cancelled` can be reached from any status before `delivered`. Each
status change is timestamped once (never backdated), and staff advance
an order with a single button click from the admin dashboard or the
Orders list — there's no manual status dropdown to get wrong.

## Admin panel

The admin panel is a fully custom-branded theme built on top of
Django's own admin (so it keeps Django's built-in permissions, search,
and form validation, but doesn't look or feel like stock Django admin).

- **Dashboard** — today's order count, pending/preparing counts,
  today's revenue, customer count, an order-status breakdown chart, a
  live Today's Orders table (auto-refreshes without a page reload),
  Best-Selling Items, Quick Actions, and Recent Reviews.
- **Orders** — full list with filters (status, date), search, and a
  one-click "advance to next status" button per order.
- **Menu Management** — Menu Items (with Chef Special / Popular Dish /
  Offer toggles, Veg/Non-Veg, daily selling limits), Categories, and
  dedicated quick views for Chef Specials and Popular Dishes.
- **Business** — Customers (with order count and total spend),
  Reviews (approve/hide), Offers (with a start/end date schedule).
- **Reports** — sales totals, average order value, and best-sellers
  over Today / Yesterday / Last 7 Days / Last 30 Days / a custom range.

## Roles & security

- **Customer** — created only through the public signup form. Can
  never become staff or an admin through any customer-facing action;
  this is enforced on the server, not just hidden in the UI.
- **Staff** (`is_staff=True`) — can access the admin panel for the
  sections they're given permission to.
- **Super Admin** (`is_superuser=True`) — full access to everything.

A customer can only ever see and edit their **own** profile, cart, and
orders — every query is scoped to the logged-in user on the server
side, never trusted from anything the browser sends.

## Design system

The site uses a light, Butterfly-branded palette (sky blue, soft
lavender, mint, pale pink) with a small amount of "glassmorphism" on
featured surfaces only (the hero card, the account page's profile
panel, and the admin dashboard's summary cards) — everything else
(tables, forms, lists) stays flat and high-contrast for readability.
The same branding is applied across every admin page, not just the
dashboard, via `static/admin/css/butterfly_admin.css` and
`templates/admin/base_site.html`.

## Pre-Order feature

Customers can pre-book certain menu items (e.g. custom cakes) that
need advance notice, instead of ordering them for immediate
fulfillment. A cart/order is always **either** a Normal Order **or** a
Pre-Order — never a mix of both.

### What changed

**Models / migrations**
- `menu/models.py` — `MenuItem.is_preorder` (bool) and
  `preorder_hours` (positive int, required when `is_preorder=True`,
  validated in `clean()`). New migration:
  `menu/migrations/0013_menuitem_is_preorder_menuitem_preorder_hours.py`.
- `orders/models.py` — `Order.is_preorder` (bool), `preorder_datetime`
  (nullable datetime, the calculated fulfillment time), and
  `preorder_reminder_sent` (bool, prevents duplicate reminders). Also
  a new `AdminNotification` model, used by the reminder scheduler. New
  migration: `orders/migrations/0004_order_is_preorder_order_preorder_datetime_and_more.py`.
- `cart/models.py` — no new field on `CartItem` itself (whether a cart
  row is "pre-order" is always derived from `menu_item.is_preorder`);
  added a `cart_order_type(user)` helper used everywhere the
  no-mixing rule needs to be checked or displayed.

Run `python manage.py migrate` to apply both.

**How the pre-order date/time is calculated**

At checkout (`orders/views.py`), inside the same atomic transaction
that already locks each menu item row:

```
order.preorder_datetime = order_placed_at + timedelta(hours=max(
    item.menu_item.preorder_hours for item in the order's pre-order items
))
```

If an order has several pre-order items with different lead times, the
**longest** one is used, so the order is only considered ready once
every item in it actually is. The value is written once at checkout
and never recalculated — if an admin later edits a menu item's
`preorder_hours`, only *new* pre-orders placed afterwards use the new
value; existing orders keep what the customer was originally promised.

**How normal/pre-order separation works**

- Adding an item to the cart (`cart/views.py: add_to_cart`) checks
  `cart_order_type(user)` against the item being added. If they
  conflict, the request is rejected (AJAX gets `{"ok": false,
  "conflict": true, "error": "..."}`, status 409); the menu page's JS
  then shows a confirm dialog ("Clear your current cart and continue
  with this item?"). Confirming resubmits the same request with
  `force=1`, which clears the existing cart and adds the new item in
  one step. A "Clear Cart" button on the cart page (and the
  `cart:clear_cart` endpoint) gives a no-JS fallback.
- `orders/views.py: checkout` independently re-derives the order type
  from the *locked* cart rows and refuses to process a mixed cart even
  if one somehow existed — the backend never trusts what the frontend
  already prevented.

**How the 1-hour reminder works**

`orders/reminders.py: send_due_preorder_reminders()` finds
`Order`s where `is_preorder=True`, `preorder_reminder_sent=False`, and
`preorder_datetime <= now + 1 hour`, creates one `AdminNotification`
per order, and atomically flips `preorder_reminder_sent=True` (an
`UPDATE ... WHERE preorder_reminder_sent=False` guards against a
duplicate if two runs ever overlapped). It's called from two places
that share this exact logic:

1. **`orders/scheduler.py`** — an in-process APScheduler job that
   checks every 1 minute. Chosen over Celery+Beat because this project
   has no Redis/broker set up; APScheduler needs nothing extra
   installed and runs inside the same process as the app.
2. **`python manage.py send_preorder_reminders`** — the exact same
   logic as a one-off management command, for production setups that
   prefer an external cron job / systemd timer instead of (or as a
   backup to) the in-process scheduler.

Reminders show up in the admin as a 📦 badge next to the existing 🔔
pending-orders bell on the dashboard (live-updated the same way the
rest of the dashboard already polls), and in **Pre-Order Reminders**
under the Order Type filter / `AdminNotification` admin list, where
clicking through leads to the relevant order.

**Running the scheduler**

- **Locally:** nothing extra to do — just `python manage.py
  runserver`. `orders/apps.py` starts the APScheduler job
  automatically (guarded against Django's autoreloader double-loading
  it).
- **In production:** the in-process scheduler only reliably works with
  a single app process. If you run multiple gunicorn/uwsgi workers,
  either (a) dedicate exactly one worker/process to scheduling, or —
  recommended — (b) don't rely on the in-process scheduler at all and
  instead add a cron job / systemd timer that runs
  `python manage.py send_preorder_reminders` every 1–5 minutes. That
  command is safe to run from any number of places since duplicate
  reminders are prevented at the database level.

**New dependencies:** `psycopg2-binary`, `python-dotenv`, `Pillow` (was
already required by `ImageField` but missing from `requirements.txt`),
`APScheduler`, `django-apscheduler`. Install with
`pip install -r requirements.txt`.

**Testing:** `orders/tests.py` (`PreorderCheckoutTests`,
`PreorderReminderTests`) and `cart/tests.py`
(`CartMixingPreventionTests`) cover: pre-order datetime calculation and
snapshotting, the longest-lead-time rule for multiple pre-order items,
backend rejection of a mixed cart at checkout, reminder creation, and
duplicate-reminder prevention, plus the cart mixing-block/force-switch/
clear-cart flows. Run everything with `python manage.py test` (105
tests, all passing as of this change).
