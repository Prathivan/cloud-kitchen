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
   the mobile number must be verified with a one-time code (sent via
   SMS or WhatsApp, customer's choice) before the account is created;
   see "Mobile OTP verification" below. This always creates a plain
   **customer** account (see "Roles & security" below).
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

## Mobile OTP verification (signup)

Signup requires the customer's mobile number to be verified with a
one-time code — sent via **SMS or WhatsApp, their choice** — before
any account is created. The rest of the signup form (name, email,
password) only appears after the code is confirmed.

### Flow

1. Customer enters their mobile number and picks SMS or WhatsApp on
   the signup page, then clicks **Send Verification Code**. This posts
   to `POST /signup/send-otp/`, which creates an `OTPVerification` row
   (6-digit code, hashed, 5-minute expiry) and calls
   `accounts/otp_service.send_otp()`.
2. Customer enters the code and clicks **Verify Code**
   (`POST /signup/verify-otp/`). On a correct, unexpired code, the
   mobile number is marked verified **in that browser session only**
   (`request.session["otp_verified_mobile_number"]`) — nothing is
   written to the `User`/`CustomerProfile` tables at this point.
3. The rest of the signup form unlocks. The final `POST /signup/`
   (`accounts/forms.py: CustomerSignupForm.clean()`) refuses to create
   an account unless the mobile number being submitted matches the one
   verified in the session — so there's no way to skip straight to the
   final POST with an unverified number.

### MSG91 is wired up — here's how to switch it on

`accounts/otp_service.py` has a working MSG91 integration for both SMS
and WhatsApp already written — it's inactive until you set the env
vars below in your `.env` (see `.env.example` for the full list with
comments):

```
OTP_PROVIDER=msg91
MSG91_AUTH_KEY=your-msg91-auth-key

# SMS (needs DLT registration first — see MSG91's dashboard):
MSG91_SMS_SENDER_ID=YOURID
MSG91_SMS_DLT_TEMPLATE_ID=123456789012345
MSG91_SMS_TEMPLATE=Your Butterfly Cloud Kitchen verification code is {otp}. Valid for 5 minutes.

# WhatsApp (needs an approved WhatsApp "Authentication" template):
MSG91_WHATSAPP_INTEGRATED_NUMBER=919876543210
MSG91_WHATSAPP_TEMPLATE_NAME=otp_verification
MSG91_WHATSAPP_NAMESPACE=your-template-namespace
```

Steps to get those values, in order:
1. Create an MSG91 account and get your **Auth Key** from the
   dashboard (`MSG91_AUTH_KEY`).
2. Complete **DLT registration** for SMS (mandatory in India) — MSG91
   walks you through registering your sender ID and your exact OTP
   message template. Once approved you'll have a **sender ID** and a
   **DLT template ID** — copy the approved template's wording exactly
   into `MSG91_SMS_TEMPLATE` (with `{otp}` where the digits go).
3. Register a **WhatsApp Business Account** through MSG91's onboarding
   and get an **Authentication-category** template approved by Meta
   (usually 1–2 days). Copy the template name, namespace, and your
   WhatsApp Business number into the `MSG91_WHATSAPP_*` variables.
4. Set all of the above in `.env`, restart the server. Signups will
   now send real SMS/WhatsApp messages instead of printing to the
   console.

If any of the SMS or WhatsApp variables are missing (e.g. you've only
finished DLT registration but not the WhatsApp template yet), that one
channel silently falls back to the console stub while the other
channel — if fully configured — sends for real. Nothing crashes either
way; check the `accounts.otp` logger if a send unexpectedly falls
back.

**Testing:** `accounts/tests.py: MSG91OTPServiceTests` mocks
`requests.post` throughout, so running the test suite never makes a
real network call or sends a real message, even if real MSG91
credentials happen to be set in the environment the tests run in.

### Limits (all in `accounts/models.py: OTPVerification`)

| Setting | Value |
|---|---|
| Code length | 6 digits |
| Code validity | 5 minutes |
| Resend cooldown | 30 seconds |
| Max incorrect attempts | 5, then the code is locked out (request a new one) |

Codes are stored **hashed** (`django.contrib.auth.hashers`), never in
plaintext, including in the Django admin (`OTPVerification` is
registered read-only there for debugging, but the code itself is never
shown — only mobile number, channel, verification status, and
timestamps).

**Testing:** `accounts/tests.py: OTPFlowTests` covers sending a code,
correct/incorrect verification, expiry, the resend cooldown, the
max-attempts lockout, and a full end-to-end signup through the real
OTP flow with no shortcuts. `MSG91OTPServiceTests` covers the MSG91
integration itself (SMS + WhatsApp payloads, error handling, mobile
number normalization) with `requests.post` always mocked. `SignupTests`
covers the rest of the signup form and is unaffected by the OTP
requirement itself (it uses a `signup_via_client()` test helper that
marks a mobile number verified directly in the session, the same state
a real customer's session would be in after finishing steps 1–2
above). Run everything with `python manage.py test` (131 tests, all
passing as of this change).
