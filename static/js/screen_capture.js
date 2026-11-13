/*
 * Screenshots and screen recording in the apps (apps/landing/capture.py).
 *
 * The Android app and the computer app start every window blocked. This
 * page tells the app whether the person signed in may capture it: only
 * staff and admins, and only while the control room's switch is on
 * (Control room > Screen protection). Everyone else stays blocked.
 *
 *   window.DMScreen.setSecure(block)          the Android app
 *   window.DMDesktop.setCaptureBlocked(block) the computer app
 *
 * In a web browser, or an older app without these, nothing happens.
 */
(function () {
  "use strict";
  var me = document.currentScript;
  var block = !(me && me.getAttribute("data-capture") === "allow");
  try {
    if (window.DMScreen && typeof window.DMScreen.setSecure === "function") window.DMScreen.setSecure(block);
    if (window.DMDesktop && typeof window.DMDesktop.setCaptureBlocked === "function") window.DMDesktop.setCaptureBlocked(block);
  } catch (error) { /* the app keeps the window blocked */ }
})();
