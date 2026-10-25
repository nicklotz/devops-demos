# Lab 06: Managing credentials

Your lab machine now holds several credentials: a Git token, the Harness admin password, a cluster-admin token, database passwords.
In this lab you find where each of them is stored and who can read it.
You use a Harness secret in a pipeline, and see what happens when a step prints it.
You give the delivery pipeline of Day 3 its own identity with the smallest set of permissions it needs.
You turn on secret scanning so a pushed key is rejected, and you rotate a credential.

**Lecture:** L8 Credential management · **You need:** Lab 05 completed (or run `~/devops-demos/scripts/catch-up.sh 06` on a fresh machine)

## Goals

- Find credentials on a developer machine, in Kubernetes and in Terraform state, and name who can read each one.
- Use a Harness secret in a pipeline step without writing it to the log.
- Create a least-privilege ServiceAccount for deployments, and check its permissions.
- Block a pushed secret with server-side secret scanning.
- Rotate a token and update the secret that the pipeline uses.

## Before you start

Check that the platform pipeline from Lab 05 applied its change, and that both repositories are up to date.

```bash
export KUBE_CONFIG_PATH=$HOME/.kube/config
cd ~/platform && git switch main && git pull
kubectl -n terraform get secret tfstate-default-platform
kubectl -n flightops-dev get resourcequota quota -o jsonpath='{.spec.hard.pods}{"\n"}'
cd ~/flight-status && git switch main && git pull
git log --oneline -1
```

```text
NAME                       TYPE     DATA   AGE
tfstate-default-platform   Opaque   1      1h
12
2b7d9e1 Add departures board (#1)
```

## Part 1: Find the credentials on your machine

An attacker who gets access to one machine looks for credentials first, because credentials open other systems.
You do the same search on your lab machine.
For each place, note who can read it and what a better practice would be.

### 1.1 The Git credential store

In Lab 01 you set `credential.helper store`.
Git saved your Harness token the first time you pushed.

```bash
ls -l ~/.git-credentials
cat ~/.git-credentials
```

```text
-rw------- 1 student student 72 Oct 27 11:02 /home/student/.git-credentials
http://admin:eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...@localhost:3000
```

The file is in plain text.
Its mode, `-rw-------`, keeps other users out, but every program that runs as you can read it.
That includes any script you run and any package you install with an install script.

Better practice: a credential helper that uses the operating system's encrypted keyring (Git Credential Manager, or the macOS Keychain), and tokens with short lifetimes.
You keep the `store` helper for the rest of this course, because later labs push without a prompt.

### 1.2 The Harness container's environment

In Lab 01 you started Harness with the admin password as an environment variable.
Docker keeps the environment of every container.

```bash
docker inspect harness --format '{{range .Config.Env}}{{println .}}{{end}}' | grep GITNESS_
```

```text
GITNESS_URL_CONTAINER=http://harness:3000
GITNESS_CI_CONTAINER_NETWORKS=devops
GITNESS_PRINCIPAL_ADMIN_EMAIL=admin@example.com
GITNESS_PRINCIPAL_ADMIN_PASSWORD=Harness-Lab-2026
GITNESS_METRIC_ENABLED=false
```

Anyone who can run `docker inspect` can read the password.
Membership of the `docker` group gives the same power as root on the machine, so this is a short list of people, but still more than needed.

Better practice: pass secrets to containers as files (Docker secrets, or Kubernetes Secrets mounted as volumes), not as command-line arguments, and change a bootstrap password at the first sign-in.

### 1.3 Secrets in the Harness database

In Lab 05 you stored the Terraform kubeconfig as the Harness secret `platform_kubeconfig`.
Harness Open Source 3.3.0 keeps secrets unencrypted in its database file, inside the `harness-data` volume (Lab 01, step 4.2).
Docker stores volumes under `/var/lib/docker/volumes`, which only root can read.
`grep -a` searches a binary file as if it were text.

```bash
sudo grep -a -o 'server: https://k3d-devops-serverlb:6443' /var/lib/docker/volumes/harness-data/_data/database.sqlite | head -1
```

```text
server: https://k3d-devops-serverlb:6443
```

That line comes from the stored kubeconfig. The ServiceAccount token is stored right next to it.
Anyone with root access to this machine, or with a copy of the volume or of a backup, can read every secret in Harness.

Better practice: encrypt secrets at rest with a key that is kept somewhere else, ideally in a key management service, or keep them in an external secrets manager.
The Harness platform encrypts secrets in its built-in secret manager with a key management service, and it can read secrets from external stores such as HashiCorp Vault or AWS Secrets Manager.
United's enterprise secrets store is TSS.

<!-- test
sudo grep -a -q 'k3d-devops-serverlb' /var/lib/docker/volumes/harness-data/_data/database.sqlite
-->

### 1.4 The shell history

