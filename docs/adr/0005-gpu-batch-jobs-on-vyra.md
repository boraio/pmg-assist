# 0005 — Batch work on VYRA's GPU: embeddings as a Kubernetes Job

- Status: Accepted
- Date: 2026-11-22, accepted 2026-11-23
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

### 1. This project's batch work runs as Jobs in `pmg-assist`, pinned to the free GPU

Embedding runs as a Kubernetes Job in the `pmg-assist` namespace on `zeru`,
requesting one GPU (`nvidia.com/gpu: 1`) so the scheduler counts it. The
scheduler's choice is not enforced inside the container (checked 2026-11-23,
below), so each Job also sets `CUDA_VISIBLE_DEVICES` to the free GPU's UUID,
`GPU-9c0b7326-8de2-1264-2e5f-c3da2c0e428e` (index 1), and PyTorch then sees
only that GPU. Jobs never use `llama-server`'s GPU,
`GPU-a23a0398-19e9-75ee-32a6-664fc70db316` (index 0). The owner starts a Job
when the free GPU is not needed for other work, such as Houdini; a Job holds it
only while it runs. Moving a Job to the other GPU is a change to that one value.

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
- The cluster does not enforce GPU allocation inside containers: every pod on
  `zeru` sees both GPUs. That is a cluster matter too (the device plugin or the
  container runtime); this project works around it in its own Jobs only.
- The pin is hard-coded. If the GPUs are swapped or `llama-server` moves, run
  `infra/k8s/gpu-check.yaml` again and change the value.

## Measured and checked, 2026-11-23

- Throughput: the first Job embedded the 149,067 chunks in 670 seconds, about
  220 a second, 10–12 times nia's CPU. It ran before the pin, almost certainly
  on GPU 0 beside `llama-server`; bge-small fitted in the memory left over.
- Visibility (`infra/k8s/gpu-check.yaml`): inside a `pmg-assist` container
  `NVIDIA_VISIBLE_DEVICES` is `void`, PyTorch sees both GPUs, and its `cuda:0`
  is GPU 0: holding 512 MiB raised GPU 0's memory from 10,065 to 10,687 MiB and
  left GPU 1 at a few MiB. With `CUDA_VISIBLE_DEVICES` set to GPU 1's UUID,
  PyTorch sees one GPU and the same 512 MiB lands on GPU 1 (1 to 625 MiB),
  leaving GPU 0 at 10,065 MiB.

## Open

- When the cluster enforces GPU allocation inside containers, the pin can go.
