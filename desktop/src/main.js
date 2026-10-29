/*
 * Diction Masters for Windows, Mac and Linux.
 *
 * Like the Android and iPhone apps, this is a native window that opens the
 * LIVE website (siteUrl in app.settings.json). Every page still comes from
 * Django, so whatever you deploy to the website shows up in the computer
 * app straight away — no new download needed.
 *
 * Django knows it is the computer app because the app adds
 * "DictionMastersApp/desktop" to its User-Agent (apps/landing/native_app.py),
 * so templates can use {% if native_app.platform == "desktop" %}.
 *
 * What this file adds on top of the website:
 *   - one window that remembers its size and position
 *   - links to other websites open in the computer's own browser
 *   - Paystack payments open inside the app, like on the website
 *   - microphone (pronunciation practice) and camera (QR codes) allowed
 *     for the Diction Masters site only
 *   - downloads go through the normal "Save as" box
 *   - a "You're offline" screen, and saved lessons offline
 *   - menus and keyboard shortcuts (back, reload, zoom, full screen)
 *   - the app updates ITSELF when you publish a new version (updater.js)
 *
 * This file must keep working on Electron 22 too: that is the last version
 * that runs on Windows 7 and 8 (the "legacy" build). So: CommonJS, no
 * brand-new Electron APIs.
 */
"use strict";

const path = require("path");
const fs = require("fs");
const {
  app, BrowserWindow, Menu, shell, session, dialog, systemPreferences, nativeTheme,
} = require("electron");

const settings = require("../app.settings.json");
const pkg = require("../package.json");
const updater = require("./updater");

// ----------------------------------------------------------------- settings
// DM_DEV_URL (environment) or devUrl (settings) = test against your own Django.
const devUrl = (process.env.DM_DEV_URL || settings.devUrl || "").replace(/\/+$/, "");
const SITE = devUrl || settings.siteUrl.replace(/\/+$/, "");
const SITE_HOST = new URL(SITE).host;

const APP_HOSTS = new Set([...settings.appHosts, SITE_HOST]);
const PAYMENT_HOSTS = settings.paymentHosts || [];

function hostMatches(host, pattern) {
  if (pattern.startsWith("*.")) return host.endsWith(pattern.slice(1));
  return host === pattern;
}
function isAppUrl(url) {
  try {
    const u = new URL(url);
    return /^https?:$/.test(u.protocol) && APP_HOSTS.has(u.host);
  } catch (error) { return false; }
}
function isPaymentUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" && PAYMENT_HOSTS.some((p) => hostMatches(u.hostname, p));
  } catch (error) { return false; }
}
function isLocalPage(url) { return url.startsWith("file://"); }

// ---------------------------------------------------------- linux sandbox
// Ubuntu 24.04+ blocks the sandbox Chromium uses inside an AppImage. The
// .deb package doesn't have this problem; for the AppImage, fall back so it
// still opens (the app only ever shows the Diction Masters site).
if (process.platform === "linux" && process.env.APPIMAGE) {
  try {
    const flag = fs.readFileSync("/proc/sys/kernel/apparmor_restrict_unprivileged_userns", "utf8").trim();
    if (flag === "1") app.commandLine.appendSwitch("no-sandbox");
  } catch (error) { /* file absent: not restricted */ }
}

// ------------------------------------------------------------- user agent
// Chrome's normal description of itself + "DictionMastersApp/desktop".
// "Electron/..." is removed so sites treat the app as ordinary Chrome.
function appUserAgent(defaultAgent) {
  const cleaned = defaultAgent
    .replace(/\sElectron\/\S+/i, "")
    .replace(/\sDiction[\w-]*\/\S+/gi, ""); // "DictionMasters/1.0.0" (the app's own name)
  return `${cleaned} DictionMastersApp/desktop`;
}

// ------------------------------------------------------------ window state
const stateFile = () => path.join(app.getPath("userData"), "window-state.json");

function loadWindowState() {
  const w = settings.window || {};
  const fallback = { width: w.width || 1280, height: w.height || 820, maximized: false };
  try {
    const saved = JSON.parse(fs.readFileSync(stateFile(), "utf8"));
    const { screen } = require("electron");
    // Only reuse the position if it is still on a connected screen.
    const visible = screen.getAllDisplays().some((d) => {
      const a = d.workArea;
      return saved.x >= a.x - 50 && saved.y >= a.y - 50 && saved.x < a.x + a.width && saved.y < a.y + a.height;
    });
    if (!visible) { delete saved.x; delete saved.y; }
    return Object.assign(fallback, saved);
  } catch (error) {
    return fallback;
  }
}

