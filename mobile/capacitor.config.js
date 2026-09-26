/*
 * Capacitor configuration for the Diction Masters Android and iPhone apps.
 *
 * You normally DON'T edit this file — change app.settings.json instead,
 * then run `npm run sync`. Everything below is built from those settings.
 *
 * How the app works: the native app opens your live Django site
 * (settings.siteUrl) in a fast, full-screen native web view and adds
 * phone features on top (see static/js/native_app.js in the Django
 * project). So every change you deploy to the website appears in the
 * apps straight away — no app-store update needed.
 */
const settings = require("./app.settings.json");

// While testing against your own computer (devUrl in app.settings.json),
// the app opens that address instead of the live site.
const devUrl = (settings.devUrl || "").replace(/\/+$/, "");
const siteUrl = devUrl || settings.siteUrl.replace(/\/+$/, "");
const devHost = devUrl ? new URL(devUrl).hostname : null;

/** @type {import('@capacitor/cli').CapacitorConfig} */
const config = {
  appId: settings.appId,
  appName: settings.appName,

  // Local fallback pages (loading + offline screen), shipped inside the app.
  webDir: "www",

  server: {
    // The Django site the app opens.
    url: siteUrl,
    // Shown when the site can't be reached (no internet, server down).
    errorPath: "offline.html",
    // Addresses allowed to open inside the app window.
    allowNavigation: [...settings.appHosts, ...settings.paymentHosts, ...(devHost ? [devHost] : [])],
    // Plain http:// is only allowed while testing on your own computer.
    cleartext: Boolean(devUrl),
  },

  android: {
    // Django recognises the app by this (apps/landing/native_app.py).
    appendUserAgent: "DictionMastersApp/android",
    allowMixedContent: Boolean(devUrl),
    captureInput: true,
    // true while you are testing (lets Chrome's chrome://inspect see the app);
    // `npm run build:android` switches it off for the store build.
    webContentsDebuggingEnabled: process.env.DM_RELEASE !== "1",
    // Newer Android draws under the status bar; keep the page below it.
    adjustMarginsForEdgeToEdge: "auto",
    backgroundColor: settings.colors.brand,
  },

  ios: {
    appendUserAgent: "DictionMastersApp/ios",
    contentInset: "automatic",
    backgroundColor: settings.colors.brand,
    // Lets the service worker run on iPhone, so offline lessons work.
    limitsNavigationsToAppBoundDomains: settings.iosAppBoundDomains && !devUrl,
    webContentsDebuggingEnabled: process.env.DM_RELEASE !== "1",
    scrollEnabled: true,
  },

  plugins: {
    SplashScreen: {
      launchShowDuration: Math.round(settings.splashSeconds * 1000),
      launchAutoHide: true,
      backgroundColor: settings.colors.splashBackground,
      androidScaleType: "CENTER_CROP",
      showSpinner: false,
      splashFullScreen: false,
      splashImmersive: false,
    },
    StatusBar: {
      overlaysWebView: false,
      style: "DARK", // light text, for the dark navy bar
      backgroundColor: settings.colors.statusBar,
    },
    Keyboard: {
      resize: "native",
      resizeOnFullScreen: true,
    },
  },
};

module.exports = config;
