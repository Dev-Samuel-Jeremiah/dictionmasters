# Diction Masters for Windows, Mac and Linux

The computer app: the live Diction Masters website in its own window, with
offline lessons, microphone practice, and updates that install themselves.

**Everything is explained in [`../DESKTOP_APP_GUIDE.md`](../DESKTOP_APP_GUIDE.md).**

Quick start (Node.js 22):

```bash
npm install
npm start        # the live site
npm run dev      # your local Django at http://127.0.0.1:8000
```

Installers are built and published by GitHub: Actions → **Desktop app**.
The one file to edit is `app.settings.json`.
