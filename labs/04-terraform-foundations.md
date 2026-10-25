# Lab 04: Terraform foundations on Kubernetes

In this lab you build the platform that the flight status service will run on.
You create a local Kubernetes cluster with k3d. Then you describe two environments, dev and prod, in Terraform: a namespace for each, limits on what can run there, and a PostgreSQL database.
You watch Terraform plan and apply changes, look at the state it keeps, and see it correct a change that someone made by hand.
At the end, the Terraform code goes into its own Git repository in Harness.

**Lecture:** L5 Infrastructure as code concepts and L6 Terraform architecture · **You need:** Lab 03 completed (or run `~/devops-demos/scripts/catch-up.sh 04` on a fresh machine)

## Goals

- Install command-line tools from signed package repositories, and check a download against its published checksum.
- Create a Kubernetes cluster from a declarative configuration file.
- Write Terraform configuration with a variable, `for_each` and a module, and run `init`, `plan` and `apply`.
- Show that Terraform is idempotent and that it corrects drift.
- Keep infrastructure code in version control without its state file.

## Before you start

You need Docker, Harness and your `flight-status` repository from Day 1.
Run these checks in a terminal.

```bash
docker ps --format '{{.Names}}: {{.Status}}'
curl -fs -o /dev/null -w 'Harness answers with HTTP %{http_code}\n' http://localhost:3000/api/v1/system/config
git -C ~/flight-status log --oneline -3
```

You should see the `harness` container with status `Up`, `Harness answers with HTTP 200`, and the last commits of your flight status repository.

```text
harness: Up 2 hours
Harness answers with HTTP 200
1a2b3c4 Add departures board (#1)
...
```

If `docker ps` reports `permission denied`, run `newgrp docker` in this terminal and try again (Lab 01 explains why).

In this lab you create files in a new folder, `~/platform`.
When a step shows a file with its path, create that file in VS Code and paste the content.
If you do not use VS Code, the Text Editor app works too.

## Part 1: Install k3d, kubectl and Terraform

Today's tools come from three places.
k3d comes from its GitHub release page.
kubectl comes from the Kubernetes project's apt repository.
Terraform comes from HashiCorp's apt repository.
Each install pins a version, so every student and every pipeline runs the same software.

### 1.1 Install k3d and check its checksum

k3d runs k3s, a small Kubernetes distribution, inside Docker containers.
It gives you a real Kubernetes API on your lab machine.
At United, the equivalent is Amazon EKS, which runs the Kubernetes control plane for you in AWS.

You download k3d as a single binary file.
The project publishes a SHA-256 checksum for every file it releases.
If you compute the checksum of your download and it matches the published one, the file is the one the project released.
If the download was damaged or replaced, the numbers differ.

Download the binary and the checksum list:

```bash
mkdir -p ~/downloads && cd ~/downloads
curl -fsSLO https://github.com/k3d-io/k3d/releases/download/v5.9.0/k3d-linux-amd64
curl -fsSLO https://github.com/k3d-io/k3d/releases/download/v5.9.0/checksums.txt
grep 'k3d-linux-amd64$' checksums.txt
```

The last command prints the published line for your file: a long hexadecimal hash and a path.
The paths in this list start with `_dist/`, the folder in which the k3d project built its files.
Your file is in the current folder, so the next command takes only the hash from that line and checks it against your file.

```bash
echo "$(grep '_dist/k3d-linux-amd64$' checksums.txt | cut -d' ' -f1)  k3d-linux-amd64" | sha256sum --check
```

You should see:

```text
k3d-linux-amd64: OK
```

Only install the file when the check says `OK`.
`install` copies the file to `/usr/local/bin`, which is on your `PATH`, and makes it executable.

```bash
sudo install -m 0755 k3d-linux-amd64 /usr/local/bin/k3d
k3d version
```

```text
k3d version v5.9.0
k3s version v1.35.5-k3s1 (default)
```

### 1.2 Install kubectl 1.35

kubectl is the command-line client for the Kubernetes API.
Kubernetes supports a kubectl that is at most one minor version older or newer than the API server.
This is the version skew policy.
The cluster you create in Part 2 runs Kubernetes 1.35, so you install kubectl from the repository for the 1.35 line.

The steps follow the same pattern you used for Docker and VS Code in Lab 01:

