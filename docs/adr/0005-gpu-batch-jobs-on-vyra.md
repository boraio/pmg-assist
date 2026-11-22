# 0005 — Batch work on VYRA's GPU: embeddings as a Kubernetes Job

- Status: Proposed
- Date: 2026-11-22
- Milestone: 1

## Context

- ADR 0002 (decision 3) already places embedding on `zeru` as a Kubernetes Job,
  using the free GPU when there is one. The owner confirmed on 2026-11-20 that
  running this project's own workloads on VYRA, GPU Jobs included, is in scope;
  installing or operating cluster components is not.
- Embedding the 149,067 gold chunks with bge-small-en-v1.5 on nia's CPU runs at
  19–31 chunks a second, 80–130 minutes per index version (embedding spike,
  2026-11-20). Larger models such as AfriE5 would take about a day.
- Checked on 2026-11-22: the cluster advertises 2 GPUs, both on `zeru`, both
  NVIDIA GeForce RTX 3060 with 12 GB. One is allocated to the running
  `llama-server` pod in `llm` (10 GB in use); the other shows 1 MiB in use. The
  free one is also used, when needed, for the owner's Houdini work. Driver
  615.71.09 supports CUDA up to 13.4.
- Storage classes `ceph-xfs` (default) and `ceph-ext4` provide Ceph RBD volumes
  (one node at a time). The RadosGW bucket from ADR 0002 does not exist yet.
- Nodes restart often enough that the API pod restarted 22 times in 19 days,
  each time after its node or kubelet restarted, not because the API failed.

## Decisions

### 1. This project's batch work runs as Jobs in `pmg-assist`

Embedding runs as a Kubernetes Job in the `pmg-assist` namespace on `zeru`,
requesting exactly one GPU (`nvidia.com/gpu: 1`). It never takes the GPU that
`llama-server` holds; the scheduler only offers the unallocated one. The owner
starts a Job when the second GPU is not needed for other work; a Job holds it
only while it runs.

### 2. A GPU image built in CI

`ghcr.io/boraio/pmg-assist-embed` is built by GitHub Actions from a Dockerfile
in `ingest/`, on the official `pytorch/pytorch:2.15.0-cuda13.4-cudnn9-runtime`
image (the same PyTorch version as the CPU path, and a CUDA version the driver
supports), plus sentence-transformers 6.3.0 and the `ingest/` code. Model
weights are not baked in; they download once into the data volume.

### 3. One data volume, copied in and out by hand

A `ceph-xfs` volume `pmg-data` in `pmg-assist` holds the index directory's
inputs and outputs and the model cache. Files move with `kubectl cp` through a
small helper pod pinned to `zeru`, so it and the Job can mount the volume at
the same time. The RadosGW bucket replaces this when it exists.

### 4. Restarts are survived, not avoided

The Job retries (a small `backoffLimit`) and the embed step resumes from its
partial output on the volume, as it already does on nia. A node restart costs
the batch in progress, not the run.

### 5. The embed step gains a device and larger groups

`pmg_ingest.embed` takes `--device` (`cpu` by default, `cuda` in the Job) and
hands the model groups of several hundred chunks at a time, keeping its own
batch size, so sentence-transformers can sort them by length. The marker
records the device. Vectors from a CPU run and a GPU run are never mixed in one
output; a partial CPU output is deleted before a GPU run.

## Consequences

- The embed image is large (several GB, mostly CUDA libraries); it is built
  only when its inputs change.
- Copying data with `kubectl cp` is a manual step, written out in the Makefile
  or a short runbook, until the bucket exists.
- The same pattern serves Milestone 2's generator evaluations and a future
  multilingual model.
- The `llm` namespace holds dozens of dead `llama-server` pods, and nodes
  restart often. Both are cluster matters; this project only records them.

## Open

- Throughput on the RTX 3060, measured on the first Job.
- Whether the scheduler's GPU matches the one `nvidia-smi` shows as free: the
  `llama-server` container sees both GPUs, so the first Job checks which one it
  was given and how much memory is in use on it.
