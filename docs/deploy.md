# Deploying Diction Masters

Written for whoever puts the site on a server. It assumes Ubuntu, nginx
and PostgreSQL on one machine, which is the cheapest thing that works
well; a managed database or a platform like Render works too, and the
differences are noted where they matter.

## What runs where

| | Development (your laptop) | Production (the server) |
|---|---|---|
| Database | PostgreSQL | PostgreSQL |
| Tests | SQLite, in memory | SQLite, in memory |
| Debug pages | on | off |
| Site CSS/JS/images | served by Django | served by WhiteNoise, compressed and cached for a year |
| Uploads, recordings, thumbnails | Cloudflare R2 | Cloudflare R2 |
| Switch | `DJANGO_ENV=development` | `DJANGO_ENV=production` |

Everything is decided by `.env`. Nothing in the code needs editing to go
live, and `.env` is never committed.

PostgreSQL is used everywhere, so what you build on is what you run on.
`DJANGO_DB=sqlite` is the escape hatch: it switches back to the old
`db.sqlite3` file for a quick look, or to work with no database server
running.

Tests run on an SQLite database held in memory. Django empties the
database at the start of every test run, so tests are kept well away
from real data: nothing is created on the PostgreSQL server and
`diction_db` is never touched.

The site refuses to start in production if `DJANGO_SECRET_KEY` is still
the development placeholder, or if `DJANGO_ALLOWED_HOSTS` is empty. That
is deliberate: a half-configured site should not serve traffic.

## 1. Prepare the server

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip postgresql nginx ffmpeg
```

`ffmpeg` is what takes the thumbnail from an uploaded video. Without it
the site still runs; videos simply have no thumbnail.

## 2. Get the code and its dependencies

```bash
sudo mkdir -p /srv/dictionmasters && sudo chown "$USER" /srv/dictionmasters
git clone <your repository> /srv/dictionmasters
cd /srv/dictionmasters
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

## 3. Fill in the settings

```bash
cp .env.example .env
nano .env
```

At the very least set:

```
DJANGO_ENV=production
DJANGO_SECRET_KEY=          # venv/bin/python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
DJANGO_ALLOWED_HOSTS=dictionmasters.com,www.dictionmasters.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://dictionmasters.com,https://www.dictionmasters.com
POSTGRES_DB=diction_db
POSTGRES_USER=diction_user
POSTGRES_PASSWORD=…
R2_ACCOUNT_ID=…  R2_BUCKET_NAME=…  R2_ACCESS_KEY_ID=…  R2_SECRET_ACCESS_KEY=…
ELEVENLABS_API_KEY=…  ELEVENLABS_VOICE_ID=…  GROQ_API_KEY=…
```

Keep `.env` readable only by the account that runs the site:

```bash
chmod 600 .env
```

## 4. Create the database

```bash
bash scripts/create_postgres_db.sh
```

It reads the name, user and password from `.env` and asks for your sudo
password once. On a managed database, skip this and paste the host,
user and password the provider gives you into `.env`, with
`POSTGRES_SSLMODE=require`.

## 5. Build the site

```bash
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput
venv/bin/python manage.py createsuperuser        # your admin login
venv/bin/python manage.py check --deploy         # should report no issues
```

Moving content from a laptop database to the server instead of starting
empty:

```bash
bash scripts/move_data_to_postgres.sh
```

It exports everything from SQLite and loads it into PostgreSQL.
Uploads are untouched: they are already on R2 and the database only
holds the links.

## 6. Run it with gunicorn

`/etc/systemd/system/dictionmasters.service`:

```ini
[Unit]
Description=Diction Masters
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/srv/dictionmasters
EnvironmentFile=/srv/dictionmasters/.env
ExecStart=/srv/dictionmasters/venv/bin/gunicorn -c gunicorn.conf.py config.wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /srv/dictionmasters
sudo systemctl enable --now dictionmasters
sudo systemctl status dictionmasters
```

## 7. Put nginx in front

`/etc/nginx/sites-available/dictionmasters`:

```nginx
server {
    listen 80;
    server_name dictionmasters.com www.dictionmasters.com;

    # Lesson videos are large; let them through.
    client_max_body_size 512M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/dictionmasters /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d dictionmasters.com -d www.dictionmasters.com
```

Certbot adds the HTTPS server block. Django then redirects any plain
HTTP request to HTTPS, and sends secure cookies and HSTS.

Static files are served by the application through WhiteNoise, so nginx
needs no `location /static/` block. Uploads are served from R2 through
signed links that expire after six hours.

## 8. Every release after that

```bash
cd /srv/dictionmasters
git pull
venv/bin/pip install -r requirements.txt
venv/bin/python manage.py migrate
venv/bin/python manage.py sync_quickword_ipa
venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart dictionmasters
```

The `sync_quickword_ipa` command is idempotent and should run after every
release so saved Quick Words use the bundled en_UK dictionary. The Procfile
release phase runs it automatically after migrations on platforms that use
that phase.

After the release containing the unified ElevenLabs voice, run these once on
the production server so refreshed audio is saved to production media storage:

```bash
venv/bin/python manage.py regenerate_quickword_audio
venv/bin/python manage.py generate_phoneme_audio --replace
venv/bin/python manage.py revoice_tutor_cache
```

The audio commands require production's `ELEVENLABS_API_KEY`,
`ELEVENLABS_VOICE_ID`, and media storage settings. They regenerate generated
clips only; uploaded recordings and external audio URLs are preserved.

## Backups

The database holds all the teaching content and every learner's
progress. The files themselves are on R2, which keeps its own copies.

```bash
# nightly, kept for 14 days
pg_dump -U diction_user -h 127.0.0.1 diction_db | gzip > /var/backups/diction-$(date +%F).sql.gz
find /var/backups -name 'diction-*.sql.gz' -mtime +14 -delete
```

Restore with:

```bash
gunzip -c /var/backups/diction-2026-09-16.sql.gz | psql -U diction_user -h 127.0.0.1 diction_db
```

## Checking it is healthy

```bash
sudo systemctl status dictionmasters      # is it running
sudo journalctl -u dictionmasters -f      # what it is saying
venv/bin/python manage.py check --deploy  # security settings
```

In the admin console, **Connected services** shows at a glance whether
R2, ElevenLabs and Groq are reachable from the server.

## Troubleshooting

**"Set DJANGO_SECRET_KEY before running in production."** `.env` still
has the placeholder key, or systemd is not reading `.env`. Check
`EnvironmentFile` in the service file.

**A page says DisallowedHost.** Add the domain to
`DJANGO_ALLOWED_HOSTS`, then restart.

**Forms fail with a CSRF error over HTTPS.** Add the full origin,
`https://…`, to `DJANGO_CSRF_TRUSTED_ORIGINS`.

**CSS is missing after a release.** `collectstatic` was not run, or it
ran as the wrong user and could not write `staticfiles/`.

**Videos have no thumbnail.** `ffmpeg` is not installed on the server.
Install it, then press **Make thumbnails** in the admin console.

**Uploads fail or media links 404.** Check the four `R2_` values, and
that the bucket still exists.
