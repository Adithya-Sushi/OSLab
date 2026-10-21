"""Package source and executed evidence after the bounded pilot has stopped."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile
from harness.common import ROOT,write_json

def sha256(path):
    with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()

def archive(destination,files):
    with zipfile.ZipFile(destination,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as output:
        for path in sorted(set(files)):
            output.write(path,arcname=str(Path(ROOT.name)/path.relative_to(ROOT)))

def main():
    status=json.loads((ROOT/"results/derived/pilot-status.json").read_text())
    if status["state"] not in ("stopped_at_checkpoint_A","stopped_at_checkpoint_B","complete"):
        raise SystemExit("refusing to package an unfinished pilot phase")
    verification=json.loads((ROOT/"results/derived/artifact-verification.json").read_text())
    if not verification["valid"]:raise SystemExit("artifact audit has unresolved findings")
    output=ROOT/"output";pdf_directory=output/"pdf";pdf_directory.mkdir(parents=True,exist_ok=True)
    paper=ROOT/"paper/OSLab_IEEE_Initial_Draft.pdf"
    if not paper.exists():raise SystemExit("compiled paper is missing")
    shutil.copy2(paper,pdf_directory/paper.name)
    # Preserve the actual Linux functional-suite log outside the VM command queue.
    linux_tests=ROOT/"vm/outbox/0007-current-tests.log"
    if linux_tests.exists():shutil.copy2(linux_tests,ROOT/"results/derived/linux-tests.log")
    source=[]
    for name in ("src","harness","controller","analysis","configs","scripts","tests","docs"):
        source.extend(path for path in (ROOT/name).rglob("*") if path.is_file() and "__pycache__" not in path.parts
                      and not (name=="configs" and ("generated" in path.parts or "progress" in path.name or path.name=="validation-technical-repeats.json")))
    source.extend(ROOT/name for name in ("Makefile","README.txt",".gitignore","requirements-analysis.txt"))
    source.extend(path for path in (ROOT/"paper").iterdir() if path.suffix in (".py",".tex"))
    for name in ("runner.swift","provision_macos.py","entitlements.plist","image-verification.json","image-manifest.json","image-http-headers.txt","SHA512SUMS"):
        path=ROOT/"vm"/name
        if path.exists():source.append(path)
    source.extend(path for path in (ROOT/"vm/seed").iterdir() if path.is_file())
    source.append(pdf_directory/paper.name)
    data=[path for path in (ROOT/"results/raw").rglob("*") if path.is_file()]
    data.extend(path for path in (ROOT/"results/overhead").rglob("*") if path.is_file())
    data.extend(path for path in (ROOT/"results/figures").rglob("*") if path.is_file())
    data.extend(path for path in (ROOT/"results/derived").rglob("*") if path.is_file() and
                not path.name.startswith("interim") and path.name!="native-tests.log")
    data.extend(path for path in (ROOT/"configs").rglob("*") if path.is_file() and
                ("generated" in path.parts or "progress" in path.name or path.name=="validation-technical-repeats.json"))
    source_manifest={str(path.relative_to(ROOT)):sha256(path) for path in sorted(set(source))}
    data_manifest={str(path.relative_to(ROOT)):sha256(path) for path in sorted(set(data))}
    write_json(output/"source-manifest.json",source_manifest)
    write_json(output/"data-manifest.json",data_manifest)
    source.append(output/"source-manifest.json");data.append(output/"data-manifest.json")
    archive(output/"OSLab_Source.zip",source)
    archive(output/"OSLab_Experiment_Data.zip",data)
    published=[output/"OSLab_Source.zip",output/"OSLab_Experiment_Data.zip",pdf_directory/paper.name]
    (output/"SHA256SUMS").write_text("\n".join(sha256(path)+"  "+str(path.relative_to(output)) for path in published)+"\n")
    print(json.dumps({"state":status["state"],"source_files":len(source),"evidence_files":len(data),
                      "outputs":[str(path) for path in published]},indent=2))

if __name__=="__main__":main()
