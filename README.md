# Diction Masters

A private British English tutor for every Nigerian school child —
video lessons, audio drills, speaking practice, and teacher feedback,
all behind school-controlled access codes.

Built so far: the public landing page; registration (schools,
individuals, and code-based joining for teachers/students); and the
first Learning Tool — 44 Academy.

## Android & iPhone apps

The `mobile/` folder holds the native apps. They open this website, so
anything you deploy here shows up in the apps automatically. See
**[MOBILE_APP_GUIDE.md](MOBILE_APP_GUIDE.md)** for building, publishing and
editing them.

## Project layout

```
dictionmasters/
├── manage.py
├── config/              # project settings, root urls, wsgi/asgi
├── apps/
│   ├── landing/         # the public marketing homepage
│   ├── accounts/        # custom User model (email login, role), registration, login
│   ├── schools/         # School + AccessCode models, school admin dashboard
│   ├── learning_tools/  # the hub that lists every learning tool
│   └── book/            # 44 Academy — the 44 sounds of English
├── templates/
│   ├── base.html
│   ├── includes/        # header, footer, messages, form field renderer
│   ├── landing/home.html
│   ├── accounts/        # register (3 paths), login, holding dashboard
│   ├── schools/dashboard.html
│   ├── learning_tools/hub.html
│   └── book/            # home, 44-academy grid, sound lesson (tabs)
└── static/
    └── css/
        ├── base.css      # tokens, reset, buttons, header, footer — shared by every page
        ├── landing.css   # landing-page-only sections
        ├── app.css       # forms & the school dashboard
        └── book.css      # 44 Academy grid, sound lesson tabs & content cards
```

### The 44 Academy

`apps/book` models one lesson per sound of English:

- **`SoundCategory`** (Long Vowels, Short Vowels, Diphthongs, Consonants, ...)
  holds **`Sound`**s (symbol, name, example words, slug for its URL).
- Each `Sound` has one **`Articulation`** (the "Lens" tab — video +
  the trap/mouth-position/practice-words text) and any number of
  **`WordBankEntry`**, **`SentencePractice`**, **`Passage`**,
  **`Conversation`**, **`TongueTwister`**, **`MinimalPair`** and
  **`ExternalLink`** rows — one per tab on the lesson page.
- Every video/audio field accepts either a direct upload *or* a URL
  (for CDN-hosted media, e.g. Cloudflare R2) — whichever is filled
  in is used.
- **Everything is managed from `/admin/`.** Open a Sound in the admin
  and every tab's content is editable right there as inline forms —
  no code changes needed to add or update a lesson.

Pages: `/learning-tools/` (hub) → `/book/` (44 Academy) →
`/book/44-academy/` (grid of all sounds, grouped by category) →
`/book/44-academy/<sound-slug>/<tab>/` (the lesson, tabbed).
Learning Tools sits behind login — any signed-in role can view it,
matching schools' "view only" access.

### How registration works

- **`accounts.User`** is a custom user model (email as the login field,
  no separate username) with a `role`: `school_admin`, `teacher`,
  `student`, or `individual`, plus an optional FK to `schools.School`.
- **Register a school** (`/accounts/register/school/`) creates a
  `School` and its first user — the school admin — together, in one
  form.
- **Register as an individual** (`/accounts/register/individual/`)
  creates a standalone `User` with no school.
- **Join with a code** (`/accounts/join/`) is how a teacher or student
  gets in: a school admin generates a single-use `AccessCode` from
  their dashboard (role + optional note), hands the code over, and
  the teacher/student redeems it here — it creates their account
  already linked to the right school and role, and the code can't be
  reused.
- The **school dashboard** (`/school/dashboard/`, school admins only)
  is deliberately people-management only — generate codes, see who's
  joined — schools never upload or edit content.

`AUTH_USER_MODEL` is set in `config/settings.py`. Since this project
hasn't been migrated yet in this environment, running
`makemigrations` will pick up `accounts` and `schools` for the first
time — no need to hand-edit migrations.

Apps live under `apps/<name>` in their own namespace, so as we add
`accounts`, `schools`, `lessons`, `assessments`, etc. section by
section, the top level of the project stays uncluttered — each new
app is one folder plus one line in `INSTALLED_APPS`.

## Run it locally

```bash
python -m venv venv
source venv/bin/activate        # venv\Scripts\activate on Windows
pip install -r requirements.txt

python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser   # for /admin/ — prompts for email, first name, password
python manage.py runserver
```

Then open http://127.0.0.1:8000/ — you should see the landing page.
Try registering a school at `/accounts/register/school/`, then
generating a teacher or student code from the dashboard it drops you
into, and redeeming that code at `/accounts/join/` (an incognito
window is an easy way to be "someone else" while testing).

## Notes

- Database is SQLite3 (`db.sqlite3`), zero setup, good for
  development and small-to-medium production loads.
- `DEBUG`, `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS` read from
  environment variables in `config/settings.py`, with safe local
  defaults, so this is ready to move to a `.env` file later without
  changing code.
- The landing page copy (stats, steps, features) currently lives in
  `apps/landing/views.py` as plain Python data. Once the `schools`
  app exists, the stats can be swapped for real queries without
  touching the template.

## Running it

Development, on a laptop:

```bash
python -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env          # then fill in the keys you have
venv/bin/python manage.py migrate
venv/bin/python manage.py runserver
```

That uses SQLite and Django's debug pages. The test suite always uses
SQLite too, so it runs anywhere:

```bash
venv/bin/python manage.py test
```

Production uses PostgreSQL, WhiteNoise and gunicorn, switched on by
`DJANGO_ENV=production` in `.env`. The full server setup, database
creation, backups and troubleshooting are in
[docs/deploy.md](docs/deploy.md).