Bash writes every command you type to `~/.bash_history` when the terminal closes.
The `docker run` command from Lab 01 included the password.

<!-- skip -->
```bash
grep -c GITNESS_PRINCIPAL_ADMIN_PASSWORD ~/.bash_history
```

If the count is 1 or more, the password is in the history file.
Better practice: never type a secret as a command-line argument. Read it from a file, or let the program prompt for it.

### 1.5 A Kubernetes Secret

The database password for dev is in the Secret that Terraform created in Lab 04.

```bash
kubectl -n flightops-dev get secret flight-status-db -o yaml
```

```text
apiVersion: v1
data:
  DATABASE_URL: cG9zdGdyZXNxbDovL2ZsaWdodHM6...
  POSTGRES_DB: ZmxpZ2h0cw==
  POSTGRES_PASSWORD: aE4ycVR4...
  POSTGRES_USER: ZmxpZ2h0cw==
kind: Secret
...
```

The values look scrambled, but they are only base64-encoded.
Base64 is an encoding for binary data. It has no key, and anyone can reverse it:

```bash
kubectl -n flightops-dev get secret flight-status-db -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d; echo
kubectl auth can-i get secrets -n flightops-dev
```

```text
hN2qTx8mWkRb5LcP0vYs3JdA
yes
```

What protects a Secret is access control.
Anyone allowed to `get secrets` in the namespace can read every value.
You are the cluster administrator, so the answer is `yes`.

At rest, k3s stores Secrets in its datastore without encryption, unless you turn on its secrets encryption.
Amazon EKS encrypts Secrets at rest with AWS KMS keys (envelope encryption).

### 1.6 The Terraform state

Terraform showed the database passwords as `(sensitive value)` in the plan.
The state still contains them.
`terraform state pull` downloads the state from the backend and prints it.

```bash
cd ~/platform
terraform state pull | jq -r '.resources[] | select(.type == "random_password") | "\(.module): \(.instances[0].attributes.result)"'
kubectl auth can-i get secrets -n terraform --as=system:serviceaccount:terraform:terraform
```

```text
module.postgres["dev"]: hN2qTx8mWkRb5LcP0vYs3JdA
module.postgres["prod"]: Zb7RkLq2Vx9PnW4sTd8YcHmE
yes
```

The dev password is the same value you decoded in step 1.4.
Anyone who can read the state Secret in the `terraform` namespace can read every password that Terraform generated.
That includes the pipeline's `terraform` ServiceAccount, and anyone who holds the `platform_kubeconfig` secret.

Better practice: treat the state as a secret.
Limit who can read the backend, encrypt it (for example an S3 bucket with KMS encryption), and keep generated passwords out of the state where the provider allows it.
Newer Terraform versions can keep some values out of the state (ephemeral values and write-only arguments), when the provider supports them.

### 1.7 What you found

| Where | Who can read it | Better practice |
|---|---|---|
| `~/.git-credentials` | Every program running as you | Keyring-backed credential helper, short-lived tokens |
| `docker inspect harness` | Everyone in the `docker` group | Secrets as files, change bootstrap passwords |
| Harness database file | root, and anyone with a copy of the volume | Encryption at rest with a key in a KMS, or an external secrets manager |
| `~/.bash_history` | You, and programs running as you | No secrets on command lines |
| Kubernetes Secret | Everyone allowed to `get secrets` in the namespace | Tight RBAC, encryption at rest |
| Terraform state | Everyone who can read the backend | Restrict and encrypt the backend, keep secrets out of state |

## Part 2: Secrets in a pipeline

The flight status team wants a pipeline step that calls a partner API.
The API needs a key, and the key must not be in the repository.

### 2.1 Create a Harness secret

In the Harness UI, open the `flightops` project and select **Secrets** > **New Secret**.
Enter the name `demo_api_key` and the value `fs-demo-7Q2x9LmP4kV8`.
Select **Create Secret**.

<!-- ui: create_secret flightops demo_api_key fs-demo-7Q2x9LmP4kV8 -->

### 2.2 Use the secret in a step

Work on a branch. `main` is protected, and this change is an experiment.

```bash
cd ~/flight-status
git switch main && git pull
git switch -c feature/secret-demo
```

Replace `~/flight-status/.harness/ci.yaml` with this version.
It is the Lab 03 pipeline plus one new step at the end, `callapi`.
The step receives the secret as the environment variable `API_KEY`, and prints it.

