# FPGA Remote Lab

New portal intended to eventually replace CT200 (LabDiscoveryEngine) for the
H-BRS FPGA Remote Lab infrastructure. Built from scratch on a new LXC
container (CT210), independently of the existing CT200 deployment.

## Status

Authentication, reservations/calendar, the profile system, and real
hardware access to the CT300 boards (Cyclone X/IV/V, Arty Z7) are all
live end to end (backend + frontend). See
[`backend/README.md`](backend/README.md) and
[`frontend/README.md`](frontend/README.md) for details and setup; what's
deliberately not implemented yet is listed at the bottom of each.

## Layout

```
backend/   FastAPI application (auth, labs, reservations, profile, hardware access) - see backend/README.md
frontend/  React + TypeScript + Vite SPA - see frontend/README.md
deploy/    nginx + systemd configs used on CT210 - see deploy/README.md
```

The backend serves the built frontend directly (same origin, no separate
frontend server in production) - see "Serving the frontend" in
`backend/README.md`.
