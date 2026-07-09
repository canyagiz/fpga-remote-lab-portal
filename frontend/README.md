# FPGA Remote Lab - Frontend

React + TypeScript + Vite, styled with **Tailwind CSS v4 + shadcn/ui**.
Covers the same scope as the backend right now: a public landing page,
login/register with email 2FA, the reservation/queue dashboard, the lab
list, and an admin users page. No hardware-session UI yet (see the backend
README's "deliberately deferred" list).

shadcn/ui components live in `src/components/ui/` and are plain source
files you own (not an npm dependency) - the usual `npx shadcn@latest add
<component>` CLI needs an interactive terminal, which isn't available on
CT210, so new components are currently added by hand, copying the
upstream source from https://ui.shadcn.com/docs/components and adjusting
imports to this project's `cn()` helper (`src/lib/utils.ts`) and color
tokens (`src/styles.css`).

## Setup

```bash
npm install
npm run dev
```

This starts Vite's dev server (default `http://localhost:5173`) and proxies
`/api/*` to the backend at `http://localhost:8000` (see `vite.config.ts`),
so make sure the backend is running first. The proxy keeps everything on
one apparent origin in the browser, matching how cookies work in
production - the backend has no CORS middleware on purpose.

## Building for production

```bash
npm run build
```

Outputs to `dist/`. The backend (`../backend/app/main.py`) serves this
directory directly and falls back to `index.html` for client-side routes,
so there's no separate frontend server or build step needed on CT210 -
just rebuild and restart the backend service.

## Structure

```
src/
  api/            typed fetch client + response types, mirrors backend/app/schemas.py
  context/        AuthContext - current user, login/2FA/logout
  components/ui/  shadcn/ui primitives (button, input, card, badge, table, label)
  components/     Navbar, PasswordInput, PasswordStrength, ProtectedRoute (UI only, not a security boundary)
  pages/          one file per route
  lib/utils.ts    cn() class-merging helper shadcn components expect
```

Route-level auth is enforced by `ProtectedRoute`, but that's purely for
UX (hiding pages, redirecting). The actual authorization boundary is the
backend - every API call is checked server-side regardless of what the
frontend shows or hides.
