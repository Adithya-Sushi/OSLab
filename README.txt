OSLab: Benefit-Guided Memory Reclaim
==================================
Author: Adithya Sushil, 24BCI0286
Email: adithya.sushil2024@vitstudent.ac.in

This artifact implements the measurement-first pilot in the final implementation
plan. Research outcomes, implementation status and pending work are recorded in
docs/IMPLEMENTATION_STATUS.txt and results/derived/EXPERIMENT_REPORT.txt.

Quick start: portable verification
----------------------------------
  make all
  python3 -m unittest discover -s tests -v
  python3 -m unittest analysis.test_reference -v
  python3 -m unittest analysis.test_actuator -v

Python 3.11+ is required (the guest uses 3.13). C workloads build with the system
C compiler. On macOS, a sandbox that forbids binding a Unix socket prevents the
foreground integration test; run it in the dedicated guest or a normal terminal.
Synthetic fixtures are verification inputs only and never research observations.

Dedicated Linux guest
----------------------
The supplied guest is Debian 13 ARM64, 3 GiB RAM, 2 vCPUs, launched with Apple's
Virtualization.framework on Apple Silicon. UTM can also host a Debian guest, but
backend changes require a new environment record and separate experiment phase.

The VM's disk is sparse and provisioned at 40 GiB; this is not its physical size.
The project is the sole explicitly shared writable directory. No host block
device is passed through. Image origin and SHA-512 are in vm/image-verification.json.
Downloaded image/tool binaries are excluded from the source archive.

To create a fresh guest from the pinned official image and first-boot seed:
  python3 vm/provision_macos.py --inspect
  python3 vm/provision_macos.py --directory vm/reproduction

The second command downloads the image only if absent, checks its pinned SHA-512,
creates a fresh 40-GiB sparse disk, builds/signs the launcher and prepares cloud-init.
It refuses to overwrite an existing disk. Use its printed launch command. Keep
only one VM running against this project's shared command queue at a time.

To rebuild the native launcher on macOS:
  swiftc -framework Virtualization vm/runner.swift -o vm/oslab-vm
  codesign --force --sign - --entitlements vm/entitlements.plist vm/oslab-vm

To start an already provisioned guest from this directory:
  ./vm/oslab-vm "$PWD/vm/debian.raw" "$PWD/vm/seed.iso" "$PWD"

The first cloud-init boot installs the compiler and Python, mounts the share and
enables oslab-agent.service. The agent is root only inside the dedicated guest.
Guest provisioning refuses to replace an unrelated existing swap backend and
requires /etc/oslab-research-vm. Every boot initializes one 1-GiB lz4 zram device.

Use the file-queue agent through harness.run_matrix.job/wait_job. Named operations
are check, test, calibrate, trial, reboot and shutdown. There is no arbitrary
shell-command operation. vm/guest-status.json records readiness and the boot ID.

Frozen discovery matrix
------------------------
configs/discovery-matrix.json contains the prespecified 72-trial order. A matrix
hash and append-only attempt list are saved in the matching progress file.

  python3 -m harness.run_matrix --matrix configs/discovery-matrix.json --run

This resumes unattempted entries and reboots between trials. It retains failed
attempts and stops after an execution failure for diagnosis. Repeating a failure
requires an explicitly declared new attempt/matrix; do not remove old records.
Do not run two matrix drivers or two VMs on the same project simultaneously.

The runner rejects reuse of a guest boot ID. Do not bypass this check for matched
research arms. The one-page initialized swap header is allowed; used logical
swap or other stored data at the starting check is rejected.

Analyze and rebuild the draft
-------------------------------
  python3 -m analysis.reference_effects
  python3 -m analysis.trial_outcomes
  python3 -m analysis.resource_signals
  python3 -m analysis.horizon_sensitivity
  python3 -m analysis.write_report
  MPLCONFIGDIR="$PWD/tools/mpl-cache" .venv/bin/python -m analysis.plot_results
  python3 paper/build_draft.py
  ./tools/tectonic --outdir paper paper/OSLab_IEEE_Initial_Draft.tex

