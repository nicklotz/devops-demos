# Intermediate DevOps

A three-day, hands-on course on continuous integration, infrastructure as code, credential management, containers, Kubernetes and continuous delivery. You build and run every part of a delivery pipeline yourself, on your own Linux lab machine, with Harness Open Source, Docker, a local Kubernetes cluster (k3d) and Terraform.

The course follows one application through all three days: **flight-status**, a small Python web API that tracks flights and their status. On Day 1 you put it under continuous integration. On Day 2 you build its environments with Terraform and manage the credentials that the pipeline needs. On Day 3 you package it as a container, run it on Kubernetes and deliver it to a development and a production environment with one pipeline.

## Schedule

All times are US Central. Each day has two breaks and a lunch break.

**Day 1: Continuous integration**

| Time | Session |
|---|---|
| 09:00 | Welcome and course overview |
| 09:20 | Lecture: DevOps foundations |
| 09:50 | Lecture: Version control and continuous integration |
| 10:30 | [Lab 01: Lab environment and Harness Open Source](labs/01-lab-environment.md) (60 min) |
| 11:30 | Lecture: Pipelines and Harness |
| 12:45 | [Lab 02: Your first CI pipeline](labs/02-first-ci-pipeline.md) (90 min) |
| 14:25 | Lecture: Testing and quality gates |
| 14:55 | [Lab 03: Quality gates, pull requests and integration tests](labs/03-quality-gates.md) (120 min) |

**Day 2: Infrastructure as code and credentials**

| Time | Session |
|---|---|
| 09:10 | Lecture: Infrastructure as code concepts |
| 09:40 | Lecture: Terraform, CloudFormation and the CDK |
| 10:20 | [Lab 04: Terraform foundations on Kubernetes](labs/04-terraform-foundations.md) (120 min) |
| 13:05 | Lecture: Infrastructure as code in pipelines |
| 13:35 | [Lab 05: Terraform in the pipeline](labs/05-terraform-pipeline.md) (75 min) |
| 15:00 | Lecture: Credential management |
| 15:35 | [Lab 06: Managing credentials](labs/06-credentials.md) (75 min) |

**Day 3: Containers, Kubernetes and continuous delivery**

| Time | Session |
|---|---|
| 09:10 | Lecture: Containers |
| 09:45 | Lecture: Compose, Amazon ECS and Fargate |
| 10:20 | [Lab 07: Build, scan and describe a container](labs/07-containers.md) (75 min) |
| 11:35 | Lecture: Kubernetes |
| 12:55 | [Lab 08: Kubernetes deployments, rollouts and rollbacks](labs/08-kubernetes-rollouts.md) (90 min) |
| 14:35 | Lecture: Continuous delivery |
| 15:05 | [Lab 09: End-to-end delivery pipeline](labs/09-end-to-end-delivery.md) (105 min) |

The lecture slides are in [`slides/`](slides/). The PDF versions are in [`slides/pdf/`](slides/pdf/).

## Your lab machine

Each participant gets one Linux virtual machine:

- Ubuntu 24.04 LTS with a desktop and a web browser
- 8 vCPUs, 16 GB RAM, 80 GB disk
- A user with `sudo` rights and outbound internet access

Nothing else is installed in advance. You install every tool during the labs, and each lab explains what a tool does before you install it.

| Tool | Version | Installed in |
|---|---|---|
| git, curl, jq, VS Code | Ubuntu and Microsoft packages | Lab 01 |
| Docker Engine | 29.x | Lab 01 |
| Harness Open Source | 3.3.0 | Lab 01 |
| k3d (k3s v1.35) | 5.9.0 | Lab 04 |
| kubectl | 1.35 | Lab 04 |
| Terraform | 1.17.0 | Lab 04 |
| Trivy | 0.75.0 | Lab 07 |

No AWS or Harness accounts are needed. The local Kubernetes cluster stands in for Amazon EKS. Docker Compose and an ECS task definition file stand in for Amazon ECS on Fargate. The lectures explain how each local piece maps to the services and to the Harness platform used at United.

## Getting started

Open [Lab 01](labs/01-lab-environment.md) in the browser on your lab machine and follow it from the top. Lab 01 installs git and clones this repository to `~/devops-demos`.

## If you fall behind or start on a new machine

The labs build on each other. If you join late, or your machine is replaced, the catch-up script brings a fresh machine to the start of any lab. It replays the earlier labs and checks each result.

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/nicklotz/devops-demos.git ~/devops-demos
~/devops-demos/scripts/catch-up.sh 04
```

Replace `04` with the number of the lab you want to start. The script takes several minutes per lab. It is meant for a machine where you have not started the labs.

## What is in this repository

| Path | Contents |
|---|---|
| `labs/` | The nine lab guides |
| `app/` | The starter flight-status application with its tests |
| `solutions/` | Reference files for each lab (`solutions/labNN/...`) |
| `slides/` | Lecture slides for each day (HTML and PDF) |
| `scripts/catch-up.sh` | Brings a fresh machine to the start of a lab |
| `tests/` | The runner that executes the labs end to end (`tests/run-lab.py`) |

The April 2026 version of this course (Jenkins and Ansible labs) is kept under the git tag [`v2026-04-legacy`](https://github.com/nicklotz/devops-demos/tree/v2026-04-legacy).
