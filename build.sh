#!/usr/bin/env bash
# Build and package NidhiKernel. Used as-is by the GitHub workflow.
#
#   ./build.sh                     configure, build and zip
#   ./build.sh --no-package        configure and build only
#   ./build.sh -- <make targets>   configure, then make these targets only
#
# Settings (environment variables, all optional):
#   DEVICE        alioth (default, the only supported device), apollo, pipa
#   KERNEL_NAME   name in uname after the version (default NidhiKernel)
#   DISABLE       space-separated switches to turn off, e.g. "BBG NTSYNC".
#                 Each is a CONFIG_ option from
#                 arch/arm64/configs/vendor/xiaomi/magictime-common.config,
#                 or NET_EXTRAS for the whole networking extras block.
#   VARIANT       aosp or miui (default: miui on a *miui* branch, else aosp)
#   OUT           build directory (default: out)
#   CLANG_DIR     toolchain root; its bin/ goes first in PATH. Otherwise
#                 clang, ld.lld and llvm-* must already be in PATH.
#   JOBS          parallel jobs (default: nproc)
#   PODMAN_IMAGE  run the build inside this podman image, e.g.
#                 localhost/kernel-dev-env (the source, OUT, CLANG_DIR and
#                 CCACHE_DIR are mounted at the same paths)
#   KBUILD_BUILD_USER, KBUILD_BUILD_HOST   shown in /proc/version
#
# Switches that are always available:
#   KSU KSU_SUSFS NOMOUNT BBG REKERNEL DROIDSPACES EFFCPU EFFGPU KCOMPRESSD
#   LZ4_ARM64_NEON TCP_CONG_BBR ARM64_TUNE_SM8250 K11A_PANEL_90HZ
#   DRM_SDE_EXPO DRM_MSM_BACKLIGHT_MIN BOEFFLA_WL_BLOCKER NTSYNC
#   NTSYNC_APP_ACCESS NET_EXTRAS
set -euo pipefail

SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SRC"

PACKAGE=1
TARGETS=()
while [ $# -gt 0 ]; do
    case $1 in
        --no-package) PACKAGE=0 ;;
        --) shift; TARGETS=("$@"); PACKAGE=0; break ;;
        -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1 (see --help)" >&2; exit 1 ;;
    esac
    shift
done

DEVICE=${DEVICE:-alioth}
KERNEL_NAME=${KERNEL_NAME:-NidhiKernel}
OUT=${OUT:-out}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
JOBS=${JOBS:-$(nproc)}
BRANCH=${GITHUB_REF_NAME:-$(git branch --show-current 2>/dev/null || true)}
case ${VARIANT:-} in
    aosp|miui) ;;
    '') case $BRANCH in *miui*) VARIANT=miui ;; *) VARIANT=aosp ;; esac ;;
    *) echo "VARIANT must be aosp or miui" >&2; exit 1 ;;
esac

case $DEVICE in
    alioth) NAMES="alioth aliothin" ;;
    apollo) NAMES="apollo apollon" ;;
    pipa) NAMES="pipa" ;;
    *) echo "Unknown DEVICE: $DEVICE (alioth, apollo or pipa)" >&2; exit 1 ;;
esac
if ! [[ $KERNEL_NAME =~ ^[A-Za-z0-9._+-]{1,32}$ ]]; then
    echo "KERNEL_NAME may only use letters, digits and . _ + - (max 32)" >&2
    exit 1
fi
[ "$DEVICE" = alioth ] || echo "warning: $DEVICE is not officially supported: the build may fail or not boot" >&2