<!-- file: ~/flight-status/.harness/ci.yaml -->
```yaml
# Continuous integration for flight-status (Lab 03).
# Adds a PostgreSQL service for the integration tests and a coverage threshold.
kind: pipeline
spec:
  stages:
  - name: build
    type: ci
    spec:
      steps:
      - name: db
        type: background
        spec:
          container: postgres:17-alpine
          envs:
            POSTGRES_USER: flights
            POSTGRES_PASSWORD: flights
            POSTGRES_DB: flights
      - name: install
        type: run
        spec:
          container: python:3.12-slim
          script: |
            python -m venv .venv
            . .venv/bin/activate
            pip install --quiet -r requirements-dev.txt
      - name: lint
        type: run
        spec:
          container: python:3.12-slim
          script: |
            . .venv/bin/activate
            ruff check .
            ruff format --check .
      - name: test
        type: run
        spec:
          container: python:3.12-slim
          envs:
            DATABASE_URL: postgresql://flights:flights@db:5432/flights
          script: |
            . .venv/bin/activate
            pytest --cov=flightstatus --cov-report=term-missing --cov-fail-under=90
      # Lab 06 demonstration: this step prints a secret. Never do this in a real pipeline.
      - name: callapi
        type: run
        spec:
          container: alpine:3.20
          envs:
            API_KEY: ${{ secrets.get("demo_api_key") }}
          script: |
            echo "Calling the partner API with key $API_KEY"
```

Compare the database password in the `db` and `test` steps with the API key.
The database password is written in the YAML, and that is acceptable here: the database exists only for the length of one pipeline run, and it holds only test data.
The API key gives access to a real system, so it comes from a Harness secret.

### 2.3 Run it through a pull request

```bash
git add .harness/ci.yaml
git commit -m "Call the partner API"
git push -u origin feature/secret-demo
```

Open a pull request from `feature/secret-demo` to `main` with the title `Call the partner API`, as in Lab 03.

<!-- ui: open_pr flightops/flight-status feature/secret-demo main "Call the partner API" -->

<!-- test
h_wait flightops/flight-status ci success
h_log flightops/flight-status ci callapi | grep -q 'fs-demo-7Q2x9LmP4kV8'
-->

### 2.4 Read the log

When the run finishes, open it and select the `callapi` step.

<!-- ui: view_execution flightops/flight-status ci -->

```text
+ echo "Calling the partner API with key $API_KEY"
Calling the partner API with key fs-demo-7Q2x9LmP4kV8
```

The key is in the log, in plain text.
Everyone who can see this pipeline's runs can now read it.

Harness Open Source 3.3.0 does not mask secret values in logs.
The Harness platform does: it replaces known secret values with asterisks in step output.
Masking is a useful backup, but it has limits:

- It only finds the value in the exact form it was stored. If a script prints the value encoded in base64, or in parts, the masking does not recognize it.
- The step already has the value. A script can send it anywhere, for example to a web address in a pull request from someone else.
- Logs are often copied to other systems, such as log search tools, where the masking rules do not apply.

Never print a secret. Treat masking as a second line of defence.

There is a second way to use a secret, and it is worse.
If you write `${{ secrets.get("demo_api_key") }}` inside `script:`, Harness puts the value into the script text before the step starts.
The `+` trace line in the log then shows the value, even if the command itself never prints it.
Pass secrets through `envs`, as above.

### 2.5 Fix the step

Change the step so that it uses the key without printing it.
It checks that the key is set, and prints only its length.

<!-- file: ~/flight-status/.harness/ci.yaml -->
```yaml
# Continuous integration for flight-status (Lab 03).
# Adds a PostgreSQL service for the integration tests and a coverage threshold.
kind: pipeline
spec:
  stages:
  - name: build
    type: ci
    spec:
      steps:
      - name: db
        type: background
        spec:
          container: postgres:17-alpine
          envs:
            POSTGRES_USER: flights
            POSTGRES_PASSWORD: flights
            POSTGRES_DB: flights
      - name: install
        type: run
        spec:
          container: python:3.12-slim
          script: |
            python -m venv .venv
            . .venv/bin/activate
            pip install --quiet -r requirements-dev.txt
      - name: lint
        type: run
        spec:
          container: python:3.12-slim
          script: |
            . .venv/bin/activate
            ruff check .
            ruff format --check .
      - name: test
        type: run
        spec:
          container: python:3.12-slim
          envs:
            DATABASE_URL: postgresql://flights:flights@db:5432/flights
          script: |
            . .venv/bin/activate
            pytest --cov=flightstatus --cov-report=term-missing --cov-fail-under=90
      # Lab 06 demonstration, fixed: the step uses the secret without printing it.
      - name: callapi
        type: run
        spec:
          container: alpine:3.20
          envs:
            API_KEY: ${{ secrets.get("demo_api_key") }}
          script: |
            if [ -z "$API_KEY" ]; then
              echo "API_KEY is empty"
              exit 1
            fi
            echo "Calling the partner API. The key has ${#API_KEY} characters."
```

```bash
git commit -am "Do not print the API key"
git push
```

<!-- test
h_wait flightops/flight-status ci success
if h_log flightops/flight-status ci callapi | grep -q 'fs-demo-7Q2x9LmP4kV8'; then echo "the key is still in the log"; exit 1; fi
h_log flightops/flight-status ci callapi | grep -q 'characters'
-->