1. Download the publisher's signing key and store it in `/etc/apt/keyrings`.
2. Add the repository, and tell apt to trust only packages signed with that key (`signed-by`).
3. Update the package lists and install.

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.35/deb/Release.key | sudo gpg --dearmor --yes -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo "deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.35/deb/ /" | sudo tee /etc/apt/sources.list.d/kubernetes.list > /dev/null
sudo apt-get update
sudo apt-get install -y kubectl
kubectl version --client
```

You should see a client version that starts with `v1.35`:

```text
Client Version: v1.35.9
Kustomize Version: v5.7.1
```

The patch number (the last part) may be higher.
Kustomize is built into kubectl. You use it on Day 3.

### 1.3 Install Terraform 1.17.0

Terraform reads configuration files that describe infrastructure and makes the real infrastructure match them.
The pipeline you build in Lab 05 runs Terraform in the container image `hashicorp/terraform:1.17.0`.
You install the same version here, so your local runs and the pipeline's runs behave the same way.

`terraform=1.17.0-1` asks apt for one exact package version.
`apt-mark hold` stops a later `apt-get upgrade` from replacing it.

```bash
wget -qO- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor --yes -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(. /etc/os-release && echo "$VERSION_CODENAME") main" | sudo tee /etc/apt/sources.list.d/hashicorp.list > /dev/null
sudo apt-get update
sudo apt-get install -y terraform=1.17.0-1
sudo apt-mark hold terraform
terraform version
```

```text
terraform set on hold.
Terraform v1.17.0
on linux_amd64
```

Terraform may add a note that a newer version is available. You can ignore it.

<!-- test
k3d version | grep -q 'v5.9.0'
kubectl version --client | grep -q 'v1.35'
terraform version | grep -q 'v1.17.0'
-->

## Part 2: Create the registry and the cluster

### 2.1 Create a local image registry

On Day 3 you build container images, and the cluster pulls them to run your application.
A registry stores images.
In AWS, this would be Amazon Elastic Container Registry (ECR).
k3d can run a small registry as a container next to the cluster.

This registry uses plain HTTP. It has no TLS certificate.
That is why you added it to `insecure-registries` in `/etc/docker/daemon.json` in Lab 01.
Docker refuses to push to a plain-HTTP registry unless it is on that list.

```bash
k3d registry create registry.localhost --port 5000
docker ps --filter name=k3d-registry.localhost --format '{{.Names}}  {{.Ports}}'
curl -s --retry 5 --retry-connrefused --retry-delay 1 http://k3d-registry.localhost:5000/v2/_catalog
```

k3d adds the prefix `k3d-` to the container name.
The last command asks the registry for its list of repositories. It is empty for now.

```text
k3d-registry.localhost  0.0.0.0:5000->5000/tcp
{"repositories":[]}
```

### 2.2 Describe the cluster in a file

You could create the cluster with a long command line.
A configuration file states the same settings in a form that you can read, review and keep in Git.
It is a small example of declarative configuration: the file says what the cluster should look like, and k3d works out how to create it.
This file becomes the first file of your platform repository.

Create the folder for the platform code:

```bash
mkdir -p ~/platform/cluster
```

Open the folder in VS Code, so you can create the files of this lab there.
You can also use File > Open Folder in VS Code.

<!-- skip -->
```bash
code ~/platform
```

Create `~/platform/cluster/k3d-devops.yaml` with this content:

<!-- file: ~/platform/cluster/k3d-devops.yaml -->
```yaml
# k3d cluster for the course labs: one k3s server, the shared "devops" Docker
# network, the local registry, and the ingress on http://localhost:8080.
apiVersion: k3d.io/v1alpha5
kind: Simple
metadata:
  name: devops
servers: 1
agents: 0
image: rancher/k3s:v1.35.5-k3s1
network: devops
kubeAPI:
  hostIP: "0.0.0.0"
  hostPort: "6550"
ports:
  - port: 8080:80
    nodeFilters:
      - loadbalancer
registries:
  use:
    - k3d-registry.localhost:5000
