# Hardware integration contract

This backend never talks to a physical board directly - it talks to a
per-lab HTTP service (`Lab.backend_url` in `backend/labs.yaml`) that
implements a small slice of the [WebLab-Deusto](https://weblabdeusto.readthedocs.io/)
protocol. `app/services/weblab.py` and `app/routers/hardware_proxy.py`
are the only two files that know this contract; nothing else in this
repo depends on WebLab-Deusto, [labdiscoverylib](https://developers.labsland.com/labdiscoverylib/),
or any particular hardware vendor.

If your boards can answer these four requests, they work with this
portal - you do not need to use labdiscoverylib, and you do not need any
code from [fpga-remote-lab-hardware](https://github.com/canyagiz/fpga-remote-lab-hardware)
(H-BRS's own implementation of this contract, kept as a separate repo
purely as a working reference - see its README for what it looks like in
practice, built on labdiscoverylib).

## Authentication

Every request below uses HTTP Basic auth with this backend's
`WEBLAB_USERNAME`/`WEBLAB_PASSWORD` settings (see `.env.example`) - your
hardware service must accept the same credentials. There is no
per-request token; the whole relationship between this portal and a
hardware backend is one shared, long-lived username/password pair.

## 1. Start a session

`POST {backend_url}/foo/ldl/sessions/`

Called once per reservation, the first time a user clicks *Access*
(`app/routers/labs.py`, `start_weblab_session`). Request body:

```json
{
  "request": {
    "locale": "en",
    "ldeReservationId": "fpga-remote-lab-<user_id>-<lab_id>-<unix_ts>",
    "user": {},
    "server": {},
    "backUrl": "https://.../labs"
  },
  "laboratory": { "name": "<lab.name>" },
  "user": {
    "username": "<user.username>",
    "unique": "user-<user.id>",
    "fullName": "<user.username>"
  },
  "schedule": { "start": "<ISO 8601 UTC>", "length": <seconds> }
}
```

Expected response: `200` with `{"url": "<path or absolute URL to the lab's own UI>"}`.
Anything else (missing `url`, non-2xx) is treated as a hard failure - the
user sees "Could not start a session on the lab hardware" and no
reservation is marked started.

The returned `url` is not sent to the browser as-is: this backend
rewrites its path onto `/hw/{lab_id}/...` and hands *that* to the
browser, because nginx (in production) or this app (`hardware_proxy.py`,
in the one carved-out case below) is what actually reaches your hardware
service - the browser never talks to `backend_url` directly. See
"Reverse proxy expectations" below for what this means for your service's
own generated links.

The session URL is cached on the reservation (`weblab_session_url`) -
this endpoint is called at most once per reservation, not once per
*Access* click.

## 2. Session status

`GET {backend_url}/foo/ldl/sessions/{session_id}/status`

Polled periodically (`services/queue.py::sweep_logged_out_sessions`) for
every reservation with an open session, since there is no push
notification path back to this backend. `session_id` is whatever
trailing path segment your `url` response above ended in.

Expected response: `200` with a JSON body containing `should_finish`.
`should_finish == -1` means the session is over (idle timeout, in-lab
logout, or ran out of allotted time) - this backend then closes the
matching reservation. Any other value means the session is still active.

## 3. Force-close a session

`DELETE {backend_url}/foo/ldl/sessions/{session_id}`

Called whenever *this backend* ends a reservation from its own side -
Finish, Cancel, or the expiry sweep - so a stale session can't keep
running physically live on your hardware after our database considers
the board free. Expected response: any 2xx; the body isn't inspected.

## 4. In-lab logout carve-out

`POST {backend_url}/logout`

Not prefixed under `/foo/ldl/` - this is your lab UI's own "Log out"
button, called directly by the browser through this backend's
`/hw/{lab_id}/logout` route (the *one* hardware path this app proxies
itself instead of leaving to nginx - see `hardware_proxy.py`), so the
matching reservation can close in the same request instead of waiting
for the next status poll.

Expected response: `200` with `{"error": false}` on a real logout. Any
other shape (or a 4xx, e.g. no session was active) is treated as "nothing
to close here" and this backend does not touch the reservation - the
periodic status poll (endpoint 2) is the fallback for that case, and for
a closed tab or dropped connection that never sends this request at all.

## Reverse proxy expectations

Because the browser reaches your service through `/hw/{lab_id}/...`, not
your bare `host:port`, your service's own `url_for()`/redirect/AJAX URLs
must come out already prefixed with `/hw/{lab_id}` - otherwise they
resolve against the wrong origin and 404. In practice this means running
your WSGI app behind something like Werkzeug's `ProxyFix` with
`x_prefix=1`, and trusting the `X-Forwarded-Prefix`/`X-Forwarded-Host`/
`X-Forwarded-Proto` headers this backend (and nginx, in production) sets
on every proxied request. See `fpga-remote-lab-hardware`'s
`wsgi_app_patched.py.example` for a concrete example of this.