function trackWindowState(win) {
  let timer = null;
  const save = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (win.isDestroyed()) return;
      const bounds = win.getNormalBounds ? win.getNormalBounds() : win.getBounds();
      const state = Object.assign({}, bounds, { maximized: win.isMaximized() });
      try { fs.writeFileSync(stateFile(), JSON.stringify(state)); } catch (error) { /* read-only disk */ }
    }, 400);
  };
  ["resize", "move", "maximize", "unmaximize"].forEach((e) => win.on(e, save));
  win.on("close", save);
}

// -------------------------------------------------------------- offline
// When a page can't be loaded (no internet, site down) we show our own
// offline screen. It first tries the lessons saved by the website's
// service worker; only if nothing is saved does it say "connect once".
let lastOfflineAt = 0;

function showOffline(win, failedUrl) {
  const firstRun = Date.now() - lastOfflineAt < 15000;
  lastOfflineAt = Date.now();
  win.loadFile(path.join(__dirname, "offline.html"), {
    query: { site: SITE, failed: failedUrl || "", first: firstRun ? "1" : "0" },
  });
}

// --------------------------------------------------------------- windows
let mainWindow = null;

function webPreferences() {
  return {
    preload: path.join(__dirname, "preload.js"),
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: true,
    spellcheck: true,
  };
}

function attachHandlers(win) {
  const wc = win.webContents;

  // Links that open a new window.
  wc.setWindowOpenHandler(({ url }) => {
    if (isAppUrl(url) || isPaymentUrl(url)) {
      // Our own pages (a PDF, a printable page) and Paystack's pop-up open
      // in a new app window, like a new tab in a browser.
      return {
        action: "allow",
        overrideBrowserWindowOptions: {
          width: 1100, height: 780, autoHideMenuBar: true,
          backgroundColor: settings.colors.brand,
          icon: iconPath(),
          webPreferences: webPreferences(),
        },
      };
    }
    if (/^(https?|mailto|tel|sms|whatsapp):/i.test(url)) shell.openExternal(url);
    return { action: "deny" };
  });

  wc.on("did-create-window", (child) => attachHandlers(child));

  // Clicking a link to another website: open it in the computer's browser.
  let inPayment = false; // during a payment, the bank's security check may open its own page
  wc.on("did-navigate", (event, url) => {
    if (isPaymentUrl(url)) inPayment = true;
    else if (isAppUrl(url)) inPayment = false;
  });
  const guard = (event, url) => {
    if (isAppUrl(url) || isPaymentUrl(url) || isLocalPage(url)) return;
    if (inPayment && url.startsWith("https://")) return;
    event.preventDefault();
    if (/^(https?|mailto|tel|sms|whatsapp):/i.test(url)) shell.openExternal(url);
  };
  wc.on("will-navigate", guard);
  wc.on("will-redirect", (event, url, isInPlace, isMainFrame) => { if (isMainFrame) guard(event, url); });

  // Page couldn't load at all.
  wc.on("did-fail-load", (event, code, description, url, isMainFrame) => {
    if (!isMainFrame) return;
    if (code === -3) return; // ERR_ABORTED: user clicked elsewhere, a download started...
    if (win === mainWindow && (isAppUrl(url) || !url)) showOffline(win, url);
  });

  // Windows: the mouse's back/forward buttons.
  win.on("app-command", (event, command) => {
    if (command === "browser-backward" && wc.canGoBack()) wc.goBack();
    if (command === "browser-forward" && wc.canGoForward()) wc.goForward();
  });

  // Right-click menu: copy, paste, spelling suggestions.
  wc.on("context-menu", (event, params) => {
    const items = [];
    (params.dictionarySuggestions || []).slice(0, 5).forEach((word) => {
      items.push({ label: word, click: () => wc.replaceMisspelling(word) });
    });
    if (params.misspelledWord) {
      items.push({ label: "Add to dictionary", click: () => wc.session.addWordToSpellCheckerDictionary(params.misspelledWord) });
      items.push({ type: "separator" });
    }
    if (params.linkURL) {
      items.push({ label: "Open link in browser", click: () => shell.openExternal(params.linkURL) });
      items.push({ label: "Copy link", click: () => require("electron").clipboard.writeText(params.linkURL) });
      items.push({ type: "separator" });
    }
    if (params.isEditable) {
      items.push({ role: "undo" }, { role: "redo" }, { type: "separator" }, { role: "cut" }, { role: "copy" }, { role: "paste" }, { role: "selectAll" });
    } else if (params.selectionText) {
      items.push({ role: "copy" });
    } else {
      items.push(
        { label: "Back", enabled: wc.canGoBack(), click: () => wc.goBack() },
        { label: "Forward", enabled: wc.canGoForward(), click: () => wc.goForward() },
        { label: "Reload", click: () => wc.reload() },
      );
    }
    Menu.buildFromTemplate(items).popup({ window: win });
  });
}