```

What each setting does:

| Setting | Meaning |
|---|---|
| `metadata.name: devops` | The cluster name. Container names and the kubectl context are derived from it. |
| `servers: 1`, `agents: 0` | One k3s server, which runs the control plane and your workloads. EKS runs the control plane for you and adds worker nodes. |
| `image` | The k3s version, pinned to Kubernetes 1.35.5. |
| `network: devops` | The Docker network you created in Lab 01. Harness is already on it, so pipeline steps can reach the cluster by name (Lab 05). |
| `kubeAPI` | Publishes the Kubernetes API on port 6550 of your machine. |
| `ports: 8080:80` | Publishes the cluster's HTTP ingress on port 8080 of your machine, through a load balancer container. |
| `registries.use` | Connects the registry from step 2.1 and tells the cluster to pull images from it over HTTP. |

### 2.3 Create the cluster

```bash
k3d cluster create --config ~/platform/cluster/k3d-devops.yaml
```

This takes about a minute.
k3d pulls the k3s image, starts the containers, and waits until the API answers.
It also adds the new cluster to `~/.kube/config` and makes it the current context.
A context is a named combination of cluster, user and default namespace in that file.

The output ends with:

```text
INFO[0035] Cluster 'devops' created successfully!
INFO[0035] You can now use it like this:
kubectl cluster-info
```

Check that kubectl talks to the new cluster:

```bash
kubectl config current-context
kubectl get nodes
kubectl cluster-info
```

```text
k3d-devops
NAME                  STATUS   ROLES           AGE   VERSION
k3d-devops-server-0   Ready    control-plane   40s   v1.35.5+k3s1
Kubernetes control plane is running at https://0.0.0.0:6550
CoreDNS is running at https://0.0.0.0:6550/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
Metrics-server is running at https://0.0.0.0:6550/api/v1/namespaces/kube-system/services/https:metrics-server:https/proxy
```

<!-- test
kubectl get nodes --no-headers | grep -q ' Ready '
-->

### 2.4 See what k3d created

A k3d cluster is a set of Docker containers.
Looking at them shows how the parts connect.

```bash
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
docker network inspect devops --format '{{range .Containers}}{{.Name}}{{"\n"}}{{end}}'
```

```text
NAMES                    IMAGE                            PORTS
k3d-devops-serverlb      ghcr.io/k3d-io/k3d-proxy:5.9.0   0.0.0.0:6550->6443/tcp, 0.0.0.0:8080->80/tcp
k3d-devops-server-0      rancher/k3s:v1.35.5-k3s1
k3d-registry.localhost   registry:2                       0.0.0.0:5000->5000/tcp
harness                  harness/harness:3.3.0            0.0.0.0:3000->3000/tcp, 0.0.0.0:3022->3022/tcp
```

- `k3d-devops-server-0` runs k3s: the Kubernetes API server, the scheduler, the controllers, and the container runtime for your workloads.
- `k3d-devops-serverlb` is a load balancer. It publishes the API (6550) and the ingress (8080) on your machine.
- `k3d-registry.localhost` is the image registry.

The second command lists the containers on the `devops` network.
`harness` and the three k3d containers share it.
Docker gives each container a DNS name on that network, so a pipeline step can reach the cluster as `k3d-devops-serverlb`.

### 2.5 Just enough Kubernetes for today

Day 3 covers Kubernetes in depth.
Today you need six kinds of object, because Terraform will create them:

| Object | What it is |
|---|---|
| Namespace | A named space inside the cluster. You use one per environment. Access rules and quotas apply per namespace. |
| Pod | One or more containers that run together. |
| Deployment | Keeps a given number of identical pods running, and replaces them when they fail or when you change the image. |
| Service | A stable DNS name and address in front of a set of pods. |
| Secret | A small piece of sensitive data, such as a password, that pods can read. |
| PersistentVolumeClaim | A request for disk storage that outlives a pod. |

Look at what the cluster already runs:

```bash
kubectl get namespaces
kubectl get pods --all-namespaces
```

The `kube-system` namespace holds k3s's own components: DNS (CoreDNS), the Traefik ingress controller, the local-path storage provisioner and metrics-server.

## Part 3: Your first Terraform configuration

### 3.1 Tell Terraform where the cluster is

Terraform's Kubernetes provider reads the cluster address and your credentials from a kubeconfig file.
You name that file in the environment variable `KUBE_CONFIG_PATH`.
The first command adds the setting to `~/.bashrc`, so new terminals get it too.
The second command sets it in this terminal.

```bash
grep -q 'KUBE_CONFIG_PATH' ~/.bashrc || echo 'export KUBE_CONFIG_PATH=$HOME/.kube/config' >> ~/.bashrc
export KUBE_CONFIG_PATH=$HOME/.kube/config
echo "$KUBE_CONFIG_PATH"
```

### 3.2 Declare the providers

Terraform itself does not know about Kubernetes, AWS or any other platform.
Plugins called providers do that work.
Each provider translates Terraform resources into API calls for one platform.
This file declares which providers the configuration needs and which versions are acceptable.

Create `~/platform/versions.tf`:

<!-- file: ~/platform/versions.tf -->
```hcl
terraform {
  required_version = ">= 1.17.0"

  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
  }
}

# The provider reads the cluster address and credentials from the kubeconfig
# file named in the KUBE_CONFIG_PATH environment variable.
provider "kubernetes" {}
```

- `required_version` stops older Terraform versions from running this code.
- `source` names the provider in the Terraform Registry.
- `version = "~> 3.4"` accepts 3.4 and later 3.x versions, but not 4.0. A major version can contain breaking changes.
- The `random` provider generates values such as passwords. You use it in Part 5.
- The empty `provider "kubernetes"` block uses the defaults, including `KUBE_CONFIG_PATH`.

### 3.3 Declare the environments

A variable keeps data separate from the resources that use it.
This variable lists the environments and the limits for each.
To add an environment later, you add an entry here. You do not copy resource blocks.

Create `~/platform/variables.tf`:

<!-- file: ~/platform/variables.tf -->
```hcl
variable "environments" {
  description = "Environments to create, with the resource limits of each namespace."
  type = map(object({
    cpu_limit    = string
    memory_limit = string
    max_pods     = number
  }))
  default = {
    dev = {
      cpu_limit    = "4"
      memory_limit = "4Gi"
      max_pods     = 10
    }
    prod = {
      cpu_limit    = "6"
      memory_limit = "6Gi"
      max_pods     = 15
    }
  }
}
```

The `type` says the variable is a map. Each key (`dev`, `prod`) maps to an object with three named fields.
Terraform checks values against this type before it does anything else.

### 3.4 Declare the namespaces

A `resource` block describes one kind of infrastructure object.
The first label is the resource type (`kubernetes_namespace_v1`, from the Kubernetes provider).
The second label (`env`) is a name you use to refer to the resource inside Terraform.

`for_each` creates one instance of the resource for each entry in the map.
Inside the block, `each.key` is the entry's key (`dev` or `prod`) and `each.value` is its object.
Terraform names the instances `kubernetes_namespace_v1.env["dev"]` and `kubernetes_namespace_v1.env["prod"]`.

Create `~/platform/namespaces.tf` with only the namespace for now:

<!-- file: ~/platform/namespaces.tf -->
```hcl
# One namespace per environment: flightops-dev, flightops-prod.
resource "kubernetes_namespace_v1" "env" {
  for_each = var.environments

  metadata {
    name = "flightops-${each.key}"
    labels = {
      "app.kubernetes.io/part-of"    = "flightops"
      "app.kubernetes.io/managed-by" = "terraform"
      environment                    = each.key
    }
  }
}
```

The labels mark these namespaces as part of the flightops application and as managed by Terraform.
Anyone who finds them in the cluster can see where they come from.

### 3.5 Initialize the working directory

`terraform init` prepares a folder for Terraform.
It downloads the providers that `versions.tf` asks for into `.terraform/`.
It records the exact provider versions and their checksums in `.terraform.lock.hcl`.
You commit the lock file to Git, so everyone, including the pipeline, uses the same provider versions.

```bash
cd ~/platform
terraform init
ls -a
grep -E '^provider|^  version' .terraform.lock.hcl
```

```text
Initializing provider plugins...
- Finding hashicorp/kubernetes versions matching "~> 3.4"...
- Finding hashicorp/random versions matching "~> 3.9"...
- Installing hashicorp/kubernetes v3.4.0...
- Installing hashicorp/random v3.9.1...
...
Terraform has been successfully initialized!

