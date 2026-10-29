/*
 * How the installers are built (electron-builder). You normally DON'T edit
 * this file: change app.settings.json instead. See DESKTOP_APP_GUIDE.md.
 *
 * Two editions are built from the same code:
 *
 *   normal   Windows 10/11, macOS 12+, Linux. The current Electron.
 *   legacy   Windows 7, 8 and 8.1 (32- and 64-bit), and older Macs
 *            (macOS 10.13–11). Electron 22, the last one that runs there.
 *            Build it with DM_LEGACY=1. It updates from its own channel, so
 *            it is never offered a version that wouldn't run.
 *
 * Environment (set by .github/workflows/desktop-app.yml):
 *   DM_LEGACY=1          build the legacy edition
 *   DM_UPDATE_URL        where installed apps look for updates, e.g.
 *                        https://github.com/<owner>/<repo>/releases/download/desktop
 *   DM_RELEASE=1         refuse to build while devUrl is set
 *   CSC_LINK / CSC_KEY_PASSWORD                     Mac (or Windows) signing certificate
 *   APPLE_ID / APPLE_APP_SPECIFIC_PASSWORD / APPLE_TEAM_ID   Mac notarisation
 */
const settings = require("./app.settings.json");

const legacy = process.env.DM_LEGACY === "1";
const updateUrl = (process.env.DM_UPDATE_URL || "").replace(/\/+$/, "");
const macSigned = Boolean(process.env.CSC_LINK) && process.platform === "darwin";
const notarize = macSigned && Boolean(process.env.APPLE_ID && process.env.APPLE_APP_SPECIFIC_PASSWORD && process.env.APPLE_TEAM_ID);

if (process.env.DM_RELEASE === "1" && settings.devUrl) {
  throw new Error('app.settings.json still has "devUrl" set. Empty it ("devUrl": "") before publishing.');
}

const name = "DictionMasters";

/** @type {import('electron-builder').Configuration} */
module.exports = {
  appId: settings.appId,
  productName: settings.appName,
  copyright: `© ${new Date().getFullYear()} Diction Masters`,
  directories: { output: "dist", buildResources: "build" },
  files: ["src/**/*", "app.settings.json", "package.json", "build/icon.png"],
  asar: true,

  // Electron 22 for the Windows 7/8 edition; otherwise the version in package.json.
  ...(legacy ? { electronVersion: "22.3.27" } : {}),

  // Written into the app's package.json: the version people see, and what
  // the updater needs to know about this build (src/updater.js).
  extraMetadata: {
    version: settings.version,
    desktopName: "diction-masters.desktop",
    dmBuild: { legacy, macSigned, updateUrl },
  },

  publish: updateUrl
    ? [{ provider: "generic", url: updateUrl, channel: legacy ? "legacy" : "latest" }]
    : null,

  // ------------------------------------------------------------ Windows
  win: {
    target: [{ target: "nsis", arch: legacy ? ["x64", "ia32"] : ["x64"] }],
    icon: "build/icon.png",
    artifactName: legacy ? `${name}-Setup-Windows7-8.\${ext}` : `${name}-Setup.\${ext}`,
  },
  nsis: {
    oneClick: false,
    perMachine: false,
    allowElevation: true,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: "always",
    createStartMenuShortcut: true,
    shortcutName: settings.appName,
    runAfterFinish: true,
    deleteAppDataOnUninstall: false,
    differentialPackage: false,
  },

  // ---------------------------------------------------------------- Mac
  mac: {
    target: [
      { target: "dmg", arch: legacy ? ["x64"] : ["x64", "arm64"] },
      { target: "zip", arch: legacy ? ["x64"] : ["x64", "arm64"] }, // the updater uses the .zip
    ],
    icon: "build/icon.png",
    category: "public.app-category.education",
    minimumSystemVersion: legacy ? "10.13" : "12.0",
    artifactName: legacy ? `${name}-mac-legacy-\${arch}.\${ext}` : `${name}-mac-\${arch}.\${ext}`,
    // Without an Apple certificate: "ad-hoc" signed, so it opens on Apple
    // silicon Macs (people must allow it once, see the guide).
    identity: macSigned ? undefined : "-",
    hardenedRuntime: macSigned,
    gatekeeperAssess: false,
    entitlements: "build/entitlements.mac.plist",
    entitlementsInherit: "build/entitlements.mac.plist",
    notarize,
    extendInfo: {
      NSMicrophoneUsageDescription: "Diction Masters uses the microphone so you can record yourself speaking and get feedback on your pronunciation.",
      NSCameraUsageDescription: "Diction Masters uses the camera to scan the QR codes printed in your EchoSpell books.",
    },
  },
  dmg: {
    title: settings.appName,
    writeUpdateInfo: false,
  },

  // -------------------------------------------------------------- Linux
  linux: {
    target: [
      { target: "AppImage", arch: ["x64"] },
      { target: "deb", arch: ["x64"] },
    ],
    icon: "build/icon.png",
    category: "Education",
    synopsis: "Learn to speak English clearly and confidently.",
    maintainer: "Techmiary Technology Concepts <sales@techmiary.cloud>",
    executableName: "diction-masters",
    syncDesktopName: true,
    artifactName: `${name}-linux-\${arch}.\${ext}`,
    desktop: { entry: { StartupWMClass: settings.appName } },
  },
};
