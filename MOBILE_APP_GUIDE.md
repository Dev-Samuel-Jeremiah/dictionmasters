# Diction Masters — Android & iPhone apps

This guide covers building, publishing and changing the Diction Masters
phone apps. It's written for a learner, so it goes one step at a time.

---

## 1. How it works (and why your changes update the apps automatically)

```
 ┌──────────────────────────┐        ┌───────────────────────────────┐
 │  Android app / iPhone app│  opens │  Your Django website          │
 │  (mobile/ folder)        │ ─────► │  https://www.dictionmasters.app│
 │  native shell: icon,     │        │  every page, every feature,   │
 │  splash, mic, camera,    │ ◄───── │  the database, the admin      │
 │  back button, sharing... │  pages │  (this repository)            │
 └──────────────────────────┘        └───────────────────────────────┘
```

The apps are real native apps built with **Capacitor**, the tool Ionic
makes for this. They open your live website in a fast, full-screen native
window and add the phone features on top.

That means:

- **You keep working on the website the way you do now.** When you deploy a
  change, a new page or a new feature, both apps show it the next time
  they open a page. You don't need an app-store update.
- You need a new app-store release only for changes to the native shell:
  the app icon, name, splash screen, permissions, or files in `mobile/`.
  That's rare.
- Inside the app, Django knows it's the app (the phone sends
  `DictionMastersApp/android` or `DictionMastersApp/ios`), so you can show
  or hide things just for the app:

```django
{% if native_app %} Only in the apps {% endif %}
{% if native_app.platform == "ios" %} Only on iPhone {% endif %}
{% if not native_app %} Only on the website {% endif %}
```

```css
html[data-native-app] .something { ... }        /* both apps */
html[data-native-app="android"] .something { ... }
```

---

## 2. What was added

### In the Django project (deploy these like any other change)

| File | What it does |
|---|---|
| `apps/landing/native_app.py` | Detects the app. Opens it on a welcome screen (or the dashboard if signed in). Follows the app-store payment rules. Serves the deep-link files. |
| `static/js/native_app.js` | Phone features: Android back button, in-app browser for other websites, saving downloads, sharing, offline notice, deep links, loading bar. |
| `static/css/native_app.css` | Makes the site feel like an app. Hides "Install app" buttons and marketing links. |
| `templates/native_app/welcome.html` | The app's first screen: Log in / Create account / Join with a code / Scan a code. |
| `templates/native_app/billing_notice.html` | Shown in the app in place of the buying pages (see §8). |
| `templates/landing/privacy.html` → `/privacy/` | Privacy policy. **Both stores require one.** It's a draft: read it and edit it. |
| `templates/accounts/delete_account.html` → `/accounts/delete/` | Lets people delete their own account. **Both stores require this.** It's linked from the account menu. |
| `apps/landing/tests_native_app.py` | Tests for all of the above. |
| Small edits | `config/settings.py`, `config/urls.py`, `templates/base.html`, `templates/manage/base.html`, `static/js/pwa.js`, the billing templates, header/footer/account menu, `register_student.html`. |
| `.github/workflows/android-app.yml` | Builds the Android app on GitHub, so you don't need a powerful computer. |

The website works the same as before for everyone in a normal browser.

### The `mobile/` folder (the native app project)

| File | What it's for |
|---|---|
| `app.settings.json` | **The one file you edit.** App name, id, version, website address, colours, permission messages, deep links. |
| `capacitor.config.js` | Builds Capacitor's settings from `app.settings.json`. You normally don't touch it. |
| `package.json` | The tools and the commands (`npm run ...`). |
| `resources/` | App icon and splash screen artwork. Replace the PNGs to change them. |
| `www/offline.html` | The "You're offline" screen, built into the app. |
| `scripts/configure-native.mjs` | Applies your settings to the Android and iPhone projects: permissions, name, version, deep links, signing. |
| `scripts/check.mjs` | `npm run check` checks that everything is set up. |
| `scripts/make-artwork.py` | Redraws the default icon and splash screen. |
| `android/`, `ios/` | Created by you in §4 and §6. Commit them to git. |

---

## 3. First: deploy the Django changes

1. Test locally:
   ```bash
   python manage.py test apps.landing apps.accounts apps.billing
   python manage.py runserver
   ```
   Open http://127.0.0.1:8000/. Nothing should look different in a browser.
   There are no new database migrations.