Open the new run and read the `callapi` log:

```text
Calling the partner API. The key has 20 characters.
```

The push started two runs: one for the push to the branch, and one because the branch belongs to an open pull request.
Both show the same result.

### 2.6 Close the pull request

This change was a demonstration, so you do not merge it.
On the pull request page, select **Close pull request**.

<!-- ui: close_pr flightops/flight-status -->

Delete the branch on your machine and in Harness:

```bash
git switch main
git branch -D feature/secret-demo
git push origin --delete feature/secret-demo
```

The first run's log still contains the key.
In real work, a secret that appeared in a log counts as exposed.
You would rotate it (create a new key and revoke the old one) even after you fix the pipeline.

## Part 3: A least-privilege identity for deployments

On Day 3, the delivery pipeline deploys the flight status service to dev and prod.
It needs a credential for each environment.
The `terraform` ServiceAccount from Lab 05 would work, but it is cluster-admin: a leak would expose the whole cluster.
Least privilege means giving each identity only the permissions its task needs.

### 3.1 What the deployer needs

The pipeline applies the application's Deployment, Service, Ingress and ConfigMap, watches the rollout, reads pod logs and events when something fails, and rolls back.
It does not need to read Secrets, create namespaces, change permissions, or touch another environment.

Kubernetes role-based access control (RBAC) has three parts:

- A **ServiceAccount** is the identity.
- A **Role** lists allowed actions (verbs) on kinds of objects (resources) in one namespace.
- A **RoleBinding** gives the Role to the identity.

The Role for the deployer:

| API group | Resources | Verbs | Why |
|---|---|---|---|
| `apps` | deployments | get, list, watch, create, update, patch | Apply the Deployment, watch the rollout, roll back |
| `apps` | replicasets | get, list, watch | Rollout status and rollback read the ReplicaSets |
| core (`""`) | services, configmaps | get, list, watch, create, update, patch | Apply the Service and the generated ConfigMap |
| `networking.k8s.io` | ingresses | get, list, watch, create, update, patch | Apply the Ingress |
| core (`""`) | pods, pods/log, events | get, list, watch | Diagnose failed rollouts |

There is no `delete` verb, and no rule for `secrets`.
The Deployment refers to the database Secret by name. Kubernetes reads it when it starts the pod, so the deployer never needs to read it.

### 3.2 Add the deployer on a branch

The platform code changes through a pull request, as in Lab 05.

```bash
cd ~/platform
git switch main && git pull
git switch -c deployers
```

Create `~/platform/deployers.tf`.
It uses `for_each` over the same environments, so dev and prod each get their own ServiceAccount, Role, RoleBinding and token.
A dev credential cannot change prod.
The variable `deployer_token_versions` becomes part of the token Secret's name, `deployer-token-v1`. You use it in Part 5 to rotate the token.

<!-- file: ~/platform/deployers.tf -->
```hcl
# A ServiceAccount per environment for the delivery pipeline (Lab 06).
# Its Role allows changes to the application's objects in one namespace only.

# Increase an environment's number to rotate its deployer token, for example dev = 2.
# A long-lived ServiceAccount token depends only on the ServiceAccount and on the
# name of its Secret. A new token therefore needs a Secret with a new name.
variable "deployer_token_versions" {
  description = "Version of each environment's deployer token. Increase it to rotate the token."
  type        = map(number)
  default = {
    dev  = 1
    prod = 1
  }
}

resource "kubernetes_service_account_v1" "deployer" {
  for_each = var.environments

  metadata {
    name      = "deployer"
    namespace = kubernetes_namespace_v1.env[each.key].metadata[0].name
  }
}

resource "kubernetes_role_v1" "deployer" {
  for_each = var.environments

  metadata {
    name      = "deployer"
    namespace = kubernetes_namespace_v1.env[each.key].metadata[0].name
  }
  rule {
    api_groups = ["apps"]
    resources  = ["deployments"]
    verbs      = ["get", "list", "watch", "create", "update", "patch"]
  }
  rule {
    api_groups = ["apps"]
    resources  = ["replicasets"]
    verbs      = ["get", "list", "watch"]
  }
  rule {
    api_groups = [""]
    resources  = ["services", "configmaps"]
    verbs      = ["get", "list", "watch", "create", "update", "patch"]
  }
  rule {
    api_groups = ["networking.k8s.io"]
    resources  = ["ingresses"]
    verbs      = ["get", "list", "watch", "create", "update", "patch"]
  }
  rule {
    api_groups = [""]
    resources  = ["pods", "pods/log", "events"]
    verbs      = ["get", "list", "watch"]
  }
}

resource "kubernetes_role_binding_v1" "deployer" {
  for_each = var.environments

  metadata {
    name      = "deployer"
    namespace = kubernetes_namespace_v1.env[each.key].metadata[0].name
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.deployer[each.key].metadata[0].name
  }
  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account_v1.deployer[each.key].metadata[0].name
    namespace = kubernetes_namespace_v1.env[each.key].metadata[0].name
  }
}

# A long-lived token for the ServiceAccount, stored in a Secret named
# deployer-token-v<version>. Kubernetes writes the token into the Secret.
resource "kubernetes_secret_v1" "deployer_token" {
  for_each = var.environments

  metadata {
    name      = "deployer-token-v${var.deployer_token_versions[each.key]}"
    namespace = kubernetes_namespace_v1.env[each.key].metadata[0].name
    labels = {
      "app.kubernetes.io/component" = "deployer-token"
    }
    annotations = {
      "kubernetes.io/service-account.name" = kubernetes_service_account_v1.deployer[each.key].metadata[0].name
    }
  }
  type                           = "kubernetes.io/service-account-token"
  wait_for_service_account_token = true
}
```