The experiment harness and statistical primitives need only Python's standard
library. Figures require matplotlib; requirements-analysis.txt records the
installed analysis packages. Any normal TeX Live installation containing IEEEtran
can build the standalone paper source. Numeric results are generated from the
saved selected runs; no external figures or bibliography files are required by
the standalone .tex file.

Interpretation
----------------
The fixed-dose arms characterize donor choice; they do not evaluate a coordinated
controller. The E1 estimator and five candidate policies have functional checks,
but their execution is gated until Checkpoints A and B are documented. The
uncertainty envelope is heuristic until held-out coverage is measured. The
harness process CPU counter includes collection, load generation and orchestration.
A separate eight-pair collector on/off study measures direct collector thread CPU
and incremental harness cost; its results are in observer-overhead.json.

Guest MemAvailable is the primary outcome. Do not subtract zram allocation from
it again, equate requested bytes with freed bytes, or infer macOS RAM returned
from guest headroom. An adverse outcome is retained even when it weakens the
hypothesis. Strong baselines, held-out prediction, SQLite and publication novelty
checks remain necessary wherever the implementation-status record says pending.

Completed initial study
------------------------
There are 72 usable discovery trials and 72 usable held-out trials. The held-out
execution includes two retained timing-invalid attempts and two exact-source
replacement attempts (74 attempts total). Sixteen additional fresh-boot trials
measure collector on/off overhead. Two calibration attempts are kept separately.
Checkpoint A passed; E1 failed Checkpoint B because its uncertainty envelope was
unreliable and its interference attribution error was large. No coordinated
policy, strong-baseline or full confirmatory results are claimed. The VM is off.

The final paper is output/pdf/OSLab_IEEE_Initial_Draft.pdf. The standalone source
is paper/OSLab_IEEE_Initial_Draft.tex. output/SHA256SUMS covers the PDF, source ZIP
and data ZIP. results/derived/EXPERIMENT_REPORT.txt explains the actual findings.

Reproduction and source versions
---------------------------------
The source ZIP omits completed progress state so it can be used for a fresh
replication. The data ZIP includes original progress and exact attempt configs.
In an existing working directory, copy a frozen matrix to a new filename before
repeating it; keep the old matrix, progress and outcomes intact.

The exact original research runtime is preserved under docs/executed-source/
with its SHA-256 tree identity. A separate, recorded dispatcher extension supports
the collector on/off validity study. The original dispatcher is restored before
technical repeats so the held-out arms use the exact frozen source. Only the two
predeclared generator-timing invalid arms are eligible; original records remain.
See docs/technical-repeat-protocol.json and configs/validation-technical-repeats.json.

The held-out matrix can be run with the same run_matrix command and
--matrix configs/validation-matrix.json after discovery meets Checkpoint A.
analysis/run_bounded_pilot.py records both gates for a fresh 72-trial discovery
and 72-trial validation sequence. Do not change the frozen estimator to fit these
held-out results; declare a new version and new validation cohort for redesign.

To recompute held-out diagnostics from the supplied evidence without running a VM:
  python3 - <<'PY'
  from analysis.reference_effects import load_attempts
  from analysis.estimator_quality import evaluate
  from harness.common import ROOT, write_json
  runs = load_attempts(ROOT/'results/raw', 'configs/validation-matrix.json', purpose='validation')
  write_json(ROOT/'results/derived/estimator-validation.json', evaluate(runs))
  PY

The observer study's dispatcher extension is preserved as its exact executed
source snapshot. analysis/post_pilot_checks.py orchestrates that separate phase;
analysis/complete_valid_reference_blocks.py restores the original runtime and
repeats only the declared timing-invalid arms. Their completed progress is in
the data ZIP, not the clean source ZIP. Audit a combined source/data checkout:
  python3 -m analysis.verify_artifact

Guest provisioning downloads packages and requires network access on first boot.
Use an ordinary TeX Live installation, or obtain Tectonic from its official release
and verify docs/tool-provenance.json, before running the PDF rebuild command.
