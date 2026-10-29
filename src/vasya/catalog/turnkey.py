# SPDX-License-Identifier: GPL-3.0-or-later
"""TurnKey Linux (turnkeylinux/wordpress) first-boot preseed — OPT-IN, UNVERIFIED.

On first start TurnKey's inithooks open an interactive dialog (root/DB/admin passwords, email, domain,
Hub, security updates) on the console; until it is answered WordPress answers HTTP 500 (tested: PARTIAL).
TurnKey reads non-interactive answers from /etc/inithooks.conf. With VASYA_TURNKEY_PRESEED=1 the VASYA
template (not the image) carries the answers as container environment and a start_command wrapper that
writes them to /etc/inithooks.conf in the container's own writable layer, then execs the image's
/usr/sbin/start.sh (PID 1 in the tested container). The image is never modified. Default: off (stock template).

UNVERIFIED until retested on a real install: it assumes start.sh is the image Cmd (not its Entrypoint)."""
import os
import secrets
import string

PRESEED_ENV = "VASYA_TURNKEY_PRESEED"
BLOCKS = {"turnkey-wordpress"}
VARS = ("ROOT_PASS", "DB_PASS", "APP_PASS", "APP_EMAIL", "APP_DOMAIN", "HUB_APIKEY", "SEC_UPDATES")
CONF = "/etc/inithooks.conf"
START = "/usr/sbin/start.sh"
# single-quoted for GNS3's shlex.split -> Cmd ["/bin/sh", "-c", <script>]; values are [A-Za-z0-9@.] only
SCRIPT = ('f=' + CONF + '; if [ ! -s "$f" ]; then for v in ' + " ".join(VARS) + '; do '
          'eval "x=\\${$v:-}"; [ -n "$x" ] && printf "export %s=\\"%s\\"\\n" "$v" "$x" >> "$f"; done; '
          'chmod 600 "$f"; fi; exec ' + START)
START_COMMAND = "/bin/sh -c '" + SCRIPT + "'"


def enabled(env=None):
    return (env if env is not None else os.environ).get(PRESEED_ENV, "").strip().lower() in ("1", "yes", "true", "on")


def password(n=16):
    """Random alnum password with upper, lower and digit (TurnKey rejects weak ones in the dialog)."""
    a = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(a) for _ in range(n))
        if any(c.islower() for c in p) and any(c.isupper() for c in p) and any(c.isdigit() for c in p):
            return p


def answers():
    return {"ROOT_PASS": password(), "DB_PASS": password(), "APP_PASS": password(),
            "APP_EMAIL": "admin@example.com", "APP_DOMAIN": "DEFAULT", "HUB_APIKEY": "SKIP", "SEC_UPDATES": "SKIP"}


def apply_preseed(block, t, env=None, values=None):
    """Mutates docker template `t` for TurnKey blocks when opted in. Returns the answers or None."""
    if block.get("block_id") not in BLOCKS or not enabled(env):
        return None
    vals = values or answers()
    keep = [ln for ln in (t.get("environment") or "").splitlines()
            if ln.strip() and ln.split("=", 1)[0].strip() not in VARS]
    t["environment"] = "\n".join(keep + [f"{k}={vals[k]}" for k in VARS])
    t["start_command"] = START_COMMAND
    note = ("VASYA TurnKey preseed (UNVERIFIED, opt-in): first boot is non-interactive. "
            f"root password {vals['ROOT_PASS']}; WordPress 'admin' password {vals['APP_PASS']} "
            f"({vals['APP_EMAIL']}); MySQL root password {vals['DB_PASS']}. "
            "They are also in this template's environment.")
    t["usage"] = f"{t['usage']}\n\n{note}" if t.get("usage") else note
    return vals
