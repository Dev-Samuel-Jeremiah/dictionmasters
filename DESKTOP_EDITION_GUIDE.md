# The offline computer app — the website's side

The **offline app** for Windows and Linux is its own project
(`dictionmasters-desktop`, see its README). It installs with every lesson on
the computer and opens them with an **activation code**. This website only
does three small things for it, all in `apps/desktop_edition`:

| | Where |
|---|---|
| **Activation codes**: make them, see the computers using each, free a seat, stop a code | `/admin/` → *Activation codes* |
| **Lessons releases**: a snapshot of every lesson for the app, built in the background | `/admin/` → *Lessons releases* → *Add* |
| **What the app calls** (activate, check in, download new lessons) | `/desktop-app/…` |

(Not to be confused with `DESKTOP_APP_GUIDE.md`, the older *online* computer
app that opened the live website.)

---

## 1. One-time setup on the server

```bash
python manage.py migrate
python manage.py desktop_keys
```

`desktop_keys` prints two lines. Add them to `.env`, plus a build token
(any long random text), and restart:

```
DESKTOP_LICENCE_PRIVATE_KEY=...      # signs each computer's licence
DESKTOP_CONTENT_KEY=...              # seals the lessons
DESKTOP_BUILD_TOKEN=<long random text>   # lets the app's GitHub build download the lessons
```

**Never change the first two after the first installer is out**: installed
apps only trust licences signed with that key, and only open lessons sealed
with that content key. Keep a copy somewhere safe. (Until they're set, both
are made from `DJANGO_SECRET_KEY`: fine for testing, not for real installers.)

Optional: `DESKTOP_RECHECK_DAYS=60` makes every activated computer connect at
least once every 60 days (so a stopped code or a freed seat reaches it).
The default, `0`, never asks, which suits schools with no internet.

## 2. Build a lessons release

```bash
python manage.py export_desktop_content                      # every level
python manage.py export_desktop_content --levels "Level 1,Level 2" --no-videos
```

or `/admin/` → *Lessons releases* → *Add* (runs in the background; refresh to
follow it). For each level it renders every lesson page exactly as a pupil of
that level sees it — from the same list the website's offline mode uses
(`apps/offline/catalog.py`, so a new learning tool added there reaches the app
too) — and gathers every picture, recording, video, read-along timing and
answer key, sealed. Only files that changed are stored again, and installed
apps download only those.

**Build a release whenever you've changed lessons** you want computers to
get. Installed apps check every few hours while online.

The pages are rendered as hidden pupils, one per level
(`level-1@desktop-export.invalid`, …). They can't sign in, have no school, and
their plan never ends. Leave them be: deleting one just makes it again.

`--to FOLDER` also writes the release to a folder, to try the app with your
own lessons (the app's README, "Try it on your own computer").

## 3. Make activation codes

`/admin/` → *Activation codes* → *Add*: who it's for, which levels (none
ticked = every level), how many computers (*seats*), and an end date (or none).
*How many* makes a batch at once. Or:

```bash
python manage.py make_activation_codes --holder "White Diamonds Academy" --count 30 --levels "Level 1" --seats 1 --until 2027-07-31
```

Codes look like `DM-K7QX-3MPA-9VTR` (no 0/O, 1/I/L, 5/S, 2/Z, so they're easy to type).

| To… | Do this |
|---|---|
| Move a code to a new computer | Open the code, tick **Revoked** on the old computer, save. |
| Give a school more computers | Raise **Seats**. |
| Stop a code | Untick **Is active**. Each computer locks when it next goes online. |
| Extend a code | Change **Valid until**. Computers pick it up when they next go online. |
| See who uses a code | The computers are listed under it: name, learner, app version, lessons release, last seen. |

## 4. Publish the installers

In the app's repository: set the secret `DM_BUILD_TOKEN` to the same value as
`DESKTOP_BUILD_TOKEN`, then run *Actions → Build installers*. It downloads the
newest release into the installers. Details in the app's README.

---

## What's in `apps/desktop_edition`

| File | |
|---|---|
| `models.py` | `ActivationCode`, `Activation` (one computer), `ContentRelease` |
| `keys.py` | Licence signing (Ed25519) and lesson sealing (AES-256-GCM, a key per level) |
| `export.py` | Building a release: render, gather, seal, store |
| `views.py`, `urls.py` | `/desktop-app/activate/`, `check/`, `content/latest/`, `content/blob/<id>/`, `public-key/` |
| `admin.py` | The two admin pages |
| `management/commands/` | `export_desktop_content`, `make_activation_codes`, `desktop_keys` |
| `tests.py` | `python manage.py test apps.desktop_edition` |

Sealed files and release lists live in storage (R2) under `desktop-content/`.
Apps download them straight from R2 (the website only redirects), so big
downloads don't go through the server.

### If you change the website's marking rules

`apps/echospell/marking.py` is copied in the app (`src/main/marking.js`) so
activities are marked offline. Change both together.

### If a page looks wrong in the app

The app hides what needs the internet (search, notifications, the account
menu, Scan & Listen, the tutor, buying) with its own stylesheet. To hide
something else only in the offline app, the export sends the header
`X-DM-Desktop-Edition: 1` while rendering, and the user agent contains
`DictionMastersEdition/offline`.
