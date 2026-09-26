/*
 * Applies app.settings.json to the native Android and iPhone projects.
 *
 *   npm run configure      (also runs as part of `npm run sync`)
 *
 * Safe to run as many times as you like: every change is checked first,
 * so nothing is added twice. It edits:
 *
 *   www/app-settings.js                      the site address for the offline screen
 *   android/app/src/main/AndroidManifest.xml microphone, camera, network, deep links
 *   android/app/src/main/res/values/strings.xml  the app's name
 *   ios/App/App/Info.plist                   permission sentences, name, background audio
 *   ios/App/App/App.entitlements             iPhone deep links (Associated Domains)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const settings = JSON.parse(fs.readFileSync(path.join(root, "app.settings.json"), "utf8"));
const devUrl = (settings.devUrl || "").replace(/\/+$/, "");
if (devUrl && process.env.DM_RELEASE === "1") {
  console.error("\n✘ devUrl is set in app.settings.json (" + devUrl + ").\n  Empty it (\"devUrl\": \"\") before building for the stores, then run this again.\n");
  process.exit(1);
}
if (devUrl) console.log(`• TEST MODE: the app will open ${devUrl} (your computer), not the live site.`);
const siteUrl = devUrl || settings.siteUrl.replace(/\/+$/, "");
const siteHost = new URL(siteUrl).host;

const done = [];
const read = (p) => fs.readFileSync(p, "utf8");
function write(p, text, label) {
  if (fs.existsSync(p) && read(p) === text) return;
  fs.writeFileSync(p, text);
  done.push(label || path.relative(root, p));
}
const xmlEscape = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// ------------------------------------------------------------------ www
write(
  path.join(root, "www", "app-settings.js"),
  `// Written by scripts/configure-native.mjs from app.settings.json. Do not edit by hand.\n` +
    `window.DM_SETTINGS = ${JSON.stringify({ siteUrl, appName: settings.appName, brand: settings.colors.brand }, null, 2)};\n`
);

// -------------------------------------------------------------- Android
const androidMain = path.join(root, "android", "app", "src", "main");
const manifestPath = path.join(androidMain, "AndroidManifest.xml");
if (fs.existsSync(manifestPath)) {
  let xml = read(manifestPath);

  const permissions = [
    "android.permission.INTERNET",
    "android.permission.ACCESS_NETWORK_STATE",
    "android.permission.RECORD_AUDIO",
    "android.permission.MODIFY_AUDIO_SETTINGS",
    "android.permission.CAMERA",
  ];
  for (const name of permissions) {
    if (!xml.includes(`android:name="${name}"`)) {
      xml = xml.replace(/\n(\s*)<\/manifest>\s*$/, `\n    <uses-permission android:name="${name}" />\n$1</manifest>\n`);
    }
  }
  // Plain http:// to your computer while testing (devUrl); never in store builds.
  xml = xml.replace(/\s+android:usesCleartextTraffic="true"/, "");
  if (devUrl.startsWith("http://")) {
    xml = xml.replace(/<application\b/, '<application\n        android:usesCleartextTraffic="true"');
  }

  // The camera is optional: phones without one can still install the app.
  if (!xml.includes('android:name="android.hardware.camera"')) {
    xml = xml.replace(/\n(\s*)<\/manifest>\s*$/, `\n    <uses-feature android:name="android.hardware.camera" android:required="false" />\n$1</manifest>\n`);
  }

  // Deep links: https://www.dictionmasters.app/... opens in the app.
  const start = "<!-- dm:deeplinks:start -->";
  const end = "<!-- dm:deeplinks:end -->";
  xml = xml.replace(new RegExp(`\\s*${start}[\\s\\S]*?${end}`), "");
  if (settings.deepLinks && settings.deepLinks.android) {
    const data = settings.appHosts.map((h) => `                <data android:scheme="https" android:host="${xmlEscape(h)}" />`).join("\n");
    const block =
      `\n            ${start}\n` +
      `            <intent-filter android:autoVerify="true">\n` +
      `                <action android:name="android.intent.action.VIEW" />\n` +
      `                <category android:name="android.intent.category.DEFAULT" />\n` +
      `                <category android:name="android.intent.category.BROWSABLE" />\n` +
      `${data}\n` +
      `            </intent-filter>\n` +
      `            ${end}`;
    // Inside the main activity, just before it closes.
    xml = xml.replace(/(<activity[\s\S]*?\.MainActivity"[\s\S]*?)(\n\s*<\/activity>)/, `$1${block}$2`);
  }
  write(manifestPath, xml);

  const stringsPath = path.join(androidMain, "res", "values", "strings.xml");
  if (fs.existsSync(stringsPath)) {
    let s = read(stringsPath);
    for (const key of ["app_name", "title_activity_main"]) {
      s = s.replace(new RegExp(`(<string name="${key}">)[^<]*(</string>)`), `$1${xmlEscape(settings.appName)}$2`);
    }
    write(stringsPath, s);
  }

  // Version shown in Google Play, and signing for release builds.
  const gradlePath = path.join(root, "android", "app", "build.gradle");
  if (fs.existsSync(gradlePath)) {
    let g = read(gradlePath);
    g = g.replace(/versionCode\s+\d+/, `versionCode ${Number(settings.build) || 1}`);
    g = g.replace(/versionName\s+"[^"]*"/, `versionName "${settings.version}"`);
    if (!g.includes("dm:signing:start")) {
      g += `
// dm:signing:start — added by scripts/configure-native.mjs
// Release builds are signed with your upload key when these are set
// (see MOBILE_APP_GUIDE.md, section 5). Android Studio's
// "Generate Signed Bundle" works too, without them.
android {
    signingConfigs {
        dmRelease {
            if (System.getenv("DM_KEYSTORE_FILE")) {
                storeFile file(System.getenv("DM_KEYSTORE_FILE"))
                storePassword System.getenv("DM_KEYSTORE_PASSWORD")
                keyAlias System.getenv("DM_KEY_ALIAS")
                keyPassword System.getenv("DM_KEY_PASSWORD")
            }
        }
    }
    buildTypes {
        release {
            if (System.getenv("DM_KEYSTORE_FILE")) {
                signingConfig signingConfigs.dmRelease
            }
        }
    }
}
// dm:signing:end
`;
    }
    write(gradlePath, g);
  }
} else {
  console.log("• No android/ folder yet — run `npm run setup:android` first (skipped Android).");
}

// ------------------------------------------------------------------ iOS
const iosApp = path.join(root, "ios", "App", "App");
const plistPath = path.join(iosApp, "Info.plist");

function plistValue(value) {
  if (value === true) return "<true/>";
  if (value === false) return "<false/>";
  if (Array.isArray(value)) {
    return "<array>\n" + value.map((v) => `\t\t<string>${xmlEscape(v)}</string>`).join("\n") + "\n\t</array>";
  }
  return `<string>${xmlEscape(value)}</string>`;
}
const VALUE = "(?:<string>[\\s\\S]*?</string>|<true/>|<false/>|<array>[\\s\\S]*?</array>|<array/>|<integer>[^<]*</integer>)";
function plistSet(xml, key, value) {
  const re = new RegExp(`(\\n?\\s*)<key>${key}</key>\\s*${VALUE}`);
  if (value === undefined) return xml.replace(re, "");
  const entry = `<key>${key}</key>\n\t${plistValue(value)}`;
  if (re.test(xml)) return xml.replace(re, (m, ws) => `${ws}${entry}`);
  // Add at the end of the top-level dictionary.
  return xml.replace(/\n<\/dict>\s*<\/plist>\s*$/, `\n\t${entry}\n</dict>\n</plist>\n`);
}

if (fs.existsSync(plistPath)) {
  let xml = read(plistPath);
  xml = plistSet(xml, "CFBundleDisplayName", settings.appName);
  xml = plistSet(xml, "NSMicrophoneUsageDescription", settings.permissionText.microphone);
  xml = plistSet(xml, "NSCameraUsageDescription", settings.permissionText.camera);
  xml = plistSet(xml, "NSPhotoLibraryAddUsageDescription", settings.permissionText.photos);
  // No custom encryption: skips the export-compliance question on every upload.
  xml = plistSet(xml, "ITSAppUsesNonExemptEncryption", false);
  xml = plistSet(xml, "UIBackgroundModes", settings.backgroundAudio ? ["audio"] : undefined);
  // App-bound domains: required for the service worker (offline lessons) on iPhone.
  xml = plistSet(xml, "WKAppBoundDomains", settings.iosAppBoundDomains ? [...settings.appHosts, "localhost"].slice(0, 10) : undefined);
  write(plistPath, xml);

  const entPath = path.join(iosApp, "App.entitlements");
  const pbxPath = path.join(root, "ios", "App", "App.xcodeproj", "project.pbxproj");

  // Version shown in the App Store.
  if (fs.existsSync(pbxPath)) {
    let pbx = read(pbxPath);
    pbx = pbx.replace(/MARKETING_VERSION = [^;]+;/g, `MARKETING_VERSION = ${settings.version};`);
    pbx = pbx.replace(/CURRENT_PROJECT_VERSION = [^;]+;/g, `CURRENT_PROJECT_VERSION = ${Number(settings.build) || 1};`);
    write(pbxPath, pbx);
  }

  // Deep links (Associated Domains).
  if (settings.deepLinks && settings.deepLinks.ios) {
    const domains = settings.appHosts.map((h) => `\t\t<string>applinks:${xmlEscape(h)}</string>`).join("\n");
    write(
      entPath,
      `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n` +
        `<plist version="1.0">\n<dict>\n\t<key>com.apple.developer.associated-domains</key>\n\t<array>\n${domains}\n\t</array>\n</dict>\n</plist>\n`
    );
    if (fs.existsSync(pbxPath)) {
      let pbx = read(pbxPath);
      if (!pbx.includes("CODE_SIGN_ENTITLEMENTS")) {
        pbx = pbx.replace(/^([ \t]*)(INFOPLIST_FILE = App\/Info\.plist;)/gm, `$1CODE_SIGN_ENTITLEMENTS = App/App.entitlements;\n$1$2`);
        write(pbxPath, pbx);
      }
    }
  } else if (fs.existsSync(pbxPath)) {
    let pbx = read(pbxPath);
    pbx = pbx.replace(/^[ \t]*CODE_SIGN_ENTITLEMENTS = App\/App\.entitlements;\r?\n/gm, "");
    write(pbxPath, pbx);
  }
} else {
  console.log("• No ios/ folder yet — run `npm run setup:ios` on a Mac first (skipped iPhone).");
}

console.log(done.length ? `✔ Updated: ${done.join(", ")}` : "✔ Native projects already match app.settings.json");
console.log(`  Site: ${siteUrl}  (${siteHost})`);