Check it on your machine first:

```bash
terraform fmt -check
terraform validate
terraform plan
```

```text
Plan: 8 to add, 0 to change, 0 to destroy.
```

Eight resources: four kinds, two environments.

### 3.3 Pull request, plan and merge

```bash
git add deployers.tf
git commit -m "Add deployer service accounts"
git push -u origin deployers
```

Open a pull request in the `platform` repository from `deployers` to `main`, titled `Add deployer service accounts`.

<!-- ui: open_pr flightops/platform deployers main "Add deployer service accounts" -->

<!-- test
h_wait_pr_check flightops/platform infra success
h_log flightops/platform infra plan | grep -q '8 to add'
-->

Read the plan in the `infra` check.
Check that it only adds objects, and that each Role has the rules from the table.
Then select **Squash and merge**.

<!-- ui: merge_pr flightops/platform -->

The merge runs the pipeline on `main`, and the `apply` step creates the objects.

<!-- test
h_wait flightops/platform infra success --branch main
h_log flightops/platform infra apply | grep -q '8 added'
-->

Update your copy:

```bash
git switch main
git pull
git branch -D deployers
```

### 3.4 Check the permissions

`kubectl auth can-i` with `--as` asks the API server what another identity may do.
The loop runs four checks for the dev deployer and prints yes or no for each.

```bash
SA=system:serviceaccount:flightops-dev:deployer
for check in "create deployments -n flightops-dev" "create deployments -n flightops-prod" "get secrets -n flightops-dev" "delete namespaces"; do
  if kubectl auth can-i $check --as=$SA > /dev/null 2>&1; then answer=yes; else answer=no; fi
  echo "$check: $answer"
done
```

```text
create deployments -n flightops-dev: yes
create deployments -n flightops-prod: no
get secrets -n flightops-dev: no
delete namespaces: no
```

<!-- test
SA=system:serviceaccount:flightops-dev:deployer
test "$(kubectl auth can-i create deployments -n flightops-dev --as=$SA)" = yes
test "$(kubectl auth can-i create deployments -n flightops-prod --as=$SA)" = no
test "$(kubectl auth can-i get secrets -n flightops-dev --as=$SA)" = no
-->

### 3.5 Write kubeconfig files for the deployers

You need two kubeconfig files, one per environment, and you need to write the dev file again in Part 5.
A small script avoids typing the same steps three times.
It finds the environment's token Secret by its label, `app.kubernetes.io/component=deployer-token`, reads the token and the CA certificate from it, and writes `~/deployer-<env>.kubeconfig` with the server address that pipeline steps use.
`umask 077` makes the new file readable only by you.

Create `~/make-deployer-kubeconfig.sh`:

<!-- file: ~/make-deployer-kubeconfig.sh -->
```sh
#!/usr/bin/env bash
# Write ~/deployer-<env>.kubeconfig for the deployer ServiceAccount of one environment.
# Usage: ~/make-deployer-kubeconfig.sh dev
set -euo pipefail
ENV="$1"
NS="flightops-$ENV"
SECRET=$(kubectl -n "$NS" get secret -l app.kubernetes.io/component=deployer-token -o jsonpath='{.items[0].metadata.name}')
TOKEN=$(kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.token}' | base64 -d)
CA=$(kubectl -n "$NS" get secret "$SECRET" -o jsonpath='{.data.ca\.crt}')
OUT="$HOME/deployer-$ENV.kubeconfig"
umask 077
cat > "$OUT" <<EOF
apiVersion: v1
kind: Config
clusters:
- name: devops
  cluster:
    server: https://k3d-devops-serverlb:6443
    certificate-authority-data: $CA
users:
- name: deployer
  user:
    token: $TOKEN
contexts:
- name: deployer
  context:
    cluster: devops
    user: deployer
    namespace: $NS
current-context: deployer
EOF
echo "Wrote $OUT from the Secret $SECRET"
```

The context sets the namespace, so kubectl commands in the pipeline work in the right environment without `-n`.

