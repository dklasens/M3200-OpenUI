#!/usr/bin/env python3
"""Remote update client: check and install releases from GitHub.

Releases are published by .github/workflows/release.yml as two assets:

  manifest.json                     version, notes, asset name, sha256, size
  m3200-openui-<tag>.tar.gz         www/ + agent/ + service + optional apply.sh

The device downloads the manifest, compares versions, then downloads the
tarball over curl (the stock TLS store works; python's ssl CA bundle may
not), verifies sha256 + size, extracts with tarfile into a staging dir,
preflight-compiles the staged agent, backs up the running one, applies
files, runs an optional root apply.sh hook (for device-side changes such
as EFS toggles shipped with a release), and finally reloads systemd and
restarts the agent.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time

DEFAULT_REPO = "dklasens/M3200-OpenUI"
API_BASE = os.environ.get("M3200_UPDATE_API", "https://api.github.com")
AGENT_VERSION = "0.2-beta"

STATE_LOCK = threading.Lock()
STATE = {
    "busy": False,
    "last_check": None,
    "last_install": None,
    "error": None,
}


def repo():
    return os.environ.get("M3200_UPDATE_REPO", DEFAULT_REPO)


def update_dir(agent_dir):
    return os.path.join(agent_dir, "update")


def _state_path(agent_dir):
    return os.path.join(update_dir(agent_dir), "state.json")


def _persist(agent_dir):
    try:
        os.makedirs(update_dir(agent_dir), exist_ok=True)
        with STATE_LOCK:
            snapshot = {
                "last_check": STATE["last_check"],
                "last_install": STATE["last_install"],
                "error": STATE["error"],
            }
        # A fresh process may not have loaded the on-disk history yet; never
        # let an in-memory None clobber a persisted record (this previously
        # wiped last_install right after every install restart).
        try:
            with open(_state_path(agent_dir), "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, ValueError):
            existing = {}
        for key in ("last_check", "last_install"):
            if snapshot[key] is None and existing.get(key) is not None:
                snapshot[key] = existing[key]
        temporary = _state_path(agent_dir) + ".tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=1)
        os.replace(temporary, _state_path(agent_dir))
    except OSError:
        pass


def _load_state(agent_dir):
    with STATE_LOCK:
        if STATE.get("loaded"):
            return
        STATE["loaded"] = True
    try:
        with open(_state_path(agent_dir), "r", encoding="utf-8") as f:
            saved = json.load(f)
        with STATE_LOCK:
            STATE["last_check"] = saved.get("last_check")
            STATE["last_install"] = saved.get("last_install")
            STATE["error"] = saved.get("error")
        # A last_check captured before an install/deploy describes the old
        # version; showing it would offer an "update" to what already runs.
        with STATE_LOCK:
            stale = STATE["last_check"]
        if stale and str(stale.get("result", {}).get(
                "current_version", "")) != current_version(agent_dir):
            with STATE_LOCK:
                STATE["last_check"] = None
            _persist(agent_dir)
    except (OSError, ValueError):
        pass


def current_version(agent_dir):
    try:
        with open(os.path.join(agent_dir, "version"), "r",
                  encoding="utf-8") as f:
            return f.read().strip() or AGENT_VERSION
    except OSError:
        return AGENT_VERSION


# ----------------------------------------------------------------------
# version comparison
# ----------------------------------------------------------------------

def parse_version(text):
    """'0.2-beta' -> ((0, 2), 'beta'); '1.2.3' -> ((1, 2, 3), None)."""
    text = str(text or "").strip().lstrip("vV")
    main, _, pre = text.partition("-")
    nums = []
    for part in main.split("."):
        match = re.match(r"\d+", part)
        nums.append(int(match.group(0)) if match else 0)
    return tuple(nums), (pre or None)


def compare_versions(a, b):
    """-1 / 0 / 1 for a <, ==, > b.  A prerelease sorts below its release."""
    na, pa = parse_version(a)
    nb, pb = parse_version(b)
    if na != nb:
        return -1 if na < nb else 1
    if pa == pb:
        return 0
    if pa is None:
        return 1
    if pb is None:
        return -1
    return -1 if pa < pb else (1 if pa > pb else 0)


# ----------------------------------------------------------------------
# transport (curl: the device's python ssl store is not trustworthy)
# ----------------------------------------------------------------------

def curl_json(url, timeout=20):
    out = subprocess.run(
        ["curl", "-fsSL", "--max-time", str(timeout),
         "-H", "Accept: application/vnd.github+json", url],
        capture_output=True, timeout=timeout + 5)
    if out.returncode != 0:
        raise ValueError("update check failed (curl %s)" % out.returncode)
    return json.loads(out.stdout.decode("utf-8"))


def curl_download(url, dest, timeout=300):
    temporary = dest + ".part"
    out = subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "--max-time", str(timeout),
         "-o", temporary, url],
        capture_output=True, timeout=timeout + 10)
    if out.returncode != 0:
        raise ValueError("download failed (curl %s)" % out.returncode)
    os.replace(temporary, dest)


def fetch_latest_release():
    """Newest non-draft release, prereleases included (this is a beta line)."""
    releases = curl_json("%s/repos/%s/releases?per_page=5" % (API_BASE, repo()))
    for release in releases:
        if release.get("draft"):
            continue
        assets = {a.get("name"): a for a in release.get("assets", [])}
        manifest_asset = assets.get("manifest.json")
        if manifest_asset:
            return release, manifest_asset
    raise ValueError("no release with a manifest.json asset found")


def check(agent_dir):
    release, manifest_asset = fetch_latest_release()
    manifest = curl_json(manifest_asset["browser_download_url"])
    latest = manifest.get("version") or release.get("tag_name", "")
    current = current_version(agent_dir)
    result = {
        "repo": repo(),
        "current_version": current,
        "latest_version": latest.lstrip("v"),
        "tag": release.get("tag_name"),
        "name": release.get("name"),
        "published_at": release.get("published_at"),
        "notes": release.get("body") or "",
        "size": manifest.get("size"),
        "update_available": compare_versions(latest, current) > 0,
        "same_version": compare_versions(latest, current) == 0,
    }
    with STATE_LOCK:
        STATE["last_check"] = {"ts": time.time(), "result": result}
        STATE["error"] = None
    _persist(agent_dir)
    return result


# ----------------------------------------------------------------------
# install
# ----------------------------------------------------------------------

def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(tar, dest):
    root = os.path.realpath(dest)
    for member in tar.getmembers():
        target = os.path.realpath(os.path.join(dest, member.name))
        if not (target == root or target.startswith(root + os.sep)):
            raise ValueError("unsafe path in update package: %s" % member.name)
        if member.issym() or member.islnk():
            raise ValueError("links are not allowed in update packages")
    tar.extractall(dest)


def _run(cmd, timeout=120):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.returncode, (out.stdout + out.stderr)[-2000:]
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def restart_agent():
    subprocess.Popen(["systemctl", "restart", "m3200-agent"])


def install(agent_dir, service_path="/etc/systemd/system/m3200-agent.service",
            allow_same=True):
    """Download, verify, stage and apply the latest release.

    Runs in a worker thread; the final agent restart is scheduled so the
    HTTP response (and the dashboard poll) completes first.
    """
    with STATE_LOCK:
        if STATE["busy"]:
            raise ValueError("an update is already in progress")
        STATE["busy"] = True
        STATE["error"] = None

    work = update_dir(agent_dir)
    stage = os.path.join(work, "stage")
    log = {"started": time.time(), "steps": []}

    def step(name):
        log["steps"].append(name)

    def finish(ok, message):
        log.update(finished=time.time(), ok=ok, message=message)
        with STATE_LOCK:
            STATE["busy"] = False
            STATE["last_install"] = log
            if not ok:
                STATE["error"] = message
        _persist(agent_dir)
        return log

    try:
        step("check")
        release, manifest_asset = fetch_latest_release()
        manifest = curl_json(manifest_asset["browser_download_url"])
        latest = str(manifest.get("version") or "").lstrip("v")
        current = current_version(agent_dir)
        if not latest:
            return finish(False, "release manifest has no version")
        if compare_versions(latest, current) < 0:
            return finish(False, "release %s is older than installed %s"
                          % (latest, current))
        if compare_versions(latest, current) == 0 and not allow_same:
            return finish(False, "already at %s" % latest)

        asset_name = manifest.get("asset")
        asset = next((a for a in release.get("assets", [])
                      if a.get("name") == asset_name), None)
        if not asset:
            return finish(False, "release is missing %s" % asset_name)

        os.makedirs(work, exist_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
        tarball = os.path.join(work, asset_name)

        step("download")
        curl_download(asset["browser_download_url"], tarball)

        step("verify")
        if manifest.get("sha256") and _sha256(tarball) != manifest["sha256"]:
            return finish(False, "sha256 mismatch — refusing to install")
        if manifest.get("size") and os.path.getsize(tarball) != manifest["size"]:
            return finish(False, "size mismatch — refusing to install")

        step("extract")
        with tarfile.open(tarball, "r:gz") as tar:
            _safe_extract(tar, stage)
        pkg = stage
        if os.path.isdir(os.path.join(stage, "m3200-openui")):
            pkg = os.path.join(stage, "m3200-openui")

        staged_agent = os.path.join(pkg, "agent", "m3200_agent.py")
        staged_qmi = os.path.join(pkg, "agent", "qmi.py")
        if not os.path.isfile(staged_agent):
            return finish(False, "package is missing agent/m3200_agent.py")

        step("preflight")
        for path in (staged_agent, staged_qmi,
                     os.path.join(pkg, "agent", "update.py")):
            if os.path.isfile(path):
                rc, output = _run([sys.executable, "-m", "py_compile", path])
                if rc != 0:
                    return finish(False, "preflight compile failed: %s" % output)

        step("backup")
        for name in ("m3200_agent.py", "qmi.py"):
            src = os.path.join(agent_dir, name)
            if os.path.isfile(src):
                shutil.copy2(src, src + ".prev")

        step("apply")
        shutil.copy2(staged_agent, os.path.join(agent_dir, "m3200_agent.py"))
        if os.path.isfile(staged_qmi):
            shutil.copy2(staged_qmi, os.path.join(agent_dir, "qmi.py"))
        # The updater must be able to update itself.
        staged_update = os.path.join(pkg, "agent", "update.py")
        if os.path.isfile(staged_update):
            shutil.copy2(staged_update, os.path.join(agent_dir, "update.py"))
        staged_service = os.path.join(pkg, "agent", "m3200-agent.service")
        if os.path.isfile(staged_service) and os.path.isdir(
                os.path.dirname(service_path)):
            shutil.copy2(staged_service, service_path)
        staged_www = os.path.join(pkg, "www")
        if os.path.isdir(staged_www):
            www = os.path.join(agent_dir, "www")
            assets = os.path.join(www, "assets")
            if os.path.isdir(assets):
                shutil.rmtree(assets)
            os.makedirs(www, exist_ok=True)
            for entry in os.listdir(staged_www):
                src = os.path.join(staged_www, entry)
                dst = os.path.join(www, entry)
                if os.path.isdir(src):
                    if os.path.isdir(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
        with open(os.path.join(agent_dir, "version"), "w",
                  encoding="utf-8") as f:
            f.write(latest + "\n")

        apply_log = None
        staged_apply = os.path.join(pkg, "apply.sh")
        if os.path.isfile(staged_apply):
            step("apply.sh")
            rc, output = _run(["sh", staged_apply])
            apply_log = {"rc": rc, "output": output}
            log["apply"] = apply_log
            if rc != 0:
                return finish(False, "apply.sh failed (rc %s): %s"
                              % (rc, output))

        step("restart")
        _run(["systemctl", "daemon-reload"], timeout=30)
        # The just-installed version is by definition current: refresh the
        # check record so the dashboard never offers it back as an update.
        with STATE_LOCK:
            STATE["last_check"] = {"ts": time.time(), "result": {
                "repo": repo(), "current_version": latest,
                "latest_version": latest, "tag": release.get("tag_name"),
                "name": release.get("name"),
                "published_at": release.get("published_at"),
                "notes": release.get("body") or "",
                "size": manifest.get("size"),
                "update_available": False, "same_version": True}}
        timer = threading.Timer(1.5, restart_agent)
        timer.daemon = True
        timer.start()

        return finish(True, "installed %s%s" % (
            latest, "; device reboot required" if manifest.get(
                "requires_reboot") else ""))
    except Exception as e:
        return finish(False, str(e))


def start_install(agent_dir, allow_same=True):
    thread = threading.Thread(
        target=install, args=(agent_dir,), kwargs={"allow_same": allow_same},
        daemon=True)
    thread.start()
    return status()


def status(agent_dir=None):
    if agent_dir:
        _load_state(agent_dir)
    with STATE_LOCK:
        return {
            "repo": repo(),
            "busy": STATE["busy"],
            "error": STATE["error"],
            "last_check": STATE["last_check"],
            "last_install": STATE["last_install"],
        }


# ----------------------------------------------------------------------
# automatic update checks
# ----------------------------------------------------------------------

DEFAULT_SETTINGS = {"enabled": True, "interval_secs": 7 * 86400}  # weekly
MIN_INTERVAL = 3600
MAX_INTERVAL = 30 * 86400
WAKE = threading.Event()
SCHEDULER = {"thread": None}


def settings_path(agent_dir):
    return os.path.join(update_dir(agent_dir), "settings.json")


def load_settings(agent_dir):
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(settings_path(agent_dir), "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved.get("enabled"), bool):
            settings["enabled"] = saved["enabled"]
        interval = int(saved.get("interval_secs", 0))
        if MIN_INTERVAL <= interval <= MAX_INTERVAL:
            settings["interval_secs"] = interval
    except (OSError, ValueError):
        pass
    return settings


def save_settings(agent_dir, enabled=None, interval_secs=None):
    settings = load_settings(agent_dir)
    if enabled is not None:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        settings["enabled"] = enabled
    if interval_secs is not None:
        interval = int(interval_secs)
        if not MIN_INTERVAL <= interval <= MAX_INTERVAL:
            raise ValueError("interval_secs must be between %s and %s"
                             % (MIN_INTERVAL, MAX_INTERVAL))
        settings["interval_secs"] = interval
    os.makedirs(update_dir(agent_dir), exist_ok=True)
    temporary = settings_path(agent_dir) + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=1)
    os.replace(temporary, settings_path(agent_dir))
    WAKE.set()
    return settings


def check_due(settings, last_check_ts, now):
    return bool(settings.get("enabled")) and (
        last_check_ts is None or now - last_check_ts >= settings["interval_secs"])


def scheduler_loop(agent_dir):
    _load_state(agent_dir)  # honor the persisted interval from the first tick
    while True:
        try:
            settings = load_settings(agent_dir)
            with STATE_LOCK:
                last = (STATE["last_check"] or {}).get("ts")
                busy = STATE["busy"]
            if not busy and check_due(settings, last, time.time()):
                try:
                    check(agent_dir)
                except Exception:
                    pass  # offline / rate-limited: retry on the next wake
        except Exception:
            pass
        WAKE.wait(60)
        WAKE.clear()


def start_scheduler(agent_dir):
    if SCHEDULER["thread"] and SCHEDULER["thread"].is_alive():
        return
    thread = threading.Thread(target=scheduler_loop, args=(agent_dir,),
                              daemon=True)
    thread.start()
    SCHEDULER["thread"] = thread
