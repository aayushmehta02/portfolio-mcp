# Vercel Pages — Integration Guide

Two pages need to be added to your Vercel app (`web-portfolio-amber-one.vercel.app`):

## 1. Root / Callback page  →  served at `/`

This page is where Upstox redirects after login. It reads the `state` parameter
(which contains the local MCP server address) and silently forwards the auth code there.

**File:** `callback-page.html`

### Next.js (App Router)
Create `app/page.tsx` with the JS logic from `callback-page.html`.

### Next.js (Pages Router)
Create `pages/index.tsx` with the JS logic.

### Plain HTML (static Vercel site)
Upload `callback-page.html` as `index.html` at the root.

---

## 2. Connected page  →  served at `/connected`

A success screen users see after authenticating. They can close this tab.

**File:** `connected-page.html`

### Next.js (App Router)
Create `app/connected/page.tsx`.

### Next.js (Pages Router)
Create `pages/connected.tsx`.

### Plain HTML
Upload `connected-page.html` as `connected/index.html`.

---

## How it all works

```
User asks Claude → connect_upstox tool fires
  → local server starts on port 8888
  → browser opens to Upstox login
  → user logs in normally
  → Upstox redirects to https://web-portfolio-amber-one.vercel.app/?code=XXX&state=http://localhost:8888/callback
  → Vercel root page reads state, does window.location.replace(state + "?code=" + code)
  → browser hits http://localhost:8888/callback?code=XXX
  → local server captures code, exchanges for token, saves to .env
  → browser redirected to /connected ("You're connected!")
  → Claude confirms success
```

No terminal. No copy-paste. Just login.
