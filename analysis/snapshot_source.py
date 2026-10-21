"""Preserve the exact executed runtime before any post-study maintenance."""
import hashlib
from pathlib import Path
import shutil
from harness.common import ROOT,source_manifest,write_json

def main():
    manifest=source_manifest();destination=ROOT/"docs/executed-source"/manifest["sha256"]
    files=list(manifest["files"])+["Makefile","analysis/__init__.py","analysis/statistics.py","vm/runner.swift"]
    for relative in files:
        source=ROOT/relative;target=destination/relative
        if target.exists() and target.read_bytes()!=source.read_bytes():raise SystemExit("refusing to replace an executed source snapshot")
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    write_json(destination/"snapshot.json",{"source_manifest":manifest,"supplemental_files":[path for path in files if path not in manifest["files"]]})
    print(destination)

if __name__=="__main__":main()
