# FPGA Remote Lab

New portal intended to eventually replace CT200 (LabDiscoveryEngine) for the
H-BRS FPGA Remote Lab infrastructure. Built from scratch on a new LXC
container (CT210), independently of the existing CT200 deployment.

## Status

Scoped to authentication and reservation/queue logic, end to end (backend +
frontend). See [`backend/README.md`](backend/README.md) and
[`frontend/README.md`](frontend/README.md) for details, setup, and what is
deliberately not implemented yet (hardware access proxy, multi-lab catalog,
Arty Z7 integration, German translation).

## Layout

```
backend/   FastAPI application (auth, labs, reservations, users) - see backend/README.md
frontend/  React + TypeScript + Vite SPA - see frontend/README.md
```

The backend serves the built frontend directly (same origin, no separate
frontend server in production) - see "Serving the frontend" in
`backend/README.md`.