2. Commit and push/deploy as usual.
3. Check `https://www.dictionmasters.app/privacy/` loads.
4. **See the app version in your browser:** in Chrome, open DevTools
   (F12) → the "⋮" menu → More tools → **Network conditions** → untick
   "Use browser default" under User agent → choose Custom and type
   `Mozilla/5.0 (Linux; Android 14) DictionMastersApp/android`. Reload
   `/`: you'll get the app's welcome screen. Untick the setting when you're done.

---

## 4. Android: build and run

### One-time setup (Windows, Mac or Linux)

1. Install **Node.js 22 LTS** from https://nodejs.org.
2. Install **Android Studio** from https://developer.android.com/studio.
   Open it once and let it download the Android SDK.
3. In a terminal:
   ```bash
   cd mobile
   npm install
   npm run setup:android
   ```
   This creates `mobile/android/`, applies your settings, and generates
   every icon and splash size.
4. Commit the new `mobile/android/` folder to git.

### Run it on your phone

1. On the phone: Settings → About phone → tap **Build number** 7 times →
   back → Developer options → turn on **USB debugging**.
2. Plug the phone in, then run:
   ```bash
   npm run open:android
   ```
3. Android Studio opens. Pick your phone at the top and press ▶ Run.

**Don't have Android Studio or a strong computer?** Push to GitHub and use
the **Actions → Android app** workflow. It builds an `.apk` you can install
on any Android phone, plus the `.aab` for Google Play.

### Test against Django on your computer (before you deploy)

By default the app opens the live site. To try your local changes first:

1. Find your computer's local IP address. On Windows, run `ipconfig` and
   look for the IPv4 Address, e.g. `192.168.1.5`. On Mac/Linux, run
   `ipconfig getifaddr en0` or `hostname -I`. The phone must be on the
   **same Wi-Fi**.
2. Let Django accept it. In your `.env`, add the IP to `DJANGO_ALLOWED_HOSTS`, e.g.
   `DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.5`. Then start the server so the
   phone can reach it:
   ```bash
   python manage.py runserver 0.0.0.0:8000
   ```
   Check it by opening `http://192.168.1.5:8000` in the phone's Chrome.
3. In `mobile/app.settings.json` set `"devUrl": "http://192.168.1.5:8000"`, then:
   ```bash
   npm run sync
   npm run open:android      # ▶ Run
   ```
