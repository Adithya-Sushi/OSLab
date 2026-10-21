import argparse
from pathlib import Path
import platform
from .common import command_version, host_information, read_text, source_manifest, write_json
from .parsers import keyed, swap_devices

def inspect(cgroup_parent="/sys/fs/cgroup", strict=True):
    parent = Path(cgroup_parent)
    env = host_information()
    env.update({"os_release": read_text("/etc/os-release"), "meminfo": keyed(read_text("/proc/meminfo")),
                "cgroup_parent": str(parent), "controllers": read_text(parent/"cgroup.controllers"),
                "subtree_control": read_text(parent/"cgroup.subtree_control"),
                "psi": read_text("/proc/pressure/memory"), "swaps": swap_devices(read_text("/proc/swaps")),
                "zswap_enabled": read_text("/sys/module/zswap/parameters/enabled"),
                "thp_enabled": read_text("/sys/kernel/mm/transparent_hugepage/enabled"),
                "lru_gen": read_text("/sys/kernel/mm/lru_gen/enabled"),
                "cmdline": read_text("/proc/cmdline"), "source": source_manifest(),
                "packages": command_version(["dpkg-query", "-W"]),
                "compiler": command_version(["cc", "--version"]), "zram": []})
    for device in sorted(Path("/sys/block").glob("zram*")):
        env["zram"].append({"name": device.name,
                            **{key: read_text(device/key) for key in
                               ("disksize", "comp_algorithm", "backing_dev", "mm_stat", "io_stat", "bd_stat")}})
    failures = []
    if platform.system() != "Linux": failures.append("Linux is required for cgroup reclaim, PSI and zram")
    if not env["controllers"] or "memory" not in env["controllers"].split():
        failures.append("cgroup v2 memory controller is unavailable")
    if env["psi"] is None: failures.append("memory PSI is unavailable")
    if strict:
        swaps = env["swaps"] or []
        if len(swaps) != 1 or not swaps[0]["path"].startswith("/dev/zram"):
            failures.append("primary experiments require exactly one zram-only swap backend")
        if env["zswap_enabled"] not in (None, "N", "0"):
            failures.append("zswap must be disabled")
        active = [d for d in env["zram"] if d["disksize"] and int(d["disksize"]) > 0]
        if len(active) != 1: failures.append("exactly one initialized zram device is required")
        if any(d["backing_dev"] not in (None, "none") for d in active):
            failures.append("zram writeback must be disabled")
    env["strict"] = strict
    env["failures"] = failures
    env["eligible"] = not failures
    return env

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="configs/environment.json")
    parser.add_argument("--cgroup-parent", default="/sys/fs/cgroup")
    parser.add_argument("--integration-only", action="store_true")
    args = parser.parse_args()
    env = inspect(args.cgroup_parent, strict=not args.integration_only)
    write_json(args.output, env)
    print("ELIGIBLE" if env["eligible"] else "UNSUPPORTED", *env["failures"], sep="\n")
    return 0 if env["eligible"] else 2

if __name__ == "__main__":
    raise SystemExit(main())