.  ..  cluster  .terraform  .terraform.lock.hcl  namespaces.tf  variables.tf  versions.tf

provider "registry.terraform.io/hashicorp/kubernetes" {
  version     = "3.4.0"
provider "registry.terraform.io/hashicorp/random" {
  version     = "3.9.1"
```

### 3.6 Check formatting and validity

`terraform fmt` rewrites files into the standard layout and prints the names of the files it changed.
`terraform validate` checks the configuration for errors, such as a misspelled attribute, without contacting the cluster.

```bash
terraform fmt
terraform validate
```

```text
Success! The configuration is valid.
```

### 3.7 Plan

`terraform plan` compares three things: your configuration, the state (what Terraform created before, nothing yet), and the real cluster.
It prints the actions it would take, and changes nothing.

```bash
terraform plan
```

```text
Terraform will perform the following actions:

  # kubernetes_namespace_v1.env["dev"] will be created
  + resource "kubernetes_namespace_v1" "env" {
      + id = (known after apply)

      + metadata {
          + labels           = {
              + "app.kubernetes.io/managed-by" = "terraform"
              + "app.kubernetes.io/part-of"    = "flightops"
              + "environment"                  = "dev"
            }
          + name             = "flightops-dev"
          ...
        }
    }

  # kubernetes_namespace_v1.env["prod"] will be created
  ...

Plan: 2 to add, 0 to change, 0 to destroy.
```

The symbols mean:

| Symbol | Action |
|---|---|
| `+` | create |
| `~` | change in place |
| `-` | destroy |
| `-/+` | destroy and create again (replace) |

`(known after apply)` marks values that only exist after the object is created, such as the ID that Kubernetes assigns.

### 3.8 Apply

`terraform apply` makes a new plan and then performs the actions in it.
Without `-auto-approve`, it prints the plan and waits for you to type `yes`.
The labs use `-auto-approve` so the commands run without a prompt.
When you work on shared infrastructure, read the plan and answer the prompt yourself.

```bash
terraform apply -auto-approve
kubectl get namespaces -l app.kubernetes.io/part-of=flightops
```

```text
kubernetes_namespace_v1.env["prod"]: Creating...
kubernetes_namespace_v1.env["dev"]: Creating...
kubernetes_namespace_v1.env["dev"]: Creation complete after 0s [id=flightops-dev]
kubernetes_namespace_v1.env["prod"]: Creation complete after 0s [id=flightops-prod]

Apply complete! Resources: 2 added, 0 changed, 0 destroyed.

NAME             STATUS   AGE
flightops-dev    Active   2s
flightops-prod   Active   2s
```

### 3.9 Look at the state

Terraform records every object it creates in a state file, `terraform.tfstate`.
The state maps each resource address in your code to a real object, and stores the object's attributes.
On the next run, Terraform reads the state to know which real objects belong to which resource.

```bash
terraform state list
terraform state show 'kubernetes_namespace_v1.env["dev"]'
ls -l terraform.tfstate
```

```text
kubernetes_namespace_v1.env["dev"]
kubernetes_namespace_v1.env["prod"]

# kubernetes_namespace_v1.env["dev"]:
resource "kubernetes_namespace_v1" "env" {
    id                               = "flightops-dev"
    ...
```

The state is a JSON file on your disk.
It is fine for one person learning Terraform.
Lab 05 moves it to a place that a team and a pipeline can share.

### 3.10 Run the plan again

Run the same plan a second time:

```bash
terraform plan
```

```text
No changes. Your infrastructure matches the configuration.
```

Terraform compared the configuration, the state and the cluster, and found nothing to do.
Running the same configuration again gives the same result and changes nothing.
This property is called idempotency.

<!-- test
cd ~/platform
terraform plan -detailed-exitcode > /dev/null
-->

### 3.11 Compare with an imperative command

`kubectl create` is imperative: it tells the cluster to do one action now.
Create a namespace this way:

```bash
kubectl create namespace demo
```

Run the same command again:

<!-- expect-fail -->
```bash
kubectl create namespace demo
```

```text
Error from server (AlreadyExists): namespaces "demo" already exists
```

The second run fails, because the action "create" cannot happen twice.
A script built from imperative commands must check the current state before each step.
Terraform does that comparison for you, which is why the second `terraform plan` above reported no changes.

Remove the demo namespace:

```bash
kubectl delete namespace demo
```

## Part 4: Resource limits and drift

### 4.1 Add a quota and default limits

A ResourceQuota sets upper limits for a whole namespace: total CPU, total memory and the number of pods.
It stops one environment from using all of the cluster's capacity.

When a namespace has a CPU or memory quota, Kubernetes rejects any pod that does not declare its own CPU and memory limits.
A LimitRange fills in default requests and limits for containers that do not set them.
The two objects are used together.

Replace the content of `~/platform/namespaces.tf` with the full version:

<!-- file: ~/platform/namespaces.tf -->
```hcl
# One namespace per environment: flightops-dev, flightops-prod.
resource "kubernetes_namespace_v1" "env" {
  for_each = var.environments

  metadata {
    name = "flightops-${each.key}"
    labels = {
      "app.kubernetes.io/part-of"    = "flightops"
      "app.kubernetes.io/managed-by" = "terraform"
      environment                    = each.key
    }
  }
}

# Upper limits for everything that runs in the namespace.
resource "kubernetes_resource_quota_v1" "env" {
  for_each = var.environments

  metadata {
    name      = "quota"
    namespace = kubernetes_namespace_v1.env[each.key].metadata[0].name
  }
  spec {
    hard = {
      "limits.cpu"    = each.value.cpu_limit
      "limits.memory" = each.value.memory_limit
      pods            = each.value.max_pods
    }
  }
}

# Default requests and limits for containers that do not set their own.
resource "kubernetes_limit_range_v1" "env" {
  for_each = var.environments

  metadata {
    name      = "defaults"
    namespace = kubernetes_namespace_v1.env[each.key].metadata[0].name
  }
  spec {
    limit {
      type = "Container"
      default = {
        cpu    = "500m"
        memory = "256Mi"
      }
      default_request = {
        cpu    = "100m"
        memory = "128Mi"
      }
    }
  }
}
```

Look at the `namespace` lines.
They do not repeat the text `flightops-dev`.
They refer to the namespace resource: `kubernetes_namespace_v1.env[each.key].metadata[0].name`.
This reference tells Terraform that the quota depends on the namespace.
Terraform builds a dependency graph from such references, and creates the namespace before the quota and the limit range.

`500m` means 500 millicores, half a CPU core. `256Mi` means 256 mebibytes of memory.

### 4.2 Plan and apply

```bash
cd ~/platform
terraform plan
```

The plan adds two quotas and two limit ranges, and leaves the namespaces alone:

```text
Plan: 4 to add, 0 to change, 0 to destroy.
```

```bash
terraform apply -auto-approve
kubectl describe resourcequota quota -n flightops-dev
kubectl describe limitrange defaults -n flightops-dev
```

```text
Name:          quota
Namespace:     flightops-dev
Resource       Used  Hard
--------       ----  ----
limits.cpu     0     4
limits.memory  0     4Gi
pods           0     10
```

### 4.3 Change the quota by hand

Someone fixes a problem late at night and raises the pod limit in dev with kubectl, outside Terraform.
The cluster now differs from the code.
This difference is called drift.

```bash
kubectl -n flightops-dev patch resourcequota quota --type merge -p '{"spec":{"hard":{"pods":"50"}}}'
kubectl -n flightops-dev get resourcequota quota -o jsonpath='{.spec.hard.pods}{"\n"}'
```

```text
resourcequota/quota patched
50
```

### 4.4 Detect and correct the drift

```bash
terraform plan
```

Terraform reads the real quota from the cluster during the plan.
It finds 50, compares it with the configuration (10), and plans to change it back:

```text
  # kubernetes_resource_quota_v1.env["dev"] will be updated in-place
  ~ resource "kubernetes_resource_quota_v1" "env" {
        id = "flightops-dev/quota"

      ~ spec {
          ~ hard = {
              ~ "pods"          = "50" -> "10"
                # (2 unchanged elements hidden)
            }
        }
        # (1 unchanged block hidden)
    }

Plan: 0 to add, 1 to change, 0 to destroy.
```

Apply the plan to bring the cluster back to the code:

```bash
terraform apply -auto-approve
kubectl -n flightops-dev get resourcequota quota -o jsonpath='{.spec.hard.pods}{"\n"}'
```

```text
10
```

<!-- test
test "$(kubectl -n flightops-dev get resourcequota quota -o jsonpath='{.spec.hard.pods}')" = "10"
-->

Repeatedly moving the real system toward the declared state is called convergence.
Terraform only converges when someone runs it.
If nobody runs Terraform after a manual change, the drift stays.
In Lab 05, a pipeline runs Terraform on every change and shows you drift in its plan.

If the manual change was right, the fix is to change the code (the variable) and apply, so that code and cluster agree again.

## Part 5: A database module

### 5.1 Why a module

Each environment needs a PostgreSQL database with five objects: a generated password, a Secret, a storage claim, a Deployment and a Service.
You could write five resources with `for_each` again.
A module groups related resources into one reusable unit with inputs (variables) and outputs.
You write the database once, and call it once per environment.
Teams publish modules so that other teams create infrastructure the same way.
At United, the shared CDK library plays this role for AWS: it packages approved patterns as reusable constructs.

The module goes into its own folder, `modules/postgres`, with four files.

```bash
mkdir -p ~/platform/modules/postgres
```

### 5.2 Write the module

The module's providers. A module declares the providers it uses. The root configuration chooses the versions.

<!-- file: ~/platform/modules/postgres/versions.tf -->
```hcl
terraform {
  required_providers {
    kubernetes = {
      source = "hashicorp/kubernetes"
    }
    random = {
      source = "hashicorp/random"
    }
  }
}
```

The module's inputs. `namespace` has no default, so every caller must set it. `image` and `storage` have defaults that a caller may override.

<!-- file: ~/platform/modules/postgres/variables.tf -->
```hcl
variable "namespace" {
  description = "Namespace to create the database in."
  type        = string
}

variable "image" {
  description = "PostgreSQL container image."
  type        = string
  default     = "postgres:17-alpine"
}

variable "storage" {
  description = "Size of the data volume."
  type        = string
  default     = "1Gi"
}
```

The module's resources. Read the comments while you create the file:

- `random_password` generates a 24-character password and keeps it in the state, so it stays the same on every run.
- The Secret `flight-status-db` holds the database user, password and name, plus a ready-made `DATABASE_URL`. On Day 3, the flight status service reads that URL.
- The PersistentVolumeClaim asks for 1 GiB of disk. k3d's local-path storage creates the volume when the first pod uses it, so Terraform does not wait for it (`wait_until_bound = false`).
- The Deployment runs one PostgreSQL container. It reads its settings from the Secret (`env_from`), and stores data on the volume. The `Recreate` strategy stops the old pod before it starts a new one, because only one pod may write to the volume.
- The readiness probe runs `pg_isready`, so Kubernetes knows when the database accepts connections.
- The Service gives the database the DNS name `postgres` inside its namespace.

<!-- file: ~/platform/modules/postgres/main.tf -->
```hcl
# A single PostgreSQL instance for one environment.
# Terraform generates the password and stores it, with a ready-made
# DATABASE_URL for the application, in the Secret "flight-status-db".

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "kubernetes_secret_v1" "db" {
  metadata {
    name      = "flight-status-db"
    namespace = var.namespace
  }
  data = {
    POSTGRES_USER     = "flights"
    POSTGRES_PASSWORD = random_password.db.result
    POSTGRES_DB       = "flights"
    DATABASE_URL      = "postgresql://flights:${random_password.db.result}@postgres:5432/flights"
  }
}

resource "kubernetes_persistent_volume_claim_v1" "db" {
  metadata {
    name      = "postgres-data"
    namespace = var.namespace
  }
  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = var.storage
      }
    }
  }
  # k3d's local-path storage creates the volume only when a pod uses it.
  wait_until_bound = false
}