# Re-run inside the container, with every path mounted where it is now.
if [ -n "${PODMAN_IMAGE:-}" ] && [ -z "${NIDHI_IN_CONTAINER:-}" ]; then
    mounts=()
    for d in "$SRC" "$OUT" ${CLANG_DIR:+"$CLANG_DIR"} ${CCACHE_DIR:+"$CCACHE_DIR"}; do
        mkdir -p "$d"
        mounts+=(-v "$d:$d")
    done
    args=()
    [ $PACKAGE = 1 ] || args+=(--no-package)
    [ ${#TARGETS[@]} = 0 ] || args+=(-- "${TARGETS[@]}")
    exec podman run --rm --userns=keep-id --security-opt label=disable "${mounts[@]}" \
        -e NIDHI_IN_CONTAINER=1 -e DEVICE -e KERNEL_NAME -e DISABLE -e VARIANT="$VARIANT" \
        -e OUT="$OUT" -e CLANG_DIR -e JOBS="$JOBS" -e CCACHE_DIR -e CCACHE_MAXSIZE \
        -e GITHUB_REF_NAME="$BRANCH" \
        -e KBUILD_BUILD_USER="${KBUILD_BUILD_USER:-$(id -un)}" \
        -e KBUILD_BUILD_HOST="${KBUILD_BUILD_HOST:-podman}" \
        -w "$SRC" "$PODMAN_IMAGE" "$SRC/build.sh" "${args[@]}"
fi

if [ -n "${CLANG_DIR:-}" ]; then
    export PATH="$CLANG_DIR/bin:$PATH"
    export LD_LIBRARY_PATH="$CLANG_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
command -v clang >/dev/null || { echo "clang is not in PATH; set CLANG_DIR" >&2; exit 1; }
CC=clang
command -v ccache >/dev/null && CC="ccache clang"

# One set of variables for every make call, so Kconfig sees the same Clang
# as the build and keeps ThinLTO and CFI.
MAKE_ARGS=(
    O="$OUT" ARCH=arm64
    CROSS_COMPILE=aarch64-linux-gnu- CROSS_COMPILE_COMPAT=arm-linux-gnueabi-
    CC="$CC" HOSTCC=gcc HOSTCXX=g++ LD=ld.lld AS=llvm-as AR=llvm-ar NM=llvm-nm
    OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip LLVM=1 LLVM_IAS=1
    KBUILD_BUILD_USER="${KBUILD_BUILD_USER:-$(id -un)}"
    KBUILD_BUILD_HOST="${KBUILD_BUILD_HOST:-$(uname -n)}"
)

# --- Configure -------------------------------------------------------------
# Switches go in with the defconfig merge: disabling them afterwards would
# leave everything they select turned on.
FRAGMENT_NAME=nidhi-variant.config
FRAGMENT=arch/arm64/configs/$FRAGMENT_NAME
trap 'rm -f "$SRC/$FRAGMENT"' EXIT
tr -d '\r' < arch/arm64/configs/vendor/xiaomi/magictime-common.config > "$FRAGMENT"
sed -i "s|^CONFIG_LOCALVERSION=.*|CONFIG_LOCALVERSION=\"-$KERNEL_NAME\"|" "$FRAGMENT"

CHECK=()
for opt in ${DISABLE:-}; do
    case $opt in
        NET_EXTRAS)
            # The block ends at the first blank line
            sed -i '/^# Networking extras/,/^$/d' "$FRAGMENT"
            CHECK+=(IP_SET IP_NF_TARGET_TTL IP6_NF_TARGET_HL NET_ACT_CONNMARK CIFS)
            continue ;;
        *[!A-Z0-9_]*|'')
            echo "Bad switch name: $opt" >&2; exit 1 ;;
    esac
    grep -q "^CONFIG_$opt=" "$FRAGMENT" || { echo "Unknown switch: $opt" >&2; exit 1; }
    sed -i "/^CONFIG_$opt=/d" "$FRAGMENT"
    echo "# CONFIG_$opt is not set" >> "$FRAGMENT"
    CHECK+=("$opt")
    case $opt in
        # KernelSU needs some hook: without SuSFS use the manual hooks
        KSU_SUSFS) echo "CONFIG_KSU_MANUAL_HOOK=y" >> "$FRAGMENT" ;;
        # The defconfig pass would otherwise keep baseband_guard in the LSM list
        BBG) echo 'CONFIG_LSM="lockdown,yama,loadpin,safesetid,integrity,selinux,smack,tomoyo,apparmor,bpf"' >> "$FRAGMENT" ;;
        TCP_CONG_BBR) printf '# CONFIG_DEFAULT_BBR is not set\nCONFIG_DEFAULT_CUBIC=y\n' >> "$FRAGMENT" ;;
    esac
done

