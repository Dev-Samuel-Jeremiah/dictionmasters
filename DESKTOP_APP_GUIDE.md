# Diction Masters — the computer app (Windows, Mac, Linux)

This guide covers building, publishing and changing the Diction Masters app
for computers. It works the same way as the Android app (see
`MOBILE_APP_GUIDE.md`), so if you know that one, you know this one.

---

## 1. How it works (and why website changes reach it by themselves)

```
 ┌──────────────────────────┐        ┌────────────────────────────────┐
 │  Computer app            │  opens │  Your Django website           │
 │  (desktop/ folder)       │ ─────► │  https://www.dictionmasters.app │
 │  window, menus, icon,    │ ◄───── │  every page, every feature,    │
 │  mic, downloads, updates │  pages │  the database, the admin       │
 └──────────────────────────┘        └────────────────────────────────┘
```

The app is built with **Electron** (the tool behind apps like VS Code,
Slack and WhatsApp Desktop). It opens your live website in its own window
and adds the computer features on top.

So, exactly like the Android app:

- **You keep working on the website the way you do now.** Every change you
  deploy (a page, a feature, a lesson, the design) shows in the computer app
  the next time a page opens. Nobody downloads anything.
- **The app also updates itself.** When you change the app's own code
  (icon, menus, anything in `desktop/`) and publish a new version, every
  installed app downloads it quietly and asks to restart. That's rare.
- Django knows it's the computer app (it sends `DictionMastersApp/desktop`),
  so you can show or hide things just for it:

```django
{% if native_app.platform == "desktop" %} Only in the computer app {% endif %}
{% if native_app %} In any of the apps (Android, iPhone, computer) {% endif %}
```

```css
html[data-native-app="desktop"] .something { ... }
```

```js
if (window.DMDesktop) { /* in the computer app; DMDesktop.os is "windows", "mac" or "linux" */ }
```

---

## 2. Which computers it runs on

| Computer | File | Notes |
|---|---|---|
| Windows 10 and 11 | `DictionMasters-Setup.exe` | 64-bit |
| Windows 7, 8 and 8.1 | `DictionMasters-Setup-Windows7-8.exe` | 32- and 64-bit in one installer |
| Mac with Apple chip (M1, M2, M3, M4…) | `DictionMasters-mac-arm64.dmg` | macOS 12 or newer |
| Mac with Intel chip | `DictionMasters-mac-x64.dmg` | macOS 12 or newer |
| Older Macs | `DictionMasters-mac-legacy-x64.dmg` | macOS 10.13 to 11 |
| Ubuntu, Debian, Linux Mint, Zorin, Pop!_OS | `DictionMasters-linux-amd64.deb` | 64-bit |
| Any other Linux (Fedora, Arch, …) | `DictionMasters-linux-x86_64.AppImage` | 64-bit |

**About Windows 7 and 8, and older Macs.** Microsoft and Apple stopped
updating these systems, and so did Chrome and Electron. These editions use
Electron 22 (Chrome 108), the last version that runs there. They work, and
they update themselves within that edition, but they don't get new browser
security fixes. That's fine for opening your own site; just encourage
schools to move to Windows 10/11 when they can. If one day a page needs
something Chrome 108 can't do, test it in the Windows 7 edition first (§9).

---

## 3. What was added

### In the Django project (deploy these like any other change)

