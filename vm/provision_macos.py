"""Recreate the pinned research guest without overwriting an existing disk."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
PINNED_URL="https://cloud.debian.org/images/cloud/trixie/20261017-2634/debian-13-generic-arm64-20261017-2634.qcow2"

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--directory",default="vm")
    parser.add_argument("--qemu-img")
    parser.add_argument("--inspect",action="store_true")
    args=parser.parse_args()
    if platform.system()!="Darwin" or platform.machine()!="arm64":raise SystemExit("Apple Silicon macOS is required by this launcher")
    directory=(ROOT/args.directory).resolve()
    if not directory.is_relative_to(ROOT):raise SystemExit("output directory must be inside this project")
    verification=json.loads((ROOT/"vm/image-verification.json").read_text())
    image=ROOT/"vm/debian-13-generic-arm64.qcow2"
    raw=directory/"debian.raw"
    qemu=args.qemu_img or shutil.which("qemu-img") or "/Applications/Docker.app/Contents/MacOS/qemu-img"
    if not Path(qemu).exists():raise SystemExit("qemu-img is missing; supply --qemu-img PATH")
    if args.inspect:
        print(json.dumps({"pinned_image_url":PINNED_URL,"expected_sha512":verification["sha512"],
                          "image_cached":image.exists(),"target_disk_exists":raw.exists(),"qemu_img":qemu,
                          "configuration":{"ram_gib":3,"vcpus":2,"disk_gib":40,"share":str(ROOT)}},indent=2))
        return
    if raw.exists():raise SystemExit("refusing to overwrite an existing VM disk; choose a new --directory")
    directory.mkdir(parents=True,exist_ok=True)
    if not image.exists():
        temporary=image.with_suffix(".qcow2.download")
        urllib.request.urlretrieve(PINNED_URL,temporary)
        with temporary.open("rb") as stream:actual=hashlib.file_digest(stream,"sha512").hexdigest()
        if actual!=verification["sha512"]:raise SystemExit("downloaded image checksum does not match the pinned image")
        temporary.replace(image)
    with image.open("rb") as stream:actual=hashlib.file_digest(stream,"sha512").hexdigest()
    if actual!=verification["sha512"]:raise SystemExit("cached image checksum mismatch")
    commands=[
        [qemu,"convert","-f","qcow2","-O","raw",str(image),str(raw)],
        [qemu,"resize","-f","raw",str(raw),"40G"],
        ["swiftc","-module-cache-path",str(directory/"swift-cache"),"-framework","Virtualization",str(ROOT/"vm/runner.swift"),"-o",str(directory/"oslab-vm")],
        ["codesign","--force","--sign","-","--entitlements",str(ROOT/"vm/entitlements.plist"),str(directory/"oslab-vm")],
        ["hdiutil","makehybrid","-o",str(directory/"seed.iso"),"-iso","-joliet","-default-volume-name","cidata",str(ROOT/"vm/seed")]]
    for command in commands:subprocess.run(command,check=True)
    (directory/"provisioning.json").write_text(json.dumps({"commands":commands,"pinned_image_url":PINNED_URL,"sha512":actual},indent=2)+"\n")
    print("Provisioned. Start one VM only:")
    print(str(directory/"oslab-vm"),str(raw),str(directory/"seed.iso"),str(ROOT))

if __name__=="__main__":main()