```bash
chmod +x ~/make-deployer-kubeconfig.sh
~/make-deployer-kubeconfig.sh dev
~/make-deployer-kubeconfig.sh prod
ls -l ~/deployer-*.kubeconfig
```

```text
Wrote /home/student/deployer-dev.kubeconfig from the Secret deployer-token-v1
Wrote /home/student/deployer-prod.kubeconfig from the Secret deployer-token-v1
-rw------- 1 student student 1740 Oct 28 14:20 /home/student/deployer-dev.kubeconfig
-rw------- 1 student student 1742 Oct 28 14:20 /home/student/deployer-prod.kubeconfig
```

### 3.6 Test the dev deployer

From your machine, use the published API port instead of the pipeline's server name, as in Lab 05.

```bash
kubectl --kubeconfig ~/deployer-dev.kubeconfig --server https://0.0.0.0:6550 auth whoami
kubectl --kubeconfig ~/deployer-dev.kubeconfig --server https://0.0.0.0:6550 get deployments,pods
```

```text
Username   system:serviceaccount:flightops-dev:deployer
...
NAME                       READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/postgres   1/1     1            1           3h
...
```

Now try to read the Secrets with the same credential:

<!-- expect-fail -->
```bash
kubectl --kubeconfig ~/deployer-dev.kubeconfig --server https://0.0.0.0:6550 get secrets
```

```text
Error from server (Forbidden): secrets is forbidden: User "system:serviceaccount:flightops-dev:deployer" cannot list resource "secrets" in API group "" in the namespace "flightops-dev"
```

The API server refuses, and names the identity, the verb, the resource and the namespace.
This message is the first thing to read when a pipeline step fails with `Forbidden`.

### 3.7 Store the kubeconfigs in Harness

Create two secrets in the `flightops` project, as in Lab 05.
Open each file in VS Code to copy its content:

<!-- skip -->
```bash
code ~/deployer-dev.kubeconfig ~/deployer-prod.kubeconfig
```

- Name `dev_kubeconfig`, value: the content of `~/deployer-dev.kubeconfig`.
- Name `prod_kubeconfig`, value: the content of `~/deployer-prod.kubeconfig`.

<!-- ui: create_secret flightops dev_kubeconfig @~/deployer-dev.kubeconfig -->
<!-- ui: create_secret flightops prod_kubeconfig @~/deployer-prod.kubeconfig -->

The Lab 09 pipeline uses these two secrets.
In the Harness platform, each environment would have its own Kubernetes connector with its own credential.

## Part 4: Secret scanning

Access control protects a secret after it is stored.
Secret scanning stops a secret from being stored in Git in the first place.

### 4.1 Turn it on

In the Harness UI, open **Repositories** > **flight-status** > **Settings** > **Security**.
Turn on **Secret scanning** and save.

<!-- ui: enable_secret_scanning flightops/flight-status -->

From now on, Harness checks every push to this repository for patterns that look like credentials, and rejects the push if it finds one.

### 4.2 Try to push an AWS key

A developer adds AWS credentials to a configuration file by mistake.
The values below are the example keys from the AWS documentation. They do not work, but they have the same format as real keys.

```bash
cd ~/flight-status
git switch -c feature/aws-config
```

Create `~/flight-status/config.ini` with the two example keys. The `printf` commands join each value from two parts. The only reason is that this lab file is itself stored on GitHub, and GitHub scans it for keys too. The file on your machine contains the complete values.

```bash
printf 'aws_access_key_id = %s%s\n' 'AKIAIOSFODNN7' 'EXAMPLE' > config.ini
printf 'aws_secret_access_key = %s%s\n' 'wJalrXUtnFEMI/K7MDENG' '/bPxRfiCYEXAMPLEKEY' >> config.ini
cat config.ini
```

```bash
git add config.ini
git commit -m "Add AWS configuration"
```

The commit works: it only changes your local repository.
The push sends it to Harness:

<!-- expect-fail -->
```bash
git push -u origin feature/aws-config
```

```text
remote: Push contains secret:
remote:
remote:   aws-access-token in config.ini:1
remote:       Secret:       AKIAIOSF... (the full key ID)
remote:       Commit:       5c1d0e8...
remote:       Details:      Identified a pattern that may indicate AWS credentials, risking unauthorized cloud resource access and data breaches on AWS platforms.
...
 ! [remote rejected] feature/aws-config -> feature/aws-config (pre-receive hook declined)
```

Harness rejected the push. The key is not in the repository on the server.

### 4.3 Clean up

The commit exists only on your machine. Delete the branch:

```bash
git switch main
git branch -D feature/aws-config
```

If a real key reaches a shared repository, removing the commit is not enough.
Others may have pulled it already, and the history may be copied elsewhere.
Treat the key as exposed and rotate it.

### 4.4 Scanning before the push