resource "kubernetes_deployment_v1" "db" {
  metadata {
    name      = "postgres"
    namespace = var.namespace
    labels = {
      app = "postgres"
    }
  }
  spec {
    replicas = 1
    # Stop the old pod before starting a new one: the volume allows one writer.
    strategy {
      type = "Recreate"
    }
    selector {
      match_labels = {
        app = "postgres"
      }
    }
    template {
      metadata {
        labels = {
          app = "postgres"
        }
      }
      spec {
        container {
          name  = "postgres"
          image = var.image
          # POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB come from the Secret.
          env_from {
            secret_ref {
              name = kubernetes_secret_v1.db.metadata[0].name
            }
          }
          env {
            name  = "PGDATA"
            value = "/var/lib/postgresql/data/pgdata"
          }
          port {
            container_port = 5432
          }
          readiness_probe {
            exec {
              command = ["pg_isready", "-U", "flights"]
            }
            period_seconds = 5
          }
          resources {
            requests = {
              cpu    = "100m"
              memory = "128Mi"
            }
            limits = {
              cpu    = "1"
              memory = "512Mi"
            }
          }
          volume_mount {
            name       = "data"
            mount_path = "/var/lib/postgresql/data"
          }
        }
        volume {
          name = "data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.db.metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_service_v1" "db" {
  metadata {
    name      = "postgres"
    namespace = var.namespace
  }
  spec {
    selector = {
      app = "postgres"
    }
    port {
      port        = 5432
      target_port = 5432
    }
  }
}
```

The module's output. An output passes a value back to the caller. Here it is the name of the Secret.

<!-- file: ~/platform/modules/postgres/outputs.tf -->
```hcl
output "secret_name" {
  description = "Name of the Secret with the connection settings."
  value       = kubernetes_secret_v1.db.metadata[0].name
}
```

### 5.3 Call the module

A `module` block calls the module.
`source` points to the folder.
`for_each` works the same way as on resources: one module instance per environment.
`namespace` passes the input.

Create `~/platform/databases.tf`:

<!-- file: ~/platform/databases.tf -->
```hcl
# One PostgreSQL database per environment, built from the local module.
module "postgres" {
  source   = "./modules/postgres"
  for_each = var.environments

  namespace = kubernetes_namespace_v1.env[each.key].metadata[0].name
}
```

Root outputs print useful values after each apply, and other tools can read them with `terraform output`.

Create `~/platform/outputs.tf`:

<!-- file: ~/platform/outputs.tf -->
```hcl
output "namespaces" {
  description = "Namespaces created for the environments."
  value       = [for ns in kubernetes_namespace_v1.env : ns.metadata[0].name]
}

output "database_secrets" {
  description = "Secret in each namespace that holds the database connection settings."
  value       = { for env, db in module.postgres : env => db.secret_name }
}
```

### 5.4 Initialize the module

Try a plan right away:

<!-- expect-fail -->
```bash
cd ~/platform
terraform plan
```

```text
Error: Module not installed

  on databases.tf line 2:
   2: module "postgres" {

This module is not yet installed. Run "terraform init" to install all modules required by this configuration.
```

Terraform reads modules from its working directory (`.terraform/modules`), not from your source folders.
Every time you add a module or a provider, run `terraform init` again.

```bash
terraform init
```

```text
Initializing modules...
- postgres in modules/postgres
...
Terraform has been successfully initialized!
```

### 5.5 Plan and apply

```bash
terraform plan
```

Look at the resource addresses.
Resources inside a module instance start with the module address, for example `module.postgres["dev"].random_password.db`.

```text
  # module.postgres["dev"].kubernetes_deployment_v1.db will be created
  ...
  # module.postgres["dev"].kubernetes_secret_v1.db will be created
  + resource "kubernetes_secret_v1" "db" {
      + data                           = (sensitive value)
  ...
Plan: 10 to add, 0 to change, 0 to destroy.

Changes to Outputs:
  + database_secrets = {
      + dev  = "flight-status-db"
      + prod = "flight-status-db"
    }
  + namespaces       = [
      + "flightops-dev",
      + "flightops-prod",
    ]
```

Ten resources: five per environment.
Terraform shows the Secret data as `(sensitive value)` in the plan.
It still writes the real values into the state. Lab 06 comes back to this.

```bash
terraform apply -auto-approve
```

The apply takes about a minute.
By default, Terraform waits until each Deployment is ready, so the databases accept connections when the command finishes.

<!-- test
kubectl -n flightops-dev rollout status deployment/postgres --timeout=300s
kubectl -n flightops-prod rollout status deployment/postgres --timeout=300s
-->

### 5.6 Check the databases

```bash
kubectl -n flightops-dev get pods,services,persistentvolumeclaims,secrets
```

```text
NAME                            READY   STATUS    RESTARTS   AGE
pod/postgres-7d945f8596-fx8kj   1/1     Running   0          60s

NAME               TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)    AGE
service/postgres   ClusterIP   10.43.120.17   <none>        5432/TCP   60s

NAME                                  STATUS   VOLUME          CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/postgres-data   Bound    pvc-0b5e...     1Gi        RWO            local-path     60s

NAME                      TYPE     DATA   AGE
secret/flight-status-db   Opaque   4      61s
```

List the keys in the Secret, without the values:

```bash
kubectl -n flightops-dev get secret flight-status-db -o jsonpath='{.data}' | jq 'keys'
```

```text
[
  "DATABASE_URL",
  "POSTGRES_DB",
  "POSTGRES_PASSWORD",
  "POSTGRES_USER"
]
```

Run a query inside the database container to prove that PostgreSQL works:

```bash
kubectl -n flightops-dev exec deploy/postgres -- psql -U flights -d flights -c 'select version();'
```

```text
                                          version
--------------------------------------------------------------------------------------------
 PostgreSQL 17.x on x86_64-pc-linux-musl, compiled by gcc ...
(1 row)
```

Print the outputs:

```bash
terraform output
```

```text
database_secrets = {
  "dev" = "flight-status-db"
  "prod" = "flight-status-db"
}
namespaces = [
  "flightops-dev",
  "flightops-prod",
]
```

Think about the order in which Terraform created these objects.
The Secret needs the password and the namespace.
The Deployment needs the Secret and the storage claim.
You did not write this order anywhere. Terraform derived it from the references in the code (the dependency graph from the lecture).

## Part 6: Put the platform code in Git

Infrastructure code needs the same treatment as application code: version history, review, and a pipeline.
You start with version history.

### 6.1 Create the repository in Harness

In the Harness UI (http://localhost:3000), open the `flightops` project.
Select **Repositories**, then **New Repository**.
Enter the name `platform`. Do not add a README, license or .gitignore, because you push existing files.
Select **Create Repository**.


<!-- shots:begin -->
<img src="img/04-terraform-foundations/01-create_repo-1.png" alt="Create the repository, step 1 of 3">

<img src="img/04-terraform-foundations/01-create_repo-2.png" alt="Create the repository, step 2 of 3">

<img src="img/04-terraform-foundations/01-create_repo-3.png" alt="Create the repository, step 3 of 3">

<!-- shots:end -->

<!-- ui: create_repo flightops platform -->

### 6.2 Keep working files and state out of Git

Three kinds of files must not go into Git:

- `.terraform/` holds downloaded provider binaries. `terraform init` recreates it.
- `terraform.tfstate` holds the state, including the database passwords that `random_password` generated. Anyone who can read the repository could read them.
- `terraform.tfstate.backup` is the previous copy of the state, with the same content.

The lock file `.terraform.lock.hcl` does go into Git.

Create `~/platform/.gitignore`:

<!-- file: ~/platform/.gitignore -->
```text
# Terraform working files and state. The state holds the generated database
# passwords, so it never goes into Git.
.terraform/
*.tfstate
*.tfstate.*
```

### 6.3 Commit and push

```bash
cd ~/platform
git init -b main
git add .
git status --short
```

Check the list before you commit. There must be no `.tfstate` file and nothing under `.terraform/`.

```text
A  .gitignore
A  .terraform.lock.hcl
A  cluster/k3d-devops.yaml
A  databases.tf
A  modules/postgres/main.tf
A  modules/postgres/outputs.tf
A  modules/postgres/variables.tf
A  modules/postgres/versions.tf
A  namespaces.tf
A  outputs.tf
A  variables.tf
A  versions.tf
```

```bash
git commit -m "Platform: k3d cluster, namespaces, quotas and databases"
git remote add origin http://localhost:3000/git/flightops/platform.git
git push -u origin main
```

Git uses the token that the credential helper stored in Lab 01, so it does not ask for a password.

<!-- test
cd ~/platform
test "$(git ls-remote origin refs/heads/main | cut -f1)" = "$(git rev-parse HEAD)"
-->

### 6.4 Look at the repository

In Harness, open **Repositories** > **platform**.
You see the files and your commit.
The state file is not there. It is still on your disk, and only on your disk.
If your lab machine broke now, the code would be safe, but Terraform would no longer know which objects in the cluster it created.
Lab 05 fixes this.

In the Harness platform, Terraform runs inside pipelines: Harness CD has Terraform Plan and Apply steps, and the Infrastructure as Code Management module runs Terraform and stores its state for you.

## Troubleshooting

- **`sha256sum` reports `FAILED` or `did NOT match`**: the download is damaged or incomplete. Delete `k3d-linux-amd64`, download it again, and check again. Do not install a file that fails the check.
- **`k3d registry create` says the registry already exists**: you created it before. Continue with the next step.
- **`k3d cluster create` fails with `port is already allocated`**: another container uses port 6550, 8080 or 5000. Run `docker ps` to find it. If an old `devops` cluster is left over, run `k3d cluster delete devops` and create the cluster again.
- **kubectl says `The connection to the server localhost:8080 was refused`**: kubectl has no current context. Run `kubectl config use-context k3d-devops`.
- **Terraform says `no configuration has been provided` or `cluster unreachable`**: `KUBE_CONFIG_PATH` is not set in this terminal. Run `export KUBE_CONFIG_PATH=$HOME/.kube/config` and try again.
- **`Error: Module not installed` or `Inconsistent dependency lock file`**: run `terraform init` after you add a module or a provider.
- **The postgres pod stays `Pending`**: the storage provisioner may still be starting. Check `kubectl -n kube-system get pods` and `kubectl -n flightops-dev describe pod -l app=postgres`. The events at the end of the output name the cause.
- **`git remote add` says `remote origin already exists`**: you ran the block twice. Run `git remote set-url origin http://localhost:3000/git/flightops/platform.git` and push again.

<!-- runner: stop -->

## Going further (optional)

- **Explore with the console.** Run `terraform console` in `~/platform` and evaluate expressions such as `var.environments["prod"].max_pods`, `keys(var.environments)` and `module.postgres["dev"].secret_name`. Type `exit` to leave.
- **Draw the dependency graph.** Install Graphviz (`sudo apt-get install -y graphviz`), then run `terraform graph | dot -Tsvg > graph.svg` and open `graph.svg` in the browser. Find the arrows from the Deployment to the Secret and to the storage claim.
- **Add and remove an environment.** Add a `staging` entry to `variables.tf` with smaller limits. Run `terraform plan`: it adds a namespace, a quota, a limit range and a database. Apply it, then remove the entry and apply again. Terraform destroys everything it created for staging. Do not commit this change.
- **Find the volume on the node.** The local-path provisioner stores volumes in the k3s container: `docker exec k3d-devops-server-0 ls /var/lib/rancher/k3s/storage`.

## Summary

- You installed k3d, kubectl and Terraform with pinned versions, and checked a download against its published checksum.
- You created a Kubernetes cluster from a declarative file, on the same Docker network as Harness.
- You wrote Terraform with a variable, `for_each`, references between resources and a module, and you saw Terraform derive the creation order from those references (the dependency graph).
- You saw idempotency (a second plan changes nothing) and convergence (Terraform reverted a manual change).
- You put the platform code in Git, with the lock file and without the state file. The state is still only on your machine. Lab 05 moves it.