4. **When you're done:** set `"devUrl": ""` again and `npm run sync`.
   (`npm run release` and the GitHub build refuse to run while `devUrl`
   is set, so a test build can't reach the stores by mistake.)

Note: while testing over plain `http://`, the offline videos and the
service worker don't run. That's a browser rule for insecure addresses.
Everything else works.

### Debugging

While testing, open `chrome://inspect` in Chrome on your computer with the
phone plugged in. Your app's pages show up there, with the console, the
network tab, and the other DevTools.

---

## 5. Android: publish on Google Play

1. **Create a Google Play developer account** (one-time US$25):
   https://play.google.com/console.
2. **Make your upload key** (once, and keep it safe for ever):
   ```bash
   keytool -genkey -v -keystore dictionmasters-upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload
   ```
   Back up the `.jks` file and its passwords somewhere safe, **outside git**.
   If you lose them, Google can reset the key, but it takes time.
3. **Build the release bundle** in either of these ways:
   - **Android Studio:** run `npm run release`, then `npm run open:android`
     → Build → Generate Signed App Bundle / APK → Android App Bundle →
     choose your `.jks` → release.
     The file is in `android/app/release/` or `android/app/build/outputs/bundle/release/`.
   - **GitHub Actions:** add 4 secrets to the repo (Settings → Secrets → Actions):
     - `ANDROID_KEYSTORE_BASE64`: the key file as text. Run
       `base64 -w0 dictionmasters-upload.jks` (Mac: `base64 -i dictionmasters-upload.jks`;
       Windows PowerShell: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("dictionmasters-upload.jks"))`).
     - `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` (`upload`), `ANDROID_KEY_PASSWORD`.

     Then run the workflow and download **diction-masters-aab**.
4. In Play Console: **Create app**, then fill in:
   - **Privacy policy:** `https://www.dictionmasters.app/privacy/`
   - **App access:** give the reviewer a test login (email + password) with
     an active plan.
   - **Data safety:** name, email, voice recordings (optional, for app
     functionality), app activity. Data is encrypted in transit, and users
     can request deletion at `https://www.dictionmasters.app/accounts/delete/`.
   - **Target audience:** if you include under-13s, you must follow the
     Families policy. Many school apps choose 13+ and let schools manage children.
   - Content rating questionnaire, store listing, screenshots (take them in the app).
5. Upload the `.aab` to **Internal testing** first, install it from the
   link, then promote it to Production.

> New personal developer accounts must run a **closed test with at least 12
> testers for 14 days** before Production. Plan for this.

---

## 6. iPhone: build and publish

You need **a Mac with Xcode** (free from the Mac App Store) and an **Apple
Developer account** (US$99 a year, https://developer.apple.com/programs/).
No Mac? You can rent a cloud Mac (for example MacinCloud or GitHub's macOS
runners), or ask someone with a Mac to do these steps once.

1. On the Mac, install Node.js 22 and Xcode, then:
   ```bash
   cd mobile
   npm install
   npm run setup:ios
   npm run open:ios
   ```
2. In Xcode: click **App** (left) → **Signing & Capabilities** → tick
   *Automatically manage signing* → choose your Team.
3. Plug in an iPhone and press ▶ to test it.
   To debug, use Safari on the Mac: Develop menu → your iPhone.
4. To publish: run `npm run release` first. Then in Xcode choose
   **Product → Archive** → **Distribute App → App Store Connect**.
5. In https://appstoreconnect.apple.com: create the app with the same Bundle
   ID (`app.dictionmasters.mobile`). Send the build to **TestFlight** to
   test, then **Submit for Review** with:
   - Privacy policy URL: `https://www.dictionmasters.app/privacy/`
   - **A demo account** (email + password) with an active plan, in *App Review Information*.
   - App Privacy answers: the same as Google's Data safety above.

**Apple review tips.** Apple rejects apps that are "just a website"
(guideline 4.2), and rejects in-app purchases that don't use Apple's own
system (guideline 3.1.1).
This app handles both. It has native features: microphone practice,
camera QR scanning, offline lessons and videos, sharing, background audio
for Diction Radio, an offline screen and deep links. It also hides buying in
the app (§8). In the review notes, mention the microphone practice, the QR
scanning and the offline videos.

---

## 7. Deep links (optional, recommended)

With deep links, tapping a `https://www.dictionmasters.app/...` link in
WhatsApp or an email opens the app directly.

**Android** (on by default in `app.settings.json`):
1. After your first upload, open Play Console → your app → **Test and release →
   App integrity → App signing**. Copy the **SHA-256 certificate fingerprint**.
2. On your server, set:
   ```
   NATIVE_APP_ANDROID_SHA256=AB:CD:...:EF
   ```
   Add your upload key's fingerprint too, comma-separated, so test
   builds work. Get it with `keytool -list -v -keystore dictionmasters-upload.jks`.
3. Check `https://www.dictionmasters.app/.well-known/assetlinks.json` shows it.

**iPhone:**
1. Set `NATIVE_APP_IOS_TEAM_ID=XXXXXXXXXX` on the server. Find it at
   developer.apple.com → Account → Membership.
2. In `mobile/app.settings.json` set `"deepLinks": { ..., "ios": true }`,
   then run `npm run sync`.
3. In Xcode → Signing & Capabilities, check that **Associated Domains** shows up.

Run `npm run check` to confirm both files are live.

---

## 8. Payments and the app-store rules

Apple, and Google Play for digital content, don't allow selling
subscriptions inside an app through your own payment provider like
Paystack. Breaking this rule gets the app rejected or removed. So by
default:

- **In the apps:** plans can't be bought. The "Pricing" links, "Pay now"
  and "Choose a plan" buttons, and promo codes are hidden. The buying pages
  show a short notice instead. New accounts start on the free trial.
  People who paid on the website sign in and have everything.
- **On the website:** everything works exactly as before.

Also, the app mustn't *tell* people to go and pay on the website (no
buttons or links to it), so the notice deliberately doesn't do that.

This is controlled by one server setting:

```
NATIVE_APP_HIDE_PAYMENTS=ios,android   # default: safe for both stores
NATIVE_APP_HIDE_PAYMENTS=ios           # allow Paystack inside the Android app only
```

Only allow Android payments if Google Play's payments policy allows it for
you (for example, if your app qualifies for an exemption or user-choice
billing in your country). Check the current Play policy first. If you want
in-app purchases later, the proper route is Google Play Billing and Apple
In-App Purchase (for example with the RevenueCat Capacitor plugin). That's a
separate project.

---

## 9. How to change things — quick reference

| I want to… | Do this | New store release? |
|---|---|---|
| Add or change a feature, page, lesson, design or text | Change the Django site and deploy | **No** |
| Show something only in the app | `{% if native_app %}` in a template, or `html[data-native-app]` in CSS | No |
| Change what the app's back button, links or downloads do | Edit `static/js/native_app.js`, deploy | No |
| Change the app's welcome screen | Edit `templates/native_app/welcome.html`, deploy | No |
| Change the privacy policy | Edit `templates/landing/privacy.html`, deploy | No |
| Allow/stop payments in the apps | `NATIVE_APP_HIDE_PAYMENTS` on the server | No |
| Change the app icon or splash | Replace PNGs in `mobile/resources/` → `npm run assets` → `npm run sync` | Yes |
| Change the app name or permission messages | `mobile/app.settings.json` → `npm run sync` | Yes |
| Change the website address | `siteUrl` and `appHosts` in `app.settings.json` → `npm run sync` | Yes |
| Change the offline screen | `mobile/www/offline.html` → `npm run sync` | Yes |
| Add a native feature (e.g. push notifications) | `npm install @capacitor/push-notifications` → `npm run sync` → use it from `native_app.js` via `Capacitor.Plugins.PushNotifications` | Yes |
| Change where "Get the app" downloads from | `NATIVE_APP_ANDROID_APK_URL` / `…_STORE_URL` in the server's `.env` (§12) | No |
| Publish an update to the stores | Raise `"build"` by 1 (and `"version"` if you like) in `app.settings.json` → `npm run release` → build (§5, §6) | — |

**The rule of thumb:** after editing anything in `mobile/`, run `npm run sync`.

**Updating Capacitor itself** (about once a year, when the stores ask for a
newer Android/iOS target):
```bash
cd mobile
npx cap migrate        # moves to the latest Capacitor version
npm run sync
```

---

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| App shows "You're offline" but the internet works | Check the site is up. `siteUrl` in `app.settings.json` must match exactly, with `https://`. |
| Microphone doesn't work | Android: Settings → Apps → Diction Masters → Permissions → Microphone. iPhone: Settings → Diction Masters → Microphone. Then reopen the page. |
| Links to another website open inside the app and get stuck | Add that site to `appHosts` only if it's yours. Otherwise leave it: it opens in the in-app browser, which has a Done button. |
| Login doesn't stick | Make sure `DJANGO_CSRF_TRUSTED_ORIGINS` includes `https://www.dictionmasters.app` and `https://dictionmasters.app`. |
| `npm run setup:android` fails on "SDK location not found" | Open Android Studio once so it installs the SDK, or set `ANDROID_HOME`. |
| Gradle says the Java version is wrong | Android Studio → Settings → Build Tools → Gradle → Gradle JDK: pick **JDK 21**. |
| Google Play says "target API level too low" | `npx cap migrate` to the latest Capacitor, then rebuild. |
| iPhone: offline lessons don't work | Keep `"iosAppBoundDomains": true`. It needs iOS 14 or newer. |
| iPhone: a payment or other website won't open inside the app | Expected with `iosAppBoundDomains`. Such links open in the in-app browser instead. |
| Something else | `npm run doctor` and `npm run check` in `mobile/`. |

---

## 11. Offline lessons and syncing

The app (and the website installed as an app) works without the internet:

| | How |
|---|---|
| **Pages you've opened** | Kept automatically. They open offline. |
| **Download lessons** | Me → *Offline lessons & videos* → **Download lessons**. It saves the front page of every learning tool and the lessons under them (up to 400 pages), and optionally their pictures and audio. It refreshes them by itself about twice a day on Wi-Fi. |
| **Videos** | The ⬇ button on a video, as before (encrypted on the device). |
| **Opening the app offline** | It opens on the dashboard from the device. |
| **Progress made offline** | Marking lessons complete (EchoSpell, Learning Modules, Reading Club), Quick Words lists, assessment answers, and the EchoSpell card you're on wait on the device. They're sent automatically, in order, when the phone reconnects or the app is reopened. There's also a **Sync now** button. |
| **Needs the internet** | AI feedback, the reading tutor (Yela), looking up new words, checking an answer, submitting an assessment, live Clash matches, logging in and paying. Offline, these show a clear "This needs the internet" message. |

The code lives in `templates/pwa/sw.js` (the service worker: storing pages,
the download, the sync queue), `static/js/offline_sync.js` (the download
panel and the automatic refresh) and `templates/videos/offline.html`.

**To let something else work offline:**

- A new page is covered automatically if a learner can reach it by links
  from a learning tool's front page. A brand-new tool's front page should
  also go in `DOWNLOAD_SEEDS` in `sw.js`.
- To queue a new *action* (a form that records progress), add its address
  pattern to `QUEUEABLE_PROGRESS` in `sw.js`. Only do this for actions that
  are safe to send later and don't need an answer from the server.

### Pictures and audio stored on Cloudflare R2 (one-time setup)

Lesson pictures and audio live on R2. The app can keep them offline only
if R2 allows your site to read them. Set this up once:

1. Cloudflare dashboard → **R2** → your bucket → **Settings** → **CORS policy** → **Add CORS policy**.
2. Paste this and save:
   ```json
   [
     {
       "AllowedOrigins": ["https://www.dictionmasters.app", "https://dictionmasters.app"],
       "AllowedMethods": ["GET", "HEAD"],
       "AllowedHeaders": ["*"],
       "MaxAgeSeconds": 86400
     }
   ]
   ```
3. If you serve media from your own domain (for example `media.dictionmasters.app`),
   add it to `OFFLINE_MEDIA_HOSTS` in your server's `.env`:
   `OFFLINE_MEDIA_HOSTS=r2.cloudflarestorage.com,r2.dev,media.dictionmasters.app`

Without this, lessons still download and work offline, just without their
pictures and audio.

### Testing offline

In Chrome on your computer, open DevTools → **Application** → Service
workers → tick **Offline**, then click around. On the phone, turn on
aeroplane mode.

---

## 12. Your own download: signed APK, Releases page, "Get the app" button

Once this is set up, it all happens automatically:

1. You push a change to `mobile/` (or click **Run workflow**).
2. GitHub builds the app, **signs it with your key**, and publishes it on
   your repository's **Releases** page as `diction-masters.apk`.
3. The website's **Get the app** page (`/app/get/`, linked in the footer and
   from every "Install app" button) always offers the newest one:
   - **Android:** a download button plus install steps
   - **iPhone:** "Add to Home Screen" steps (or your App Store link, later)
   - **Computer:** a QR code to open the page on a phone