function iconPath() {
  // Linux uses this for the window icon; Windows and Mac use the packaged icon.
  const p = path.join(__dirname, "..", "build", "icon.png");
  return fs.existsSync(p) ? p : undefined;
}

function createMainWindow(startUrl) {
  const state = loadWindowState();
  const w = settings.window || {};
  mainWindow = new BrowserWindow({
    x: state.x, y: state.y, width: state.width, height: state.height,
    minWidth: w.minWidth || 380, minHeight: w.minHeight || 560,
    title: settings.appName,
    icon: iconPath(),
    show: false,
    backgroundColor: settings.colors.brand,
    autoHideMenuBar: true, // Alt shows the menu on Windows and Linux
    webPreferences: webPreferences(),
  });
  if (state.maximized) mainWindow.maximize();
  trackWindowState(mainWindow);
  attachHandlers(mainWindow);

  mainWindow.once("ready-to-show", () => mainWindow.show());
  // Never leave a blank window if the first page is slow.
  setTimeout(() => { if (mainWindow && !mainWindow.isDestroyed() && !mainWindow.isVisible()) mainWindow.show(); }, 4000);

  mainWindow.on("closed", () => { mainWindow = null; });
  mainWindow.loadURL(startUrl || SITE + "/").catch(() => { /* did-fail-load shows the offline screen */ });
}

// ------------------------------------------------------------ permissions
function setUpSession() {
  const ses = session.defaultSession;
  ses.setUserAgent(appUserAgent(ses.getUserAgent()));
  app.userAgentFallback = appUserAgent(app.userAgentFallback);

  const ALLOWED = new Set([
    "media", "mediaKeySystem", "notifications", "fullscreen", "clipboard-sanitized-write",
    "clipboard-read", "pointerLock", "speaker-selection",
  ]);
  ses.setPermissionRequestHandler((wc, permission, callback, details) => {
    const url = (details && (details.requestingUrl || details.securityOrigin)) || wc.getURL();
    if (!isAppUrl(url) || !ALLOWED.has(permission)) return callback(false);
    if (permission === "media" && process.platform === "darwin") {
      // macOS asks the user once, then remembers.
      const types = (details && details.mediaTypes) || ["audio"];
      Promise.all(types.map((t) => systemPreferences.askForMediaAccess(t === "video" ? "camera" : "microphone")))
        .then((answers) => callback(answers.every(Boolean)))
        .catch(() => callback(false));
      return;
    }
    callback(true);
  });
  ses.setPermissionCheckHandler((wc, permission, origin) => {
    return isAppUrl(origin || (wc && wc.getURL()) || "") && ALLOWED.has(permission);
  });

  // Downloads: the normal "Save as" box, starting in the Downloads folder.
  ses.on("will-download", (event, item) => {
    item.setSaveDialogOptions({ defaultPath: path.join(app.getPath("downloads"), item.getFilename()) });
  });

  // Spell-check in British English, like the lessons.
  try {
    const langs = ses.availableSpellCheckerLanguages || [];
    if (langs.includes("en-GB")) ses.setSpellCheckerLanguages(["en-GB"]);
  } catch (error) { /* Mac uses the system's own spell-checker */ }
}

