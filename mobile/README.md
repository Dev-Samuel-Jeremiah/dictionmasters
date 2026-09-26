# Diction Masters — mobile apps (Android & iPhone)

Native Capacitor apps that open the live Diction Masters website and add
phone features on top. Changes you deploy to the website appear in the
apps automatically.

**Full step-by-step guide: [../MOBILE_APP_GUIDE.md](../MOBILE_APP_GUIDE.md)**

```bash
npm install
npm run setup:android     # once: creates android/
npm run setup:ios         # once, on a Mac: creates ios/
npm run open:android      # open in Android Studio, press ▶
npm run open:ios          # open in Xcode, press ▶

npm run sync              # after ANY change in this folder
npm run release           # before building for the stores
npm run check             # is everything set up?
```

Settings live in **`app.settings.json`**. That's the only file you normally edit.