None of this appears inside the app itself.

### Step A: make your signing key (once, ever)

On your computer:

```bash
# keytool comes with Java; install it if "keytool" isn't found
sudo apt install -y openjdk-21-jre-headless

keytool -genkeypair -v -keystore ~/dictionmasters-upload.jks \
  -keyalg RSA -keysize 2048 -validity 10000 -alias upload
```

It asks for a password (twice), then your name and organisation. The
Nigeria country code is **NG**. Type **yes** at the end.

**Back up `dictionmasters-upload.jks` and its password somewhere safe**
(a USB stick, or Google Drive). Never put it in git. Every update must be
signed with this same key, or phones refuse to install it over the old app.

Then turn the key into text for GitHub:

```bash
base64 -w0 ~/dictionmasters-upload.jks > ~/keystore-base64.txt
```

### Step B: give the key to GitHub

On GitHub, go to your repo → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**. Add these four, one at a time:

| Name | Value |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | everything inside `keystore-base64.txt` (open it in VS Code, Ctrl+A, Ctrl+C) |
| `ANDROID_KEYSTORE_PASSWORD` | the password you chose |
| `ANDROID_KEY_ALIAS` | `upload` |
| `ANDROID_KEY_PASSWORD` | the same password |

Then delete the text copy: `rm ~/keystore-base64.txt`.