// ------------------------------------------------------------------- menu
function buildMenu() {
  const isMac = process.platform === "darwin";
  const current = () => BrowserWindow.getFocusedWindow() || mainWindow;
  const wc = () => current() && current().webContents;
  const go = (p) => { const w = mainWindow || current(); if (w) { w.show(); w.loadURL(SITE + p).catch(() => {}); } };

  const template = [
    ...(isMac ? [{
      label: settings.appName,
      submenu: [
        { role: "about" },
        { label: "Check for updates…", click: () => updater.checkNow(true) },
        { type: "separator" },
        { role: "services" },
        { type: "separator" },
        { role: "hide" }, { role: "hideOthers" }, { role: "unhide" },
        { type: "separator" },
        { role: "quit" },
      ],
    }] : []),
    {
      label: "File",
      submenu: [
        { label: "Home", accelerator: "Alt+Home", click: () => go("/") },
        { label: "Print…", accelerator: "CmdOrCtrl+P", click: () => wc() && wc().print() },
        { type: "separator" },
        isMac ? { role: "close" } : { role: "quit", label: "Exit" },
      ],
    },
    { role: "editMenu" },
    {
      label: "View",
      submenu: [
        { label: "Back", accelerator: isMac ? "Cmd+[" : "Alt+Left", click: () => wc() && wc().canGoBack() && wc().goBack() },
        { label: "Forward", accelerator: isMac ? "Cmd+]" : "Alt+Right", click: () => wc() && wc().canGoForward() && wc().goForward() },
        { label: "Reload", accelerator: "CmdOrCtrl+R", click: () => wc() && wc().reload() },
        { label: "Reload", accelerator: "F5", visible: false, acceleratorWorksWhenHidden: true, click: () => wc() && wc().reload() },
        { type: "separator" },
        { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" },
        { label: "Zoom in", accelerator: "CmdOrCtrl+=", visible: false, acceleratorWorksWhenHidden: true, click: () => { const c = wc(); if (c) c.setZoomLevel(c.getZoomLevel() + 0.5); } },
        { type: "separator" },
        { role: "togglefullscreen" },
      ],
    },
    { role: "windowMenu" },
    {
      label: "Help",
      submenu: [
        ...(isMac ? [] : [{ label: "Check for updates…", click: () => updater.checkNow(true) }]),
        { label: "Open in web browser", click: () => { const c = wc(); shell.openExternal(c && isAppUrl(c.getURL()) ? c.getURL() : SITE + "/"); } },
        { label: "Privacy policy", click: () => go("/privacy/") },
        { type: "separator" },
        { label: "Troubleshooting: developer tools", accelerator: "CmdOrCtrl+Shift+I", click: () => wc() && wc().toggleDevTools() },
        { label: "Troubleshooting: clear saved pages and reload", click: () => clearCacheAndReload() },
        ...(isMac ? [] : [{ type: "separator" }, {
          label: `About ${settings.appName}`,
          click: () => dialog.showMessageBox(current(), {
            type: "info", title: settings.appName, message: settings.appName,
            detail: `Version ${app.getVersion()}${updater.isLegacy() ? " (Windows 7/8 edition)" : ""}\n${SITE}`,
          }),
        }]),
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

function clearCacheAndReload() {
  dialog.showMessageBox(mainWindow, {
    type: "question", buttons: ["Clear and reload", "Cancel"], defaultId: 0, cancelId: 1,
    message: "Clear saved pages?",
    detail: "This removes pages and lessons saved for offline use. You stay signed in. Use it only if a page looks broken.",
  }).then(({ response }) => {
    if (response !== 0) return;
    session.defaultSession.clearStorageData({ storages: ["serviceworkers", "cachestorage"] })
      .then(() => session.defaultSession.clearCache())
      .then(() => mainWindow && mainWindow.loadURL(SITE + "/").catch(() => {}));
  });
}

// -------------------------------------------------------------- start up
// Only one copy of the app: opening it again brings the window forward.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return createMainWindow();
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });

  if (process.platform === "win32") app.setAppUserModelId(settings.appId);
  nativeTheme.themeSource = "light";

  app.whenReady().then(() => {
    setUpSession();
    buildMenu();
    createMainWindow();
    updater.start({ settings, site: SITE, pkg, getWindow: () => mainWindow, devMode: Boolean(devUrl) });
  });

  // Mac: clicking the Dock icon with no window open opens one.
  app.on("activate", () => { if (!mainWindow) createMainWindow(); });
  app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
}
