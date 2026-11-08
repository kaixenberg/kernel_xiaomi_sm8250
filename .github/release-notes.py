#!/usr/bin/env python3
"""Write the NidhiKernel release notes as Markdown on stdout.

Usage: release-notes.py DIST
DIST holds one <variant>.json per build (written by release.yml) next to
the zips and their .sha256 files. Needs VERSION and GITHUB_REPOSITORY in
the environment and an authenticated gh for the GitHub API.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BAKASU_GROUP = "https://t.me/BakaSU_Grp"
VARIANTS = {
    "aosp": ("AOSP-based ROMs", "nidhi", ""),
    "miui": ("MIUI / HyperOS", "nidhi-miui", "-miui"),
}


def gh_api(path):
    out = subprocess.check_output(["gh", "api", "--paginate", path], text=True)
    # --paginate concatenates JSON arrays/objects; split them back up
    dec, pos, items = json.JSONDecoder(), 0, []
    while pos < len(out):
        while pos < len(out) and out[pos].isspace():
            pos += 1
        if pos >= len(out):
            break
        obj, pos = dec.raw_decode(out, pos)
        items.append(obj)
    return items


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def previous_tag(tags, version, suffix):
    """Highest <x.y><suffix> tag below version, or None."""
    pat = re.compile(r"^(\d+(?:\.\d+)*)" + re.escape(suffix) + "$")
    older = [m.group(1) for t in tags if (m := pat.match(t))]
    older = [v for v in older if vkey(v) < vkey(version)]
    return max(older, key=vkey) + suffix if older else None


def commits_between(repo, base, head):
    """Non-merge commits in base..head, newest first."""
    if not base:
        return [], None
    pages = gh_api(f"repos/{repo}/compare/{base}...{head}?per_page=100")
    commits = [c for page in pages for c in page.get("commits", [])]
    commits = [c for c in commits if len(c["parents"]) == 1]
    return commits[::-1], f"https://github.com/{repo}/compare/{base}...{head[:12]}"


def main():
    dist = Path(sys.argv[1])
    repo = os.environ["GITHUB_REPOSITORY"]
    version = os.environ["VERSION"]
    builds = {}
    for f in sorted(dist.glob("*.json")):
        b = json.loads(f.read_text())
        b["sha256"] = (dist / (b["zip"] + ".sha256")).read_text().split()[0]
        builds[b["variant"]] = b
    order = [v for v in ("aosp", "miui") if v in builds]
    tags = [t["name"] for page in gh_api(f"repos/{repo}/tags?per_page=100") for t in page]
    first = builds[order[0]]

    out = []
    w = out.append
    w(f"NidhiKernel {version} for **alioth** (POCO F3 / Mi 11X / Redmi K40), "
      f"based on TIMISONG-dev's MagicTime.")
    w("")
    w("## Downloads")
    w("")
    w("| Zip | For | Branch | SHA-256 |")
    w("|---|---|---|---|")
    for v in order:
        b = builds[v]
        what, branch, _ = VARIANTS[v]
        w(f"| `{b['zip']}` | {what} | [`{branch}`](https://github.com/{repo}/tree/{b['sha']}) "
          f"| `{b['sha256'][:16]}…` |")
    w("")
    w("Pick the zip that matches your ROM. Full checksums are in the `.sha256` files. "
      f"Every feature is on; the [README](https://github.com/{repo}#features) lists them.")
    w("")

    w("## Build details")
    w("")
    for v in order:
        w(f"- **{v.upper()}:** `{builds[v]['release']}`, commit "
          f"[`{builds[v]['sha'][:12]}`](https://github.com/{repo}/commit/{builds[v]['sha']})")
    ksu_repo = first["ksu_url"].removesuffix(".git").removeprefix("https://github.com/")
    if first.get("ksu_code"):
        w(f"- **BakaSU driver:** {first['ksu_name']}, version code **{first['ksu_code']}** "
          f"([`{first['ksu_sha'][:8]}`](https://github.com/{ksu_repo}/commit/{first['ksu_sha']}) "
          f"in [{ksu_repo}](https://github.com/{ksu_repo}))")
    w(f"- **SuSFS:** {first['susfs']}")
    w(f"- **Compiler:** {first['clang']}, ThinLTO and CFI")
    w("")

    if first.get("ksu_code"):
        w("## BakaSU manager")
        w("")
        w(f"Use a BakaSU manager built for this kernel's driver, version code "
          f"**{first['ksu_code']}**. CI builds of the manager are posted in the "
          f"[BakaSU Telegram group]({BAKASU_GROUP}): download the one whose "
          f"version code is closest to {first['ksu_code']}.")
        w("")

    w("## Flashing")
    w("")
    w("**Before you start:** the bootloader must be unlocked. Keep your ROM's "
      "`boot`, `vendor_boot` and `dtbo` images (from its zip, e.g. with "
      "payload-dumper): flashing them back restores the stock kernel.")
    w("")
    w("Flash the zip with any AnyKernel3 flasher:")
    w("")
    w("- **Recovery** (OrangeFox, TWRP and similar): *Install* the zip, or "
      "`adb sideload NidhiKernel-….zip` from the recovery's ADB sideload mode.")
    w("- **A root app,** if you're already rooted: Kernel Flasher, Franco Kernel "
      "Manager, EX Kernel Manager, or another app that flashes AnyKernel3 zips. "
      "Some root managers have this built in.")
    w("")
    w("Then reboot. The zip writes `boot` and `dtbo` on the active slot and "
      "leaves `vendor_boot` alone. It doesn't touch the other slot, so after an "
      "OTA or a ROM update, flash it again.")
    w("")
    w("**If it doesn't boot:** recovery runs from the same `boot` partition, "
      "so use fastboot. Flash your ROM's images back, naming the active slot:")
    w("")
    w("```")
    w("fastboot getvar current-slot")
    w("fastboot flash boot_b boot.img")
    w("fastboot flash dtbo_b dtbo.img")
    w("```")
    w("")
    w("Use `_a` instead if slot a is active.")
    w("")

    w("## Changes")
    w("")
    seen = set()
    for v in order:
        b = builds[v]
        suffix = VARIANTS[v][2]
        prev = previous_tag(tags, version, suffix)
        commits, compare = commits_between(repo, prev, b["sha"])
        commits = [c for c in commits if c["sha"] not in seen]
        if v == "miui" and "aosp" in builds:
            w("### MIUI only")
            w("")
        if not prev:
            w(f"First {v.upper()} release.")
            w("")
            continue
        if commits:
            for c in commits:
                subject = c["commit"]["message"].splitlines()[0]
                w(f"- {subject} ([`{c['sha'][:9]}`](https://github.com/{repo}/commit/{c['sha']}))")
                seen.add(c["sha"])
        else:
            w("- No changes of its own beyond the ones above.")
        w("")
        w(f"Full {v.upper()} diff since {prev}: {compare}")
        w("")

    w("## Notes")
    w("")
    w("- Only alioth is supported. apollo and pipa builds can be made from the "
      "Actions tab but may not boot.")
    if "miui" in builds:
        w("- The MIUI build is compiled from the same changes on MagicTime's MIUI "
          "base. It is build-tested only; please report how it runs.")
    w(f"- Custom builds (another kernel name, features turned off) come from "
      f"**Actions → Build NidhiKernel**; see the "
      f"[README](https://github.com/{repo}#building-with-github-actions).")
    print("\n".join(out))


if __name__ == "__main__":
    main()
