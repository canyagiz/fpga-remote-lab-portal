# FPGA Remote Lab

New portal intended to eventually replace CT200 (LabDiscoveryEngine) for the
H-BRS FPGA Remote Lab infrastructure. Built from scratch on a new LXC
container (CT210), independently of the existing CT200 deployment.

## Status

Backend only, scoped to authentication and reservation/queue logic. See
[`backend/README.md`](backend/README.md) for details, setup, and what is
deliberately not implemented yet (hardware access proxy, multi-lab catalog,
Arty Z7 integration, German translation).

## Layout

```
backend/   FastAPI application (auth, labs, reservations)
```

A frontend has not been started yet.
