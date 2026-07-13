#!/usr/bin/env python3
"""Render nginx-fgpa-remote-lab.conf.j2 using backend/labs.yaml.

backend/labs.yaml is the single source of truth for which labs exist and
where their hardware lives; this script is the other half of that - it
turns the same file into nginx's lab_id -> host:port map, so the two
can never drift out of sync the way hand-editing both used to allow.

Usage (from anywhere):
    python3 deploy/generate_nginx_config.py

Then, on the server:
    pct push 210 deploy/nginx-fgpa-remote-lab.conf /etc/nginx/sites-available/fgpa-remote-lab
    pct exec 210 -- nginx -t && pct exec 210 -- systemctl reload nginx
"""

import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml
from jinja2 import Environment, FileSystemLoader

_DEPLOY_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _DEPLOY_DIR.parent
_LABS_YAML = _REPO_ROOT / "backend" / "labs.yaml"
_TEMPLATE_NAME = "nginx-fgpa-remote-lab.conf.j2"
_OUTPUT_PATH = _DEPLOY_DIR / "nginx-fgpa-remote-lab.conf"


def _host_port(backend_url: str, lab_name: str) -> str:
    parsed = urlparse(backend_url)
    if not parsed.hostname or not parsed.port:
        raise ValueError(
            f"Lab {lab_name!r}: backend_url {backend_url!r} must include both a host and a port "
            "(e.g. http://10.30.70.23:5000)"
        )
    return f"{parsed.hostname}:{parsed.port}"


def main() -> None:
    if not _LABS_YAML.is_file():
        print(f"error: {_LABS_YAML} not found - copy labs.yaml.example to labs.yaml first", file=sys.stderr)
        sys.exit(1)

    with open(_LABS_YAML) as f:
        config = yaml.safe_load(f)

    labfiles_host = config.get("labfiles_host")
    if not labfiles_host:
        print("error: labs.yaml is missing labfiles_host", file=sys.stderr)
        sys.exit(1)

    labs = []
    for entry in config["labs"]:
        if not entry.get("backend_url"):
            # A lab with no hardware wired up yet has nothing for nginx to
            # route to - it just won't get an entry in the map, and
            # /hw/{id}/* will 404 for it (same as any unknown lab_id).
            continue
        labs.append(
            {
                "id": entry["id"],
                "name": entry["name"],
                "upstream": _host_port(entry["backend_url"], entry["name"]),
            }
        )

    env = Environment(
        loader=FileSystemLoader(str(_DEPLOY_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template(_TEMPLATE_NAME)
    rendered = template.render(labs=labs, labfiles_host=labfiles_host)

    _OUTPUT_PATH.write_text(rendered)
    print(f"Wrote {_OUTPUT_PATH} ({len(labs)} lab(s) mapped)")


if __name__ == "__main__":
    main()
