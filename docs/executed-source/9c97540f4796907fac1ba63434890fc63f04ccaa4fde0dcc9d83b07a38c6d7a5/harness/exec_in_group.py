"""Move before exec, so the workload's large allocation belongs to its leaf."""
import os
from pathlib import Path
import sys

def main():
    if len(sys.argv) < 3: raise SystemExit("usage: exec_in_group CGROUP COMMAND ...")
    (Path(sys.argv[1])/"cgroup.procs").write_text(str(os.getpid()))
    os.execv(sys.argv[2], sys.argv[2:])

if __name__ == "__main__": main()
