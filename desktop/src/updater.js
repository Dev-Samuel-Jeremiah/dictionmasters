/*
 * The computer app updates itself.
 *
 * Two kinds of change, two routes:
 *   - Website changes (pages, lessons, design, features): nothing to do.
 *     The app shows the live site, so they appear the next time a page opens.
 *   - App changes (icon, menus, this code): raise "version" in
 *     app.settings.json and run the GitHub workflow. It publishes the new
 *     installers on the Releases page (tag "desktop"); every installed app
 *     checks there every few hours and on start-up.
 *
 * How each system takes the update:
 *   Windows (installer)     downloads quietly, then "Restart to update".
 *   Linux AppImage          the same.
 *   Mac                     the same IF the app is signed with an Apple
 *                           Developer ID (see DESKTOP_APP_GUIDE.md). An
 *                           unsigned Mac app can't replace itself, so it
 *                           offers the download page instead.
 *   Linux .deb              offers the download page (or update with apt).
 *
 * The Windows 7/8 edition ("legacy", built with an older Electron) follows
 * its own channel (legacy.yml) so it is never offered a version that won't
 * run on Windows 7.
 */
"use strict";

const { app, dialog, shell } = require("electron");

let autoUpdater = null;
let options = null;
let manualCheck = false;
let offeredVersion = null;
let downloadedVersion = null;

function build() { return (options && options.pkg && options.pkg.dmBuild) || {}; }
function isLegacy() {
  try { return Boolean(require("../package.json").dmBuild && require("../package.json").dmBuild.legacy); }
  catch (error) { return false; }
}

function canInstallItself() {
  if (process.platform === "win32") return true;
  if (process.platform === "linux") return Boolean(process.env.APPIMAGE);
  if (process.platform === "darwin") return Boolean(build().macSigned);
  return false;
}

function win() { return options && options.getWindow ? options.getWindow() : null; }

function message(opts) {
  const w = win();
  return w && !w.isDestroyed() ? dialog.showMessageBox(w, opts) : dialog.showMessageBox(opts);
}

function openDownloadPage() {
  shell.openExternal(options.site + (options.settings.downloadPage || "/app/get/#computer"));
}

// A short log of update checks, for troubleshooting:
//   Windows  %APPDATA%\Diction Masters\updates.log
//   Mac      ~/Library/Application Support/Diction Masters/updates.log
//   Linux    ~/.config/Diction Masters/updates.log
function fileLogger() {
  const fs = require("fs");
  const path = require("path");
  const file = path.join(app.getPath("userData"), "updates.log");
  const write = (level) => (msg) => {
    try {
      if (fs.existsSync(file) && fs.statSync(file).size > 200 * 1024) fs.renameSync(file, file + ".old");
      fs.appendFileSync(file, `${new Date().toISOString()} ${level} ${msg}\n`);
    } catch (error) { /* can't write the log: never stop the app for it */ }
  };
  return { info: write("info"), warn: write("warn"), error: write("error"), debug: () => {} };
}

function start(opts) {
  options = opts;
  // Only installed apps update: not `npm start`, not while testing locally.
  if (!app.isPackaged || opts.devMode) return;

  try {
    autoUpdater = require("electron-updater").autoUpdater;
  } catch (error) {
    return; // updater missing from this build: the app still works
  }

  autoUpdater.logger = fileLogger();
  autoUpdater.autoDownload = canInstallItself();
  autoUpdater.autoInstallOnAppQuit = canInstallItself();
  if (isLegacy()) autoUpdater.channel = "legacy";
  autoUpdater.allowDowngrade = false;
  autoUpdater.allowPrerelease = false;

  autoUpdater.on("update-available", (info) => {
    if (canInstallItself()) {
      if (manualCheck) {
        message({ type: "info", buttons: ["OK"], message: `Downloading version ${info.version}…`,
          detail: "Keep using the app. We'll tell you when it's ready." });
      }
      return;
    }
    // Can't install itself: offer the download page, once per version.
    if (offeredVersion === info.version && !manualCheck) return;
    offeredVersion = info.version;
    message({
      type: "info", buttons: ["Download", "Later"], defaultId: 0, cancelId: 1,
      title: "Update available",
      message: `Diction Masters ${info.version} is available`,
      detail: `You have version ${app.getVersion()}. Download the new version and install it over this one: your account and saved lessons stay.`,
    }).then(({ response }) => { if (response === 0) openDownloadPage(); });
  });

  autoUpdater.on("update-not-available", () => {
    if (manualCheck) {
      message({ type: "info", buttons: ["OK"], message: "You're up to date",
        detail: `Diction Masters ${app.getVersion()} is the newest version.` });
    }
    manualCheck = false;
  });

  autoUpdater.on("update-downloaded", (info) => {
    manualCheck = false;
    if (downloadedVersion === info.version) return;
    downloadedVersion = info.version;
    message({
      type: "info", buttons: ["Restart now", "Later"], defaultId: 0, cancelId: 1,
      title: "Update ready",
      message: `Diction Masters ${info.version} is ready`,
      detail: "Restart the app to finish updating. If you choose Later, it updates the next time you close the app.",
    }).then(({ response }) => {
      if (response === 0) setImmediate(() => autoUpdater.quitAndInstall(false, true));
    });
  });

  autoUpdater.on("error", (error) => {
    if (manualCheck) {
      manualCheck = false;
      message({
        type: "warning", buttons: ["Open download page", "OK"], defaultId: 1, cancelId: 1,
        message: "Couldn't check for updates",
        detail: "Check your internet connection and try again, or download the newest version from the website.",
      }).then(({ response }) => { if (response === 0) openDownloadPage(); });
    }
    // Otherwise stay quiet: no internet is normal. We'll try again later.
    void error;
  });

  const check = () => { autoUpdater.checkForUpdates().catch(() => {}); };
  setTimeout(check, 15 * 1000);
  const hours = Number(opts.settings.updateCheckHours) || 4;
  setInterval(check, hours * 60 * 60 * 1000);
}

function checkNow(fromMenu) {
  if (!autoUpdater) {
    message({
      type: "info", buttons: ["Open download page", "OK"], defaultId: 1, cancelId: 1,
      message: `Diction Masters ${app.getVersion()}`,
      detail: app.isPackaged
        ? "This copy can't check for updates by itself. The download page always has the newest version."
        : "Updates are checked only in the installed app, not while testing.",
    }).then(({ response }) => { if (response === 0 && options) openDownloadPage(); });
    return;
  }
  if (downloadedVersion) {
    const version = downloadedVersion;
    downloadedVersion = null; // so the "ready" message shows again
    autoUpdater.emit("update-downloaded", { version });
    return;
  }
  manualCheck = Boolean(fromMenu);
  autoUpdater.checkForUpdates().catch(() => {});
}

module.exports = { start, checkNow, isLegacy };