Server-side scanning (push protection) catches every push, whatever the developer's setup.
Many teams also scan on the developer's machine with a pre-commit hook, using a tool such as gitleaks.
The hook stops the commit before the secret is in any Git history, even a local one.
The two checks complement each other. The hook gives the fastest feedback. The server check cannot be skipped.

## Part 5: Rotate a credential

Rotation replaces a credential with a new one and revokes the old one.
It limits how long a leaked credential stays useful.
You rotate after a suspected leak, when a person with access leaves the team, and on a regular schedule.

### 5.1 Keep a copy of the current kubeconfig

Keep the current dev kubeconfig, so you can show that the old token stops working.
Check that it works now:

```bash
cp ~/deployer-dev.kubeconfig ~/deployer-dev.old.kubeconfig
kubectl --kubeconfig ~/deployer-dev.old.kubeconfig --server https://0.0.0.0:6550 get deployments
```

```text
NAME       READY   UP-TO-DATE   AVAILABLE   AGE
postgres   1/1     1            1           3h
```

### 5.2 Why the token needs a new Secret name

A token Secret holds a JSON Web Token (JWT). The middle part of a JWT is a set of claims in base64. Decode the claims of the dev token:

```bash
kubectl -n flightops-dev get secret -l app.kubernetes.io/component=deployer-token -o jsonpath='{.items[0].data.token}' | base64 -d \
  | python3 -c "import base64, json, sys; p = sys.stdin.read().split('.')[1]; print(json.dumps(json.loads(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4))), indent=2))"
```

```text
{
  "iss": "kubernetes/serviceaccount",
  "kubernetes.io/serviceaccount/namespace": "flightops-dev",
  "kubernetes.io/serviceaccount/secret.name": "deployer-token-v1",
  "kubernetes.io/serviceaccount/service-account.name": "deployer",
  "kubernetes.io/serviceaccount/service-account.uid": "b0881137-...",
  "sub": "system:serviceaccount:flightops-dev:deployer"
}
```

The claims contain no time and no random value: no issue time, no expiry, no unique ID. Kubernetes signs them with the cluster's private key, and that signature is the same every time for the same claims. If you delete the Secret and create a new one with the same name, Kubernetes writes exactly the same token into it, and the old copies keep working.

To get a new token, the Secret needs a new name. That is the job of the variable `deployer_token_versions` in `deployers.tf`: the version number is part of the name.

### 5.3 Rotate through a pull request

A rotation is a change to the platform, so it goes through the same review and pipeline as any other change. Change the dev version from 1 to 2:

```bash
cd ~/platform
git switch main && git pull
git switch -c rotate-dev-token
sed -i 's/^    dev  = 1$/    dev  = 2/' deployers.tf
git diff
```

```text
   default = {
-    dev  = 1
+    dev  = 2
     prod = 1
   }
```

```bash
git commit -am "Rotate the dev deployer token"
git push -u origin rotate-dev-token
```

Open a pull request from `rotate-dev-token` to `main` with the title `Rotate the dev deployer token`.

<!-- ui: open_pr flightops/platform rotate-dev-token main "Rotate the dev deployer token" -->

<!-- test
h_wait_pr_check flightops/platform infra success
h_log flightops/platform infra plan | grep -q '1 to add, 0 to change, 1 to destroy'
-->

Read the plan in the pull request's `infra` run:

```text
  # kubernetes_secret_v1.deployer_token["dev"] must be replaced
-/+ resource "kubernetes_secret_v1" "deployer_token" {
      ~ metadata {
          ~ name = "deployer-token-v1" -> "deployer-token-v2" # forces replacement
...
Plan: 1 to add, 0 to change, 1 to destroy.
```

A new name cannot be changed in place, so Terraform deletes `deployer-token-v1` and creates `deployer-token-v2`. Only the dev token changes. Merge the pull request.

<!-- ui: merge_pr flightops/platform -->

<!-- test
h_wait flightops/platform infra success --branch main
-->

```bash
git switch main && git pull
kubectl -n flightops-dev get secrets -l app.kubernetes.io/component=deployer-token
```

```text
NAME                TYPE                                  DATA   AGE
deployer-token-v2   kubernetes.io/service-account-token   3      20s
```

### 5.4 The old credential stops working

<!-- test
for i in $(seq 1 30); do
  if ! kubectl --kubeconfig ~/deployer-dev.old.kubeconfig --server https://0.0.0.0:6550 get deployments > /dev/null 2>&1; then exit 0; fi
  sleep 1
done
echo "the old token is still accepted after 30 seconds"
exit 1
-->

<!-- expect-fail -->
```bash
kubectl --kubeconfig ~/deployer-dev.old.kubeconfig --server https://0.0.0.0:6550 get deployments
```

```text
error: You must be logged in to the server (Unauthorized)
```

The API server accepts a long-lived token only while the Secret named in its claims exists. `deployer-token-v1` is gone, so the old token is revoked.
Right now the `dev_kubeconfig` secret in Harness still holds that old token, so a dev deployment would fail.
Rotation is only finished when every consumer has the new value.