| File | What changed |
|---|---|
| `apps/landing/native_app.py` | Recognises `DictionMastersApp/desktop`. Builds the download links for "Get the app". |
| `templates/native_app/get_app.html` | The "Computer" box now offers Windows / Mac / Linux downloads (the visitor's own system first). |
| `static/css/get_app.css` | Styles for those download boxes. |
| `config/settings.py` | New setting `NATIVE_APP_DESKTOP_DOWNLOAD_URL`. |
| `apps/landing/tests_native_app.py` | Tests for the above (`DesktopAppTests`). |
| `.github/workflows/desktop-app.yml` | Builds every installer on GitHub, and publishes them. |

There are no new database migrations. Websites in a normal browser look the
same as before (until you set `NATIVE_APP_DESKTOP_DOWNLOAD_URL`, the "Get the
app" page is unchanged).

### The `desktop/` folder (the app itself)

| File | What it's for |
|---|---|
| `app.settings.json` | **The one file you edit.** Name, version, website address, colours, window size. |
| `src/main.js` | The app: window, menus, links, microphone, downloads, offline screen. |
| `src/updater.js` | The app updating itself. |
| `src/preload.js` | Tiny helper loaded in every page (`window.DMDesktop`). |
| `src/offline.html` | The "You're offline" screen, built into the app. |
| `build/icon.png` | The app icon (1024×1024). Replace it to change the icon everywhere. |
| `build/entitlements.mac.plist` | Mac permissions (microphone, camera). |
| `electron-builder.config.js` | How the installers are made. You normally don't touch it. |
| `package.json`, `package-lock.json` | The tools. Commit both. |

---

## 4. First: deploy the Django changes

```bash
python manage.py test apps.landing.tests_native_app
```

Then commit and deploy as usual.

---

## 5. Build the installers (on GitHub — no Mac or Windows PC needed)

1. Commit the `desktop/` folder and `.github/workflows/desktop-app.yml`,
   and push to `main`.
2. On GitHub: **Actions → Desktop app**. It starts by itself when anything in
   `desktop/` changes; or press **Run workflow**. It takes about 10–15 minutes.
3. When it's green, open **Releases**: there's a release called
   *Diction Masters for computers 1.0.0* (tag `desktop`) with all the files.
4. On your server, set this in `.env` (with your own owner/repo) and restart:
   ```
   NATIVE_APP_DESKTOP_DOWNLOAD_URL=https://github.com/<owner>/<repo>/releases/download/desktop
   ```
   Now `https://www.dictionmasters.app/app/get/` offers the downloads, the
   visitor's own system first.

> **Private repository?** Its downloads need a GitHub login, so neither
> visitors nor the apps can reach them. Use the same fix as the Android app:
> a public repository for releases (`APK_RELEASE_REPO` variable +
> `RELEASE_TOKEN` secret). The workflow uses them automatically, and the URL
> above becomes `https://github.com/<owner>/<public-repo>/releases/download/desktop`.

The release is never marked "Latest", so the Android app's
`…/releases/latest/download/diction-masters.apk` link keeps working.

---

## 6. The warning people see when installing (and how to remove it)

Windows and Mac warn about apps that aren't signed with a paid certificate.
The app works fine; the warning just needs one extra click the first time.
The "Get the app" page already tells people what to click.

| | What people see | To remove it |
|---|---|---|
| **Windows** | "Windows protected your PC" → **More info** → **Run anyway** | A code-signing certificate (from about US$200/year, e.g. Certum, Sectigo, SSL.com; or Azure Trusted Signing, about US$10/month). Add it as repo secrets `WIN_CSC_LINK` (the `.pfx` as base64) and `WIN_CSC_KEY_PASSWORD`. |
| **Mac** | "can't be opened / can't check it" → **System Settings → Privacy & Security → Open Anyway** | An Apple Developer account (US$99/year, the same one as for iPhone). See below. |
| **Linux** | Nothing | — |

**Mac signing, step by step** (also needed for the Mac app to *update itself*;
unsigned Mac apps instead show "Update available → Download"):

1. On a Mac with Xcode: Xcode → Settings → Accounts → your team →
   **Manage Certificates → + → Developer ID Application**.
2. Keychain Access → My Certificates → right-click it → **Export** → `.p12`,
   with a password.
3. `base64 -i certificate.p12 | pbcopy` and save it as the secret
   `MAC_CSC_LINK`; the password as `MAC_CSC_KEY_PASSWORD`.
4. At https://appleid.apple.com → Sign-In and Security → **App-Specific
   Passwords**, make one. Add secrets `APPLE_ID` (your Apple ID email),
   `APPLE_APP_SPECIFIC_PASSWORD`, and `APPLE_TEAM_ID` (developer.apple.com →
   Membership).
5. Run the workflow again. The Mac app is now signed and notarised: no
   warning, and it updates itself.

---

## 7. Publishing an update to the app itself

Only for changes inside `desktop/` (website changes never need this):

1. In `desktop/app.settings.json`, raise `"version"`, e.g. `"1.0.0"` → `"1.0.1"`.
2. Commit and push to `main`. The workflow builds and publishes.
3. Within a few hours (and every time it starts), each installed app finds it:

| System | What happens |
|---|---|
| Windows (both editions) | Downloads quietly, then "Diction Masters 1.0.1 is ready — Restart now / Later". *Later* installs it when the app is next closed. |
| Linux AppImage | The same. |
| Mac, signed (§6) | The same. |
| Mac unsigned, Linux `.deb` | "Diction Masters 1.0.1 is available — Download", which opens the "Get the app" page. Installing over the old one keeps everything. |

People can also use **Help → Check for updates…** (on a Mac: the
*Diction Masters* menu).

The Windows 7/8 and older-Mac editions update from their own channel
(`legacy.yml`), so they're never offered a version that wouldn't run.

**Forgot to raise the version?** The files on the Releases page are still
replaced, so new downloads get the new app, but installed apps don't update
(they think they're up to date). Raise it and push again.

---

## 8. Try it on your own computer

You need **Node.js 22** (https://nodejs.org).

```bash
cd desktop
npm install
npm start          # opens the app on the live website
```

**Against your local Django** (to test before you deploy):

```bash
python manage.py runserver          # in one terminal
cd desktop && npm run dev           # in another: opens http://127.0.0.1:8000
```

`npm run dev` is the same as setting `"devUrl": "http://127.0.0.1:8000"` in
`app.settings.json` (the GitHub build refuses to run while `devUrl` is set,
so a test build can't be published by mistake).

**Make an installer locally** (optional; GitHub does this for you):

```bash
npm run dist:win      # on Windows → dist/DictionMasters-Setup.exe
npm run dist:win7     # on Windows → dist/DictionMasters-Setup-Windows7-8.exe
npm run dist:mac      # on a Mac   → dist/DictionMasters-mac-*.dmg
npm run dist:mac-legacy  # on a Mac → dist/DictionMasters-mac-legacy-x64.dmg
npm run dist:linux    # on Linux   → dist/*.deb and dist/*.AppImage
```

Locally built installers don't update themselves (they don't know where to
look); only the GitHub-built ones do.

**Debugging:** in the app, **Help → Troubleshooting: developer tools**
(Ctrl+Shift+I, or Cmd+Shift+I on a Mac) opens Chrome's DevTools for the page.

---

## 9. What the app does — quick reference

| Feature | How |
|---|---|
| Opens on | `/` → the welcome screen, or the dashboard if signed in (same as the phone apps) |
| Stays signed in | 180 days, like the phone apps (`NATIVE_APP_SESSION_DAYS`) |
| Links to other websites | Open in the computer's normal browser |
| Paystack | Opens inside the app; paying works as on the website |
| Microphone / camera | Allowed for your site only. Mac asks the user once. |
| Downloads | The normal "Save as" box |
| Printing | File → Print (Ctrl+P) or the site's own print buttons |
| Offline | Saved lessons open (the website's service worker). Nothing saved yet → "You're offline" with *Try again*. |
| Window | Remembers its size and position. One copy only: opening it again brings the window forward. |
| Keyboard | Alt+← / Alt+→ (Cmd+[ / Cmd+] on Mac) back/forward, Ctrl+R or F5 reload, Ctrl +/−/0 zoom, F11 full screen, Alt+Home home |
| Menus | Hidden on Windows/Linux until you press **Alt** |
| Troubleshooting | Help → *clear saved pages and reload* (stays signed in). Update log: `updates.log` in the app's data folder (`%APPDATA%\Diction Masters` on Windows, `~/Library/Application Support/Diction Masters` on Mac, `~/.config/Diction Masters` on Linux). |

### Payments

The computer app isn't sold through an app store, so there are no store
rules: **payments work in it, exactly like the website**. If you ever want
to hide buying there too, add `desktop` to the server setting:

```
NATIVE_APP_HIDE_PAYMENTS=ios,android,desktop
```

---

## 10. How to change things

| I want to… | Do this | New app version? |
|---|---|---|
| Add or change a feature, page, lesson, design or text | Change the Django site and deploy | **No** |
| Show something only in the computer app | `{% if native_app.platform == "desktop" %}` or `html[data-native-app="desktop"]` | No |
| Change the download links | `NATIVE_APP_DESKTOP_DOWNLOAD_URL` on the server | No |
| Change the app icon | Replace `desktop/build/icon.png` (1024×1024 PNG) | Yes (§7) |
| Change the app name, window size, website address | `desktop/app.settings.json` | Yes |
| Change the offline screen | `desktop/src/offline.html` | Yes |
| Change menus, links, permissions | `desktop/src/main.js` | Yes |
| Update Electron itself (about twice a year) | `cd desktop && npm install electron@latest electron-builder@latest`, test with `npm start` | Yes |

---

## 11. Troubleshooting

| Problem | Fix |
|---|---|
| Windows: "Windows protected your PC" | More info → Run anyway (§6). |
| Mac: "can't be opened because Apple cannot check it" / "is damaged" | System Settings → Privacy & Security → Open Anyway. If it still says "damaged", in Terminal: `xattr -cr "/Applications/Diction Masters.app"`. Signing (§6) ends this. |
| Linux AppImage won't start | Ubuntu 22.04+: `sudo apt install libfuse2`. Or use the `.deb`. |
| Microphone doesn't work | Windows: Settings → Privacy → Microphone → allow desktop apps. Mac: System Settings → Privacy & Security → Microphone → Diction Masters. Then reload the page. |
| "You're offline" but the internet works | Check the site is up. `siteUrl` in `app.settings.json` must match exactly, with `https://`. |
| Login doesn't stick | `DJANGO_CSRF_TRUSTED_ORIGINS` must include `https://www.dictionmasters.app` and `https://dictionmasters.app` (same as the phone apps). |
| A page looks broken only in the app | Help → Troubleshooting: clear saved pages and reload. |
| The app doesn't update | Check you raised `"version"` (§7), the workflow finished, and the release files are public. Then Help → Check for updates. Look in `updates.log` (§9). |
| GitHub build fails on "devUrl" | Set `"devUrl": ""` in `desktop/app.settings.json`. |

---

## Screenshots and screen recording are blocked

`"blockScreenCapture": true` in `app.settings.json` (the default) makes
screenshots, screen recordings and screen sharing (Zoom, Teams, Meet) show
the app's window as black:

| | |
|---|---|
| Windows 10 (2004+) and 11 | Blocked |
| Windows 7 and 8 | Blocked in most tools |
| Mac | Blocked in screenshots and most recorders; some tools on macOS 15+ ignore it |
| Linux | Not possible (the system has no such setting) |

This also stops teachers showing the app on Zoom/Teams or a shared classroom
screen. To allow capture again, set it to `false`, raise `"version"` and push
(§7). A website can't block capture, so none of this applies in a browser.
