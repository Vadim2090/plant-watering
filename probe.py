"""Probe the environment sources before the bot ever runs (SPEC.md §13.3-4 prep).

    python probe.py            # Xiaomi cloud (if credentials are in .env) and the weather fallback
    python probe.py --weather  # weather only
    python probe.py --login    # one interactive Xiaomi login (answers the captcha) that stores a
                               # passToken in .env, so the bot never logs in with the password again

For the Xiaomi path it logs in, looks for the purifier in the configured region and then in
every other region (a wrong region returns an empty list, not an error), reads temperature and
humidity live and prints them. Nothing sensitive is printed: usernames, tokens and device ids
are masked.
"""

from __future__ import annotations

import argparse
import sys

from config import XIAOMI_REGIONS, ConfigError, load_config
from env_source import (
    WeatherSource,
    XiaomiCloudSource,
    is_valid_reading,
    list_xiaomi_devices,
    pick_purifier,
)


def mask(s: str | None) -> str:
    s = str(s or "")
    return f"{s[:2]}...{s[-2:]} ({len(s)} chars)" if len(s) > 4 else "<short>"


def probe_weather(lat: float, lon: float) -> bool:
    print(f"\nWeather (Open-Meteo) at {lat:.2f}, {lon:.2f}:")
    r = WeatherSource(lat, lon).read()
    if r is None:
        print("  FAILED - no reading (network? API down?)")
        return False
    print(f"  indoor estimate {r.temp_c} C, {r.rh}% RH  (crude: outdoor mean -> indoor rule, §5.2)")
    return True


def probe_xiaomi(username: str | None, password: str | None, region: str, device_id: str | None,
                 user_id: str | None = None, pass_token: str | None = None) -> bool:
    how = "passToken" + (" + password fallback" if password else "") if pass_token else "password"
    print(f"\nXiaomi cloud, account {mask(username or user_id)}, login via {how}, configured region '{region}':")
    order = [region] + [r for r in XIAOMI_REGIONS if r != region]
    found_region, device = None, None
    for r in order:
        try:
            devices = list_xiaomi_devices(username, password, r, user_id, pass_token)
        except Exception as e:
            msg = str(e)
            print(f"  login/list failed on '{r}': {type(e).__name__}: {msg[:120]}")
            if "login failed" in msg or "Access denied" in msg or "AccessDenied" in type(e).__name__:
                print("  -> password login refused: wrong password, or Xiaomi demands a captcha (code 87001) "
                      "after a few attempts from a new client. Fix: one interactive login to obtain a "
                      "passToken, stored as XIAOMI_USER_ID / XIAOMI_PASS_TOKEN - see README.")
                return False
            continue
        names = ", ".join(f"{d['name'] or '?'} [{d['model']}{'' if d['online'] else ', offline'}]" for d in devices) or "none"
        print(f"  region '{r}': {len(devices)} device(s): {names}")
        if device_id:
            match = [d for d in devices if d["did"] == device_id]
            device = match[0] if match else None
        else:
            device = pick_purifier(devices)
        if device is not None:
            found_region = r
            break
    if device is None:
        print("  FAILED - no purifier on any region. Is the device paired to THIS Mi account?")
        return False
    print(f"  purifier: {device['name'] or '?'} model={device['model']} online={device['online']} did={mask(device['did'])}")
    if found_region != region:
        print(f"  NOTE: found in region '{found_region}', not '{region}' -> set XIAOMI_REGION={found_region} in .env")
    if not device["model"].startswith("zhimi.airp.vb4"):
        print(f"  NOTE: model is {device['model']}, the spec's property table is for zhimi.airp.vb4 - verify siid/piid")

    r = XiaomiCloudSource(username, password, found_region, device["did"], user_id, pass_token).read()
    if r is None:
        print("  FAILED - device found but no temperature/humidity came back (device off? properties differ?)")
        return False
    ok = is_valid_reading(r.temp_c, r.rh)
    print(f"  reading: {r.temp_c} C, {r.rh}% RH  -> {'valid' if ok else 'OUT OF RANGE, would be discarded'}")
    return ok