### 5.5 Write and test the new kubeconfig

```bash
~/make-deployer-kubeconfig.sh dev
kubectl --kubeconfig ~/deployer-dev.kubeconfig --server https://0.0.0.0:6550 get deployments
rm -f ~/deployer-dev.old.kubeconfig
```

```text
Wrote /home/student/deployer-dev.kubeconfig from the Secret deployer-token-v2
NAME       READY   UP-TO-DATE   AVAILABLE   AGE
postgres   1/1     1            1           3h
```

### 5.6 Update the Harness secret

In the Harness UI, open **Secrets** > `dev_kubeconfig`, edit it, paste the content of the new `~/deployer-dev.kubeconfig` as the value, and save.

<!-- ui: update_secret flightops dev_kubeconfig @~/deployer-dev.kubeconfig -->

The pipeline reads the secret at the start of each run, so the next run uses the new token.
You did not change any pipeline YAML.

### 5.7 Rotation with an enterprise secrets store

You rotated in four steps: create a new token, revoke the old one, update the stored copy, check.
An enterprise secrets store automates these steps.
AWS Secrets Manager, for example, can rotate a secret on a schedule with a rotation function.
At United, the enterprise secrets store is TSS.
The pattern is the same: the pipeline refers to the secret by name and reads the current value at run time, so a rotation needs no pipeline change.
The Harness platform can read secrets from an external secrets manager at run time instead of keeping its own copy, which removes step 5.6.

Short-lived credentials go one step further.
Instead of a token that stays valid until someone rotates it, each pipeline run gets a credential that expires after minutes.
AWS IAM roles issue such credentials, and Kubernetes can issue time-limited ServiceAccount tokens (see Going further).

## Troubleshooting

- **`kubectl auth can-i` prints `no` where you expected `yes`**: the deployer objects do not exist yet. Check the `infra` run on `main` after the merge, and run `kubectl -n flightops-dev get serviceaccount,role,rolebinding`.
- **`make-deployer-kubeconfig.sh` fails with `array index out of bounds`**: no Secret with the label `app.kubernetes.io/component=deployer-token` exists yet. Same cause: the pipeline has not applied `deployers.tf`.
- **kubectl with a deployer kubeconfig says `lookup k3d-devops-serverlb ... no such host`**: on your machine, add `--server https://0.0.0.0:6550`. The file's own address works only from pipeline steps.
- **The `callapi` step prints `API_KEY is empty`**: the secret name in the YAML does not match the secret in Harness. Both must be `demo_api_key`.
- **The push of `config.ini` was not rejected**: secret scanning is not on. Check **Settings** > **Security** of the `flight-status` repository, then delete the branch on the server with `git push origin --delete feature/aws-config`.
- **`git push origin --delete feature/secret-demo` says the remote ref does not exist**: the branch is already gone. Continue.
- **The rotation plan shows more than one change**: the branch contains other changes, or `main` moved. Compare with `git diff main`, and keep the pull request to the one-line version change.
- **The old token still works after the merge**: check that the `infra` run on `main` applied the change, and that `kubectl -n flightops-dev get secrets -l app.kubernetes.io/component=deployer-token` shows `deployer-token-v2` only.

<!-- runner: stop -->

## Going further (optional)

- **A short-lived token.** Ask Kubernetes for a token that expires after 10 minutes, and read its expiry time:

  ```text
  TOKEN=$(kubectl -n flightops-dev create token deployer --duration=10m)
  echo "$TOKEN" | jq -R 'split(".")[1] | gsub("-"; "+") | gsub("_"; "/") | @base64d | fromjson | {sub, expires: (.exp | todate)}'
  ```

  Nothing stores this token. When it expires, it is useless to anyone who copied it.
- **Scan on your machine.** Download the gitleaks binary from its GitHub releases page, check its checksum as you did for k3d in Lab 04, and run `gitleaks git ~/flight-status` to scan the full history.
- **Scan the platform repository.** Turn on secret scanning for `platform` as well, and think about which secrets could end up in Terraform code.
- **A memory-only credential helper.** In a scratch repository, set `git config credential.helper 'cache --timeout=900'`. Git then keeps the token in memory for 15 minutes instead of writing it to disk.

## Summary

- You found credentials in five places on one machine, and named who can read each one (threat model).
- You used a Harness secret in a pipeline step through an environment variable, saw it leak into the log when printed, and changed the step so it no longer prints it. Masking is a backup for this rule.
- You gave each environment a deployer identity whose Role allows only the actions a deployment needs (least privilege), and checked it with `kubectl auth can-i`.
- You turned on secret scanning, and Harness rejected a push that contained an AWS key.
- You rotated the dev deployer token, saw the old token rejected, and updated the pipeline's secret (rotation and revocation).
