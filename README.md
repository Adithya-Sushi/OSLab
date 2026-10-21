# OSLab: Estimating Reclaim Benefit Across Cgroups Sharing Compressed Swap

Operating Systems lab project by **Adithya Sushil (24BCI0286)**.

This project measures how much lasting available memory a Linux guest gains when a small reclaim request is sent to one of two background applications. The applications run in separate cgroups and share one lz4 zram swap device. The requested reclaim size is fixed at 32 MiB, and the main measurement window is 20 seconds.

## What is implemented

- C donor workloads, a foreground request service and a separate reclaim worker.
- A Python experiment harness, counter collector and checked request generator.
- A simple benefit estimator, candidate donor policies and a shared work budget.
- Matched-trial analysis, uncertainty intervals, figures and functional tests.
- An Apple Silicon launcher for a dedicated Debian ARM64 guest.

The experiment harness uses Python's standard library. Python 3.11 or later and a C compiler are needed for portable checks. The actual Linux trials used Debian 13, 3 GiB RAM and two virtual CPUs.

## Build and check

```sh
make all
python3 -m unittest discover -s tests -v
python3 -m unittest analysis.test_reference analysis.test_actuator -v
```

The cgroup actuator test requires Linux and is skipped on macOS. The foreground integration test needs permission to create a local Unix socket. Guest provisioning and the experiment commands are explained in [README.txt](README.txt).

## Completed experiments

The study contains 72 discovery trials, 72 usable held-out validation trials and 16 collector on/off trials. Two timing-invalid validation attempts were retained alongside their replacements, making 74 validation attempts in total. Two earlier calibration attempts were excluded from the research results.

Donor choice produced measurable differences in the controlled experiments. However, the E1 estimator had poor uncertainty coverage and a large attribution error under unrelated memory activity. Checkpoint A passed and Checkpoint B failed. Automatic donor selection, strong-baseline comparisons and a full confirmatory study remain future work.

See the [experiment report](results/derived/EXPERIMENT_REPORT.txt) and [implementation status](docs/IMPLEMENTATION_STATUS.txt) for the results and limitations.

## Repository contents

| Folder or file | Contents |
| --- | --- |
| `src/` | C workloads and reclaim worker |
| `harness/` | Trial runner, collector and load generator |
| `controller/` | Candidate estimator, policies and budget ledger |
| `analysis/` and `tests/` | Analysis code and functional checks |
| `configs/` | Frozen experiment settings |
| `scripts/` and `vm/` | Dedicated guest setup and launcher source |
| `docs/` | Project explanation, protocols, planning documents and exact executed source snapshots |
| `results/derived/` and `results/figures/` | Selected saved result summaries, test records and figures |
| `paper/` | Editable IEEE paper source and build scripts |
| `output/pdf/` | Initial IEEE paper draft |

The raw experiment traces, completed execution queues, VM disks, downloaded tools and local Word-report editing files are not included in this source repository. The source and analysis can be inspected and built from this checkout. Recomputing the reported numbers requires the separately saved experiment-data bundle; the summary files alone are not the raw data.

The original research runtime and the later observer dispatcher version are preserved under `docs/executed-source/`. Their recorded hashes identify the code used for the experiments.