def write_env_keys(values: dict[str, str], path: str = ".env") -> None:
    """Replace `KEY=` lines in .env in place (the keys already exist from .env.example)."""
    import pathlib

    p = pathlib.Path(path)
    lines = p.read_text(encoding="utf-8").splitlines()
    done = set()
    for i, line in enumerate(lines):
        for key, value in values.items():
            if line.startswith(key + "="):
                lines[i] = f"{key}={value}"
                done.add(key)
    for key, value in values.items():
        if key not in done:
            lines.append(f"{key}={value}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _complete_2fa(session, notification_url: str) -> tuple[str, str] | None:
    """Walk Xiaomi's two-step verification interactively and return (userId, passToken).

    Flow (matches the community token extractors): open the authStart URL, list the enabled
    channels, send a code to the phone or email, read the code the user types, verify it, then
    follow the STS redirect so the session ends up holding the passToken and serviceToken cookies.
    The user runs this; the code they enter is their own.
    """
    import json
    import time
    from urllib.parse import parse_qs, urlparse

    try:
        context = parse_qs(urlparse(notification_url).query)["context"][0]
    except (KeyError, IndexError):
        print("  2FA: could not read the context from the notification URL")
        return None
    session.get(notification_url)  # sets the identity_session / ick cookies

    lst = session.get("https://account.xiaomi.com/identity/list",
                      params={"sid": "xiaomiio", "context": context, "_locale": "en_US"})
    lj = json.loads(lst.text.replace("&&&START&&&", ""))
    options = lj.get("options") or (lj.get("data") or {}).get("options") or []
    print(f"  2FA options (raw): {options}")

    # `options` may be a list of flag ints ([4, 8]) or a list of dicts ([{'flag': 4, 'mask': ...}]).
    ordered: list[int] = []
    details: dict[int, dict] = {}
    for o in options:
        if isinstance(o, dict) and o.get("flag") is not None:
            f = int(o["flag"]); ordered.append(f); details[f] = o
        elif isinstance(o, int):
            ordered.append(o)
    if not ordered:
        print(f"  2FA: no verification options returned (code {lj.get('code')}): {lj.get('desc') or ''}")
        return None

    # 4 = SMS to the phone, 8 = email. Prefer email when both are offered (no SMS cost/roaming).
    flag = 8 if 8 in ordered else 4 if 4 in ordered else ordered[0]
    channel = "email" if flag == 8 else "phone"
    mask_index = ordered.index(flag)
    masked = (details.get(flag) or {}).get("mask") or (details.get(flag) or {}).get("maskedTarget") or "?"
    print(f"  2FA channel: {channel} ({masked})")

    ick = session.cookies.get("ick", "")
    base = "https://account.xiaomi.com/identity/auth"
    send_ep = f"{base}/sendEmailTicket" if flag == 8 else f"{base}/sendPhoneTicket"
    verify_ep = f"{base}/verifyEmail" if flag == 8 else f"{base}/verifyPhone"
    common = {"sid": "xiaomiio", "context": context, "mask": str(mask_index), "_locale": "en_US"}

    send = session.post(send_ep, params={"_dc": str(int(time.time() * 1000)), **common},
                        data={"retry": "0", "icode": "", "_json": "true", "ick": ick})
    sj = json.loads(send.text.replace("&&&START&&&", ""))
    if sj.get("code") not in (0, None):
        print(f"  2FA: sending the code failed (code {sj.get('code')}): {sj.get('desc') or ''}")
        return None
    print(f"  A verification code was sent to your {channel} ({masked}).")

    code = input("  enter the verification code: ").strip()
    verify = session.post(verify_ep, params={"_flag": str(flag), "_json": "true", **common},
                          data={"_flag": str(flag), "ticket": code, "trust": "true", "_json": "true", "ick": ick})
    vj = json.loads(verify.text.replace("&&&START&&&", ""))
    if vj.get("code") not in (0, None) or not vj.get("location"):
        print(f"  2FA: verification failed (code {vj.get('code')}): {vj.get('desc') or vj.get('description') or ''}")
        return None

    end = session.get(vj["location"], allow_redirects=False)
    sts = end.headers.get("Location")
    if sts:
        session.get(sts, allow_redirects=True)  # STS hop sets serviceToken

    # After the STS hops the same cookie name exists on several domains, so session.cookies.get()
    # raises CookieConflictError. Read straight from the jar, preferring the xiaomi.com domains.
    def jar_get(name: str) -> str | None:
        found = [c for c in session.cookies if c.name == name and c.value]
        for c in found:
            if "xiaomi" in (c.domain or ""):
                return c.value
        return found[0].value if found else None

    user_id = jar_get("userId")
    pass_token = jar_get("passToken")
    if not (user_id and pass_token):
        names = sorted({c.name for c in session.cookies})
        print(f"  2FA completed but no passToken cookie was set - login did not finalise. "
              f"cookies present: {names}")
        return None
    return str(user_id), pass_token


def interactive_login(username: str, password: str) -> bool:
    """Password login by hand, answering Xiaomi's captcha and 2FA if it asks; stores the resulting
    passToken in .env. Prints no secret."""
    import hashlib
    import json
    import pathlib
    import subprocess
    import tempfile

    from micloud import MiCloud

    cloud = MiCloud(username, password)
    cloud._init_session()
    sign = cloud._login_step1()
    post = {"sid": "xiaomiio", "hash": hashlib.md5(password.encode()).hexdigest().upper(),
            "callback": "https://sts.api.io.mi.com/sts", "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
            "user": username, "_json": "true"}
    if sign:
        post["_sign"] = sign
    j = {}
    for attempt in range(4):
        r = cloud.session.post("https://account.xiaomi.com/pass/serviceLoginAuth2", data=post)
        j = json.loads(r.text.replace("&&&START&&&", ""))
        # 2FA can arrive with result "ok" AND a notificationUrl, so check it before the ok-break
        if j.get("notificationUrl"):
            print("  Xiaomi asks for two-step verification.")
            result = _complete_2fa(cloud.session, j["notificationUrl"])
            if result is None:
                return False
            user_id, pass_token = result
            write_env_keys({"XIAOMI_USER_ID": user_id, "XIAOMI_PASS_TOKEN": pass_token})
            print(f"  logged in via 2FA. XIAOMI_USER_ID and XIAOMI_PASS_TOKEN ({len(pass_token)} chars) written to .env.")
            print("  Copy both lines to the server's .env; the bot will not need the password there.")
            return True
        if j.get("result") == "ok":
            break
        code = j.get("code")
        cap = j.get("captchaUrl")
        if not cap:
            print(f"  login refused, code {code}: {j.get('desc') or j.get('description') or ''}")
            return False
        if attempt == 3:
            print("  too many captcha attempts")
            return False
        url = cap if cap.startswith("http") else "https://account.xiaomi.com" + cap
        img = cloud.session.get(url).content
        png = pathlib.Path(tempfile.gettempdir()) / "xiaomi_captcha.png"
        png.write_bytes(img)
        print(f"  Xiaomi wants a captcha (code {code}). Image saved to {png}")
        subprocess.run(["open", str(png)], check=False)  # macOS; harmless elsewhere
        post["captCode"] = input("  type the characters you see: ").strip()

    if j.get("result") != "ok" or "userId" not in j:
        print(f"  login did not complete (code {j.get('code')}): {j.get('desc') or j.get('description') or ''}")
        return False
    cloud.user_id, cloud.ssecurity, cloud.cuser_id, cloud.pass_token = (
        str(j["userId"]), j["ssecurity"], j["cUserId"], j["passToken"])
    r3 = cloud._login_step3(j["location"])
    if r3.status_code != 200 or not cloud.service_token:
        print(f"  login step 3 failed with HTTP {r3.status_code}")
        return False
    write_env_keys({"XIAOMI_USER_ID": cloud.user_id, "XIAOMI_PASS_TOKEN": cloud.pass_token})
    print(f"  logged in. XIAOMI_USER_ID and XIAOMI_PASS_TOKEN ({len(cloud.pass_token)} chars) written to .env.")
    print("  Copy both lines to the server's .env; the bot will not need the password there.")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weather", action="store_true", help="probe only the weather fallback")
    ap.add_argument("--login", action="store_true", help="interactive Xiaomi login, stores a passToken in .env")
    args = ap.parse_args()
    try:
        cfg = load_config()
    except ConfigError as e:
        # the probe does not need a bot token; tolerate its absence
        if "TELEGRAM_BOT_TOKEN" not in str(e):
            print(f"config error: {e}", file=sys.stderr)
            return 2
        from config import parse_env_file, build_config
        values = parse_env_file(".env")
        values["TELEGRAM_BOT_TOKEN"] = "probe-only"
        cfg = build_config(values)

    if args.login:
        if not (cfg.xiaomi_username and cfg.xiaomi_password):
            print("--login needs XIAOMI_USERNAME and XIAOMI_PASSWORD in .env", file=sys.stderr)
            return 2
        print("\nInteractive Xiaomi login:")
        if not interactive_login(cfg.xiaomi_username, cfg.xiaomi_password):
            return 1
        from config import build_config, parse_env_file  # re-read: the token keys just changed
        values = parse_env_file(".env")
        values["TELEGRAM_BOT_TOKEN"] = values.get("TELEGRAM_BOT_TOKEN") or "probe-only"
        cfg = build_config(values)

    ok = True
    if not args.weather:
        if cfg.has_xiaomi:
            ok = probe_xiaomi(cfg.xiaomi_username, cfg.xiaomi_password, cfg.xiaomi_region, cfg.xiaomi_device_id,
                              cfg.xiaomi_user_id, cfg.xiaomi_pass_token) and ok
        else:
            print("\nXiaomi cloud: skipped - neither XIAOMI_USERNAME/PASSWORD nor XIAOMI_USER_ID/PASS_TOKEN set in .env")
    ok = probe_weather(cfg.latitude, cfg.longitude) and ok
    print("\nRESULT:", "OK" if ok else "PROBLEMS - see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