### Step C: is your repository public or private?

The download button needs a public download link.

- **Public repository:** nothing to do.
- **Private repository:** your code stays private, and the app is published
  from a second, public repository that only holds the app:
  1. Create a new **public** repository, for example `dictionmasters-app`,
     and tick "Add a README" so it isn't empty.
  2. Create a token: GitHub (your picture) → **Settings** → **Developer settings** →
     **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
     For *Repository access*, choose only `dictionmasters-app`. For *Permissions* →
     *Contents*, choose **Read and write**.
  3. In your main repo → Settings → Secrets and variables → Actions:
     - **Secrets** tab: `RELEASE_TOKEN` = the token
     - **Variables** tab: `APK_RELEASE_REPO` = `Dev-Samuel-Jeremiah/dictionmasters-app`

### Step D: build and publish

GitHub → **Actions** → **Android app** → **Run workflow**. When it's green,
the **Releases** page shows *Diction Masters for Android …* with
`diction-masters.apk`.

### Step E: switch on the website button

Add this to the server's `.env` (use `dictionmasters-app` instead if you did Step C
for a private repository), then restart the site:

```
NATIVE_APP_ANDROID_APK_URL=https://github.com/Dev-Samuel-Jeremiah/dictionmasters/releases/latest/download/diction-masters.apk
```

