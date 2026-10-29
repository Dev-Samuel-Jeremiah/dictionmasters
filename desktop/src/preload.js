/*
 * Runs in every page of the computer app, before the page's own scripts.
 * Kept tiny on purpose: the website does the work (static/js/*.js).
 *
 * Pages can check  window.DMDesktop  to know they're in the computer app:
 *   if (window.DMDesktop) { ... }   // DMDesktop.os = "windows" | "mac" | "linux"
 */
"use strict";

const { contextBridge } = require("electron");

const OS = { win32: "windows", darwin: "mac", linux: "linux" }[process.platform] || process.platform;

contextBridge.exposeInMainWorld("DMDesktop", Object.freeze({ platform: "desktop", os: OS }));

// The mouse's back / forward side buttons (Mac and Linux; Windows is handled in main.js).
if (process.platform !== "win32") {
  window.addEventListener("mouseup", (event) => {
    if (event.button === 3) { event.preventDefault(); history.back(); }
    if (event.button === 4) { event.preventDefault(); history.forward(); }
  });
}

// Back online: send progress made offline straight away (static/js/offline_sync.js).
window.addEventListener("online", () => {
  try {
    if (navigator.serviceWorker && navigator.serviceWorker.controller) {
      navigator.serviceWorker.controller.postMessage("sync-learning");
    }
  } catch (error) { /* page without the service worker */ }
});
