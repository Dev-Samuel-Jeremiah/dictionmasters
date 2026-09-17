Redesign the page(s) listed at the bottom so they match the design already used by the learner dashboard and EchoSpell in this Django project (Diction Masters, at /home/techmiary/my_django_project/diction/dictionmasters). Match that design exactly; don't invent a new style.

## Study these first (they are the reference)
- static/css/ui.css (THE SHARED DESIGN SYSTEM, loaded on every page by base.html: `ui-hero`, `ui-crumbs`, `ui-panel`, `ui-card`, `ui-row`, `ui-step`, `ui-tile`, `ui-ring`, `ui-btn`, `ui-status`, `ui-empty`, `ui-callout`, `ui-table` and more). Build new pages from these classes first.
- templates/learning_tools/hub.html, reading_club/*.html, reference_library/*.html (pages built purely from ui.css)
- templates/echospell/hub.html, level_detail.html, group_detail.html, activity_detail.html, activity_result.html
- static/css/echospell_ui.css (the page design system: hero, panels, cards, rings, buttons)
- templates/accounts/dashboard.html + static/css/dashboard.css (3D effects, count-up numbers)
- static/css/base.css (colour and font tokens: --ink, --gold, --maroon, --green, --parchment, --font-serif Fraunces, --font-sans Work Sans)

## The design, precisely
1. Page wrapper: `<div class="xx">` (xx = a short prefix for the app, like `es` for EchoSpell), warm ground #f4efe2, padding-bottom 88px.
2. Hero banner: dark gradient (EchoSpell uses green `#0f2a22 → #1d4d3e → #14213D`; pick one accent colour per app, dashboard uses navy, Clash uses navy/gold), a faint 40px grid pattern, a gold radial glow top-right, and soft animated rings bottom-right (::after).
   Contents, in order: pill breadcrumbs (`My dashboard › App › Page`), then a row with a 76px tilted 3D icon tile (perspective rotateX 8deg rotateY -10deg, glass gradient), a small gold uppercase eyebrow (letter-spacing 0.2em), a large Fraunces title (clamp 1.9–3rem, white), a lede, and glass chips (`es-chip`, `--gold`, `--done`). A progress ring sits on the right when there's progress to show (132px conic-gradient, gold, animated with @property).
3. Body: `wrap` container pulled up over the hero (margin-top -58px) so the first white panel overlaps it.
4. Panels and cards: #fffdf8, radius 18–22px, layered soft shadow (--es-shadow), no borders. Clickable cards get the 3D lift: `perspective(900px) rotateX(3deg) translateY(-6px)` plus a bigger shadow on hover. Inner icons use translateZ to pop forward. Cards rise in with a staggered `translate` animation (use `translate`, never `transform`, in entrance keyframes so it doesn't fight the tilt), delayed by `--i`.
5. Sections: a heading row with a Fraunces title (optionally a numbered green square badge, e.g. "1 Learn", "2 Practise") and a grey aside on the right.
6. Status: pills (`Now`/`Continue here` gold, `Done`/`Complete` green, neutral grey), progress bars (8px, gradient fill, scaleX grow animation), small light progress rings.
7. Buttons: `--gold` (gradient #f0c878→#c98f3a, navy text) for the main action, `--green` for submit/complete, `--ghost` outline, `--glass` on the dark hero. Radius 12px, lift 2px on hover, visible focus outline.
8. Empty states: dashed rounded box with 🌱 and one plain sentence.
9. Forms and long pages: a sticky frosted submit bar at the bottom (`es-submitbar`); use the static version on result pages.
10. Results: a big score ring (green for a pass, red if not), a Fraunces headline, stat pills, then a review list of cards with coloured left borders and round ✓/✗ markers.
11. Responsive: at 820px the hero stacks; at 560px the hero ring is hidden, grids drop to 1–2 columns, and the submit bar gets compact. No horizontal scroll at 400px. Grid columns use `minmax(0, 1fr)`.
12. Motion: everything decorative is disabled under `prefers-reduced-motion`.

## Rules
- Use the shared `ui-` classes from static/css/ui.css. Only add CSS for things it doesn't cover, in the "App extras" section of ui.css (or a small `<app>_ui.css` for a large app). Pick a hero colour with `ui-hero--green/blue/gold/maroon/plum/teal` (navy is the default).
- Keep every existing class name, id, data-attribute, form field name and URL that JavaScript or views rely on. Change the page frame, not the behaviour. Read the page's JS before touching markup.
- Only add view context when a template genuinely needs it (for example "next item to continue", overall progress). Don't change models.
- Show real data only; nothing fake or placeholder.
- Plain British English in the UI; no em dashes in new copy.
- Don't delete or alter user-created data.

## Verify before reporting
1. `python manage.py check` (the venv is at /home/techmiary/my_django_project/venv).
2. Create a temporary user, start `runserver 127.0.0.1:8765 --noreload`, and use Playwright to log in at /accounts/login/ (field `username`, button `.form-card button[type=submit]`). Block non-127.0.0.1 requests so fonts don't hang screenshots. Visit every redesigned page, click through each interaction, screenshot at 1280px and 400px, and check `scrollWidth` equals the viewport width and there are no page errors. Look at the screenshots and fix anything off.
3. Delete the temporary user and anything it created, and stop the test server.
4. Report briefly: what changed page by page, anything fixed along the way, and anything left for me to decide.

## Pages to redesign now
<LIST THE TEMPLATES HERE, e.g. templates/quick_words/*.html>