That address always points to the **newest** release, so you never need to
change it again. Later, when the apps are in the stores, add:

```
NATIVE_APP_ANDROID_STORE_URL=https://play.google.com/store/apps/details?id=app.dictionmasters.mobile
NATIVE_APP_IOS_STORE_URL=https://apps.apple.com/app/idXXXXXXXXXX
```

### Also: deep links, with the same key

Your key's fingerprint lets website links open straight in the app
(section 7):

```bash
keytool -list -v -keystore ~/dictionmasters-upload.jks -alias upload | grep SHA256
```

Put the long `AB:CD:…` value in the server's `.env` as `NATIVE_APP_ANDROID_SHA256=...`.

### Updating the app

- **Website changes:** just deploy the site. The app shows them straight away.
- **App changes** (anything in `mobile/`): push. GitHub builds and publishes a
  new release with a higher version number. People download it from
  `/app/get/` and install it over the old one; their account and lessons stay.
- The **test** APK in each build's Artifacts is signed with a throwaway key,
  so it can't update a phone that has the real app. Uninstall the real app first
  if you want to try a test copy.

---

## 13. "Update available" in the app

When GitHub publishes a newer Android app (section 12), everyone using an
older one sees a panel the next time they open the app: **Update
available**, what's new, and **Update now**. Tapping it downloads the new
version, and Android asks **Update**. There's no uninstalling, and their
account, progress and downloaded lessons stay. **Later** hides it for a day.

- **What's new:** the sentence in `"releaseNotes"` in `mobile/app.settings.json`.
  Change it with each app release.
- **Force an important update:** set `NATIVE_APP_ANDROID_MIN_BUILD=<build number>`
  in the server's `.env`. Apps older than that build must update, and the
  panel has no Later button.
- The website asks GitHub for the newest release (`/app/version.json`) at most
  every 15 minutes. Nothing else to set up.
- The check itself lives on the website (`static/js/native_app.js`), so it
  already works in apps people installed before it existed.
- Remember: only changes in `mobile/` need a new app. Website changes reach
  everyone instantly, with no update.

## 14. How the app behaves offline

| | Offline |
|---|---|
| Opening the app | ✅ Opens on the saved dashboard |
| Staying signed in | ✅ The app keeps people signed in for 180 days after they last used it (`NATIVE_APP_SESSION_DAYS`), so no password is needed offline |
| Lessons, 44 Academy, Tricks, EchoSpell, Reading Club | ✅ Saved automatically: on Wi-Fi the first time you sign in (with pictures and audio), and refreshed twice a day. On mobile data just the main pages |
| Saved videos | ✅ |
| Marking lessons complete, word lists, assessment answers, lesson activities (44 Academy, Tricks, EchoSpell) | ✅ Saved on the phone, then sent and marked automatically when back online |
| First ever sign-in, creating an account | ❌ Needs the internet once: the password has to be checked by the server |
| AI feedback, the reading tutor, looking up new words, live Clash, submitting a timed assessment, paying | ❌ Need the server; the app says so clearly |

A page that was never saved shows the "saved lessons" list instead of an error.
The "Connect once to get started" screen only appears on a brand-new install
that has never been online.