make "${MAKE_ARGS[@]}" "${DEVICE}_defconfig" "$FRAGMENT_NAME"
rm -f "$FRAGMENT"

grep -E '^CONFIG_(CC_IS_CLANG|LTO_CLANG|THINLTO|CFI_CLANG)=' "$OUT/.config"
bad=0
for opt in "${CHECK[@]}"; do
    if grep -qE "^CONFIG_$opt=[ym]" "$OUT/.config"; then
        echo "error: CONFIG_$opt is still enabled" >&2
        bad=1
    fi
done
[ $bad = 0 ] || exit 1
echo "Disabled: ${DISABLE:-none}"

# --- Build -----------------------------------------------------------------
if [ ${#TARGETS[@]} -gt 0 ]; then
    make "${MAKE_ARGS[@]}" -j"$JOBS" "${TARGETS[@]}"
    exit 0
fi
make "${MAKE_ARGS[@]}" -j"$JOBS"
[ $PACKAGE = 1 ] || exit 0

# --- Package ---------------------------------------------------------------
RELEASE=$(cat "$OUT/include/config/kernel.release")
# BakaSU's version, as compiled in (its Kbuild derives it from git)
KSU_CODE=$(grep -ohs -- '-DKSU_VERSION=[0-9]*' "$OUT"/drivers/kernelsu/.*.cmd "$OUT"/drivers/kernelsu/*/.*.cmd | head -1 | cut -d= -f2 || true)
KSU_NAME=$(grep -ohs -- '-DKSU_VERSION_FULL=[^ ]*' "$OUT"/drivers/kernelsu/.*.cmd "$OUT"/drivers/kernelsu/*/.*.cmd | head -1 | cut -d= -f2 | tr -d '\\"' || true)
CLANG_VERSION=$(clang --version | head -1)
BOOT=$OUT/arch/arm64/boot
ZIP_NAME=NidhiKernel-$VARIANT-$DEVICE-$(date -u +%Y%m%d-%H%M)
STAGE=$OUT/ak3
[ -f AnyKernel3/anykernel.sh ] || { echo "The AnyKernel3 submodule is empty: git submodule update --init" >&2; exit 1; }

rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -r AnyKernel3/. "$STAGE/"
rm -rf "$STAGE/.git" "$STAGE/README.md"
cp "$BOOT/Image" "$BOOT/dtbo.img" "$STAGE/"
# pipa takes its dtb from the kernel; AnyKernel3 repacks vendor_boot
[ "$DEVICE" != pipa ] || find "$OUT/arch/arm64/boot/dts/vendor/qcom" -name '*.dtb' -exec cat {} + > "$STAGE/dtb"

sed -i '/^device\.name[0-9]=/d' "$STAGE/anykernel.sh"
n=1
for name in $NAMES; do
    sed -i "/^do\.cleanuponabort=/a device.name$n=$name" "$STAGE/anykernel.sh"
    n=$((n + 1))
done
sed -i "s|^kernel.string=.*|kernel.string=NidhiKernel $RELEASE ($VARIANT, $DEVICE)|" "$STAGE/anykernel.sh"
sh -n "$STAGE/anykernel.sh"
grep -E '^(kernel\.string|device\.name)' "$STAGE/anykernel.sh"

ZIP=$OUT/$ZIP_NAME.zip
rm -f "$ZIP"
(cd "$STAGE" && zip -r9q "$ZIP" .)

if [ -n "${GITHUB_OUTPUT:-}" ]; then
    {
        echo "zip_name=$ZIP_NAME"
        echo "stage=$STAGE"
        echo "release=$RELEASE"
        echo "variant=$VARIANT"
        echo "zip=$ZIP"
        echo "ksu_code=$KSU_CODE"
        echo "ksu_name=$KSU_NAME"
        echo "clang=$CLANG_VERSION"
    } >> "$GITHUB_OUTPUT"
fi
echo "Kernel: $RELEASE ($VARIANT, $DEVICE)"
[ -z "$KSU_CODE" ] || echo "BakaSU: $KSU_NAME (version code $KSU_CODE)"
echo "Compiler: $CLANG_VERSION"
echo "Zip: $ZIP"
