/*
 * Quick health check before you build or publish:   npm run check
 *
 *  - app.settings.json is filled in correctly
 *  - the website is reachable
 *  - the Django side of the app is deployed (the /.well-known/ files for deep links)
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const s = JSON.parse(fs.readFileSync(path.join(root, "app.settings.json"), "utf8"));
let problems = 0;
const ok = (m) => console.log("  ✔ " + m);
const bad = (m) => { problems++; console.log("  ✘ " + m); };
const warn = (m) => console.log("  ! " + m);

console.log("\nSettings");
/^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/.test(s.appId) ? ok(`appId ${s.appId}`) : bad(`appId "${s.appId}" must look like com.company.app (lowercase, dots)`);
s.appName ? ok(`appName ${s.appName}`) : bad("appName is empty");
/^https:\/\//.test(s.siteUrl) ? ok(`siteUrl ${s.siteUrl}`) : bad("siteUrl must start with https://");
const host = new URL(s.siteUrl).host;
s.appHosts.includes(host) ? ok("siteUrl host is in appHosts") : bad(`add "${host}" to appHosts`);

console.log("\nWebsite");
async function get(url) {
  try {
    const r = await fetch(url, { redirect: "follow" });
    return { status: r.status, text: await r.text() };
  } catch (e) {
    return { status: 0, text: String(e) };
  }
}
const home = await get(s.siteUrl + "/");
home.status === 200 ? ok("site is up") : bad(`site answered ${home.status || "nothing"} — is it deployed?`);

const links = await get(s.siteUrl + "/.well-known/assetlinks.json");
if (links.status === 200 && links.text.includes("sha256_cert_fingerprints")) {
  links.text.includes(s.appId) ? ok("Android deep-link file is live") : warn("assetlinks.json is live but lists a different app id — check NATIVE_APP_ANDROID_PACKAGE");
} else {
  warn("Android deep-link file not set up yet (guide, section 7) — the app still works without it");
}
const aasa = await get(s.siteUrl + "/.well-known/apple-app-site-association");
aasa.status === 200 && aasa.text.includes("applinks") ? ok("iPhone deep-link file is live") : warn("iPhone deep-link file not set up yet (guide, section 7)");

for (const dir of ["android", "ios"]) {
  fs.existsSync(path.join(root, dir)) ? ok(`${dir}/ project exists`) : warn(`${dir}/ not created yet — npm run setup:${dir}`);
}

console.log(problems ? `\n${problems} problem(s) to fix.\n` : "\nAll good.\n");
process.exit(problems ? 1 : 0);
