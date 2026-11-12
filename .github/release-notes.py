#!/usr/bin/env python3
"""Write the NidhiKernel release notes as Markdown on stdout.

Usage: release-notes.py DIST
DIST holds one <variant>.json per build (written by release.yml) next to
the zips and their .sha256 files. Needs VERSION and GITHUB_REPOSITORY in
the environment and an authenticated gh for the GitHub API.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

KSU_UPSTREAM = "https://github.com/backslashxx/KernelSU"
KOWSU = "https://github.com/KOWX712/KernelSU"
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


def previous_tag(releases, tags, version, suffix):
    """Tag of the newest earlier release that has a <x><suffix> tag, or None.

    Releases are named after either version numbers (3.1) or short commit
    ids, so they are ordered by date rather than by name.
    """
    for rel in releases:  # newest first
        if rel.get("draft"):
            continue
        base = rel["tag_name"].removesuffix("-miui")
        if base == version:
            continue
        if base + suffix in tags:
            return base + suffix
    return None


def commit(repo, sha):
    return gh_api(f"repos/{repo}/commits/{sha}")[0]


def commits_between(repo, base, head, limit=400):
    """Our commits from head back to the base tag, newest first.

    Walks the first-parent chain, as a GitHub compare would also list every
    upstream commit after MagicTime rewrites its history. Upstream merges
    ("Merge upstream ...") and nidhi -> nidhi-miui merges are one line or
    skipped; other merges (feature branches) are expanded into their own
    commits.
    """
    if not base:
        return [], None
    stop = commit(repo, base)["sha"]
    out, sha = [], head
    for _ in range(limit):
        if sha == stop:
            break
        c = commit(repo, sha)
        subject = c["commit"]["message"].splitlines()[0]
        parents = [x["sha"] for x in c["parents"]]
        if len(parents) == 1:
            out.append(c)
        elif subject.startswith("Merge upstream"):
            out.append(c)
        elif not subject.startswith("Merge branch 'nidhi' into"):
            pages = gh_api(f"repos/{repo}/compare/{parents[0]}...{parents[1]}?per_page=100")
            side = [x for page in pages for x in page.get("commits", [])
                    if len(x["parents"]) == 1]
            out.extend(side[::-1])
        if not parents:
            break
        sha = parents[0]
    return out, f"https://github.com/{repo}/compare/{base}...{head[:12]}"


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
    tags = {t["name"] for page in gh_api(f"repos/{repo}/tags?per_page=100") for t in page}
    releases = [r for page in gh_api(f"repos/{repo}/releases?per_page=100") for r in page]
    releases.sort(key=lambda r: r["created_at"], reverse=True)
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
        w(f"- **KernelSU driver:** {first['ksu_name']}, version code **{first['ksu_code']}** "
          f"([`{first['ksu_sha'][:8]}`](https://github.com/{ksu_repo}/commit/{first['ksu_sha']}) "
          f"in [{ksu_repo}](https://github.com/{ksu_repo}))")
    w(f"- **SuSFS:** {first['susfs']}")
    w(f"- **Compiler:** {first['clang']}, ThinLTO and CFI")
    w("")

    if first.get("ksu_code"):
        w("## KernelSU manager")
        w("")
        w(f"The driver is [backslashxx KernelSU]({KSU_UPSTREAM}) with SuSFS, "
          f"version code **{first['ksu_code']}**. Use its manager from the "
          f"[releases]({KSU_UPSTREAM}/releases) or CI, or the "
          f"[KOWSU manager]({KOWSU}) (`com.kowx712.supermanager`), which the "
          f"driver also accepts. Some ROMs hide `me.weishu.kernelsu` from "
          f"other apps, which breaks the official manager's WebUI; KOWSU is "
          f"not affected.")
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
        prev = previous_tag(releases, tags, version, suffix)
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
