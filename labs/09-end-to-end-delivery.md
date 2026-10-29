# Lab 09: End-to-end delivery pipeline

In this lab you turn the `ci` pipeline into a delivery pipeline. Every run lints and tests the code, builds the container image and scans it. Runs for changes merged to `main` also deploy the image to dev, check the deployment with a smoke test, and roll back automatically if either step fails. A second pipeline, `promote`, deploys the same image to production when you create a release tag. Then you merge a bad change on purpose and watch the pipeline protect dev. This lab uses what you built on all three days and puts lecture L12 into practice.

**Lecture:** L12 Continuous delivery · **You need:** Lab 08 (or: run `~/devops-demos/scripts/catch-up.sh 09` on a fresh machine)

## Goals

- Build, scan and publish an image in a pipeline, tagged with the commit it was built from.
- Deploy to dev from a pipeline with a least-privilege credential, verify the rollout and run a smoke test.
- Roll back automatically when a deployment fails.
- Promote the same image to production with a release tag.
- Map each step to the Harness platform and to the DORA metrics.

## Before you start

You need the manifests from Lab 08 on `main`, dev running version 1.1.0, and the production database from Lab 04. The pipeline also uses the Harness secrets `dev_kubeconfig` and `prod_kubeconfig` from Lab 06. You can see them in Harness under the `flightops` project, in **Secrets**.

```bash
cd ~/flight-status
git switch main
git pull
ls k8s/base k8s/dev
curl -s http://flights-dev.localhost:8080/version; echo
kubectl -n flightops-prod get deployment postgres
```

You should see output like this:

```text
deployment.yaml  ingress.yaml  kustomization.yaml  service.yaml
kustomization.yaml
{"version":"1.1.0","commit":"3c1f0a9e...","environment":"dev"}
NAME       READY   UP-TO-DATE   AVAILABLE   AGE
postgres   1/1     1            1           2d
```

## Part 1: Extend the pipeline

### 1.1 Create a branch

```bash
cd ~/flight-status
git switch -c feature/delivery
```

### 1.2 The plan for the pipeline

Your `.harness/ci.yaml` from Lab 03 has four steps. You add five more. The table shows when each step runs.

| Step | What it does | Runs for |
|---|---|---|
| `db`, `install`, `lint`, `test` | As in Lab 03 | Every run |
| `image` | Builds the image and pushes it, tagged with the commit SHA | Every run |
| `scan` | Scans the image with Trivy and fails on fixable critical vulnerabilities | Every run |
| `deploy` | Deploys the new image to dev and waits for the rollout | Pushes to `main` |
| `smoke` | Calls the service through the ingress and checks the version | Pushes to `main` |
| `rollback` | Rolls dev back if this run deployed and a step failed | After a failure |

Pull requests build and scan the image, so a change that breaks the image fails before anyone merges it. Only merged code reaches an environment. Because the branch rule from Lab 03 blocks direct pushes, every push to `main` is a merged pull request.

In the next steps you add the new steps one at a time. Open `.harness/ci.yaml` in VS Code. Add each step at the end of the `steps` list, after the step from the previous section. Each `- name:` line starts with six spaces, like the existing steps. Before you paste, put the cursor at the very start of a new, empty line, with no spaces in front of it. Otherwise VS Code adds its own indentation to the first pasted line. In step 1.8 you compare your file with the complete version. If the indentation goes wrong, replace the whole file with that version.

### 1.3 Build and push the image

```yaml
      - name: image
        type: plugin
        spec:
          name: docker
          inputs:
            registry: k3d-registry.localhost:5000
            repo: k3d-registry.localhost:5000/flight-status
            insecure: true
            # Plugin inputs are strings. Separate several values with commas.
            tags: ${{ build.commit }}
            build_args: APP_VERSION=1.0.${{ build.number }},GIT_COMMIT=${{ build.commit }}
```

A plugin step runs a prebuilt container image that does one job. The `docker` plugin starts its own Docker engine inside the step container, builds the image from your Dockerfile, and pushes it.

- `registry` and `repo` name the registry and the image. `insecure: true` allows the plain HTTP registry, as `insecure-registries` did for your own Docker engine in Lab 01.
- `tags: ${{ build.commit }}` tags the image with the full commit SHA. Each image is linked to one commit, and no later build overwrites it. This is the "build once" half of "build once, promote the same artifact".
- `build_args` sets the version to `1.0.<build number>` and records the commit. These are the same build arguments you passed by hand in Lab 07.
- Harness passes plugin inputs to the plugin as environment variables. They must be strings. A YAML list (`- value` on separate lines) is ignored, and the plugin then pushes only the tag `latest`. Several values are separated by commas.

In the Harness platform, the "Build and Push to Docker Registry" step does this job, with a connector that holds the registry credentials (Amazon ECR at United).

### 1.4 Scan the image

```yaml
      - name: scan
        type: run
        spec:
          container: aquasec/trivy:0.75.0
          script: |
            trivy image --insecure --no-progress --skip-version-check --severity CRITICAL --ignore-unfixed --exit-code 1 \
              k3d-registry.localhost:5000/flight-status:${{ build.commit }}
```

This is the check you ran by hand in Lab 07, step 5.2, with the same Trivy version.

- The step scans the image in the registry by its commit tag, the exact image the next steps deploy.
- `--severity CRITICAL --ignore-unfixed --exit-code 1` is the release rule: fail only on critical vulnerabilities that have a fix.
- `--insecure` allows the plain HTTP registry.
- `--no-progress` and `--skip-version-check` keep the log short.

In the Harness platform, Security Testing Orchestration (STO) runs scanners such as Aqua Trivy as pipeline steps and collects their findings.

### 1.5 Deploy to dev

```yaml
      - name: deploy
        type: run
        when: build.event == "push" and build.target == "main"
        spec:
          container: alpine/k8s:1.35.9
          envs:
            KUBECONFIG_CONTENT: ${{ secrets.get("dev_kubeconfig") }}
          script: |
            printf '%s\n' "$KUBECONFIG_CONTENT" > /tmp/kubeconfig
            export KUBECONFIG=/tmp/kubeconfig
            touch .deploy-started
            cd k8s/dev
            kustomize edit set image flight-status=k3d-registry.localhost:5000/flight-status:${{ build.commit }}
            kubectl apply -k .
            kubectl rollout status deployment/flight-status --timeout=120s
```

- `when` limits the step to pushes to `main`. A pull request run skips it.
- `KUBECONFIG_CONTENT` comes from the Harness secret `dev_kubeconfig`. That kubeconfig belongs to the `deployer` ServiceAccount from Lab 06. It can change the application's objects in `flightops-dev` and nothing else. The script writes it to `/tmp` inside the step container. The file disappears with the container when the step ends. The script never prints it.
- `touch .deploy-started` leaves a marker file in the shared workspace. The `rollback` step uses it to tell whether this run changed the deployment.
- `kustomize edit set image` writes the new image into `k8s/dev/kustomization.yaml` inside the pipeline's workspace. Git still says `1.1.0`. The pipeline's change is not committed.
- `kubectl apply -k .` sends the manifests to the cluster, as you did by hand in Lab 08.
- `kubectl rollout status` waits until the new pods are ready. If they do not become ready, the progress deadline of 90 seconds from Lab 08 ends the wait, and the step fails. This is the first verification.

In the Harness platform, a Deploy stage does this job. The Service names the manifests and the artifact, the Environment is dev, and the Infrastructure Definition names the cluster connector and the namespace. A delegate inside United's network runs the deployment. The Rolling Deployment step applies the manifests and waits for the rollout.

### 1.6 Smoke test

```yaml
      - name: smoke
        type: run
        when: build.event == "push" and build.target == "main"
        spec:
          container: alpine/k8s:1.35.9
          script: |
            for attempt in $(seq 1 15); do
              if curl -fsS -H "Host: flights-dev.localhost" http://k3d-devops-serverlb/version > version.json \
                && jq -e '.version == "1.0.${{ build.number }}"' version.json; then
                exit 0
              fi
              sleep 2
            done
            cat version.json
            exit 1
```

`rollout status` proves that the pods are ready. The smoke test proves that users reach the new version through the same path they use: the load balancer, the ingress and the Service.

- The step calls `/version` and checks that the version equals this build's version, `1.0.<build number>`.
- It tries for up to 30 seconds, because old pods can still answer for a moment after the rollout ends.
- The URL is `http://k3d-devops-serverlb` with the header `Host: flights-dev.localhost`. Inside a container, curl sends every name that ends in `.localhost` to the container itself. The load balancer container's name does not end in `.localhost`, and the Host header tells Traefik which Ingress rule to use.

In the Harness platform, an HTTP step or a Verify step (Continuous Verification) does this job. A Verify step can also compare metrics and logs of the new version with the old one.

### 1.7 Roll back on failure

```yaml
      - name: rollback
        type: run
        when: failure()
        spec:
          container: alpine/k8s:1.35.9
          envs:
            KUBECONFIG_CONTENT: ${{ secrets.get("dev_kubeconfig") }}
          script: |
            if [ ! -f .deploy-started ]; then
              echo "This run did not deploy anything. Nothing to roll back."
              exit 0
            fi
            printf '%s\n' "$KUBECONFIG_CONTENT" > /tmp/kubeconfig
            export KUBECONFIG=/tmp/kubeconfig
            kubectl rollout undo deployment/flight-status
            kubectl rollout status deployment/flight-status --timeout=120s
```

- `when: failure()` runs the step only if an earlier step failed. After a failure, Harness skips all other remaining steps.
- The marker check matters. If a test fails, the run never deployed anything, and dev still runs a healthy version. Without the check, `rollout undo` would replace that healthy version with an older one.
- `kubectl rollout undo` is the command you used by hand in Lab 08.

In the Harness platform, a failure strategy with the action "Rollback" does this job. The Kubernetes rolling deployment comes with matching rollback steps.

### 1.8 Compare with the complete file

Your `.harness/ci.yaml` should now look like this file. Also replace the comment at the top, which still describes Lab 03. If something differs, copy the missing lines from here.

<!-- file: ~/flight-status/.harness/ci.yaml -->
```yaml
# Continuous integration and delivery for flight-status (Lab 09).
# Every run: lint, test, build the image and scan it.
# Pushes to main (merged pull requests) also deploy to dev and run a smoke test.
# If the deployment or the smoke test fails, the rollback step restores the
# previous version in dev.
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
      - name: image
        type: plugin
        spec:
          name: docker
          inputs:
            registry: k3d-registry.localhost:5000
            repo: k3d-registry.localhost:5000/flight-status
            insecure: true
            # Plugin inputs are strings. Separate several values with commas.
            tags: ${{ build.commit }}
            build_args: APP_VERSION=1.0.${{ build.number }},GIT_COMMIT=${{ build.commit }}
      - name: scan
        type: run
        spec:
          container: aquasec/trivy:0.75.0
          script: |
            trivy image --insecure --no-progress --skip-version-check --severity CRITICAL --ignore-unfixed --exit-code 1 \
              k3d-registry.localhost:5000/flight-status:${{ build.commit }}
      - name: deploy
        type: run
        when: build.event == "push" and build.target == "main"
        spec:
          container: alpine/k8s:1.35.9
          envs:
            KUBECONFIG_CONTENT: ${{ secrets.get("dev_kubeconfig") }}
          script: |
            printf '%s\n' "$KUBECONFIG_CONTENT" > /tmp/kubeconfig
            export KUBECONFIG=/tmp/kubeconfig
            touch .deploy-started
            cd k8s/dev
            kustomize edit set image flight-status=k3d-registry.localhost:5000/flight-status:${{ build.commit }}
            kubectl apply -k .
            kubectl rollout status deployment/flight-status --timeout=120s
      - name: smoke
        type: run
        when: build.event == "push" and build.target == "main"
        spec:
          container: alpine/k8s:1.35.9
          script: |
            for attempt in $(seq 1 15); do
              if curl -fsS -H "Host: flights-dev.localhost" http://k3d-devops-serverlb/version > version.json \
                && jq -e '.version == "1.0.${{ build.number }}"' version.json; then
                exit 0
              fi
              sleep 2
            done
            cat version.json
            exit 1
      - name: rollback
        type: run
        when: failure()
        spec:
          container: alpine/k8s:1.35.9
          envs:
            KUBECONFIG_CONTENT: ${{ secrets.get("dev_kubeconfig") }}
          script: |
            if [ ! -f .deploy-started ]; then
              echo "This run did not deploy anything. Nothing to roll back."
              exit 0
            fi
            printf '%s\n' "$KUBECONFIG_CONTENT" > /tmp/kubeconfig
            export KUBECONFIG=/tmp/kubeconfig
            kubectl rollout undo deployment/flight-status
            kubectl rollout status deployment/flight-status --timeout=120s
```

List the step names to check the indentation. A step indented wrongly does not appear in the list.

```bash
grep -E '^      - name:' .harness/ci.yaml
```

You should see nine steps:

```text
      - name: db
      - name: install
      - name: lint
      - name: test
      - name: image
      - name: scan
      - name: deploy
      - name: smoke
      - name: rollback
```

<!-- test
test "$(grep -cE '^      - name:' .harness/ci.yaml)" = "9"
-->

## Part 2: The production overlay and the promotion pipeline

### 2.1 The production overlay

Production uses the same base manifests as dev. Only the overlay differs:

- The namespace is `flightops-prod`.
- There are 3 replicas instead of 2.
- `APP_ENV` is `production`. In production, the service refuses to start without a `DATABASE_URL`. This guard stops a misconfigured release from running with in-memory storage.
- The host is `flights.localhost`.

Because both environments share one base, dev tests the same manifests that production runs.

```bash
mkdir -p k8s/prod
```

Create `~/flight-status/k8s/prod/kustomization.yaml` with this content.

<!-- file: ~/flight-status/k8s/prod/kustomization.yaml -->
```yaml
# The prod environment: namespace flightops-prod, http://flights.localhost:8080
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: flightops-prod
resources:
  - ../base
replicas:
  - name: flight-status
    count: 3
configMapGenerator:
  - name: flight-status-config
    literals:
      - APP_ENV=production
images:
  - name: flight-status
    newName: k3d-registry.localhost:5000/flight-status
    newTag: "1.0.0"
patches:
  - target:
      kind: Ingress
      name: flight-status
    patch: |-
      - op: replace
        path: /spec/rules/0/host
        value: flights.localhost
```

Render the overlay and check the values that differ from dev.

```bash
kubectl kustomize k8s/prod | grep -E 'APP_ENV|namespace:|replicas:|image:|host:'
```

You should see:

```text
  APP_ENV: production
  namespace: flightops-prod
  namespace: flightops-prod
  namespace: flightops-prod
  namespace: flightops-prod
  replicas: 3
        image: k3d-registry.localhost:5000/flight-status:1.0.0
  - host: flights.localhost
```

The tag `1.0.0` in the file is only a starting value. The promotion pipeline replaces it with the image of the release it deploys.

### 2.2 The promotion pipeline

Promotion means deploying to the next environment a version that has already passed the earlier stages. The `promote` pipeline runs when someone creates a tag. It does not build anything. It deploys the image that the `ci` pipeline built and scanned when the tagged commit was merged to `main`.

| Step | What it does |
|---|---|
| `check` | Asks the registry whether an image tagged with the tagged commit's SHA exists. If not, the commit was never built on `main`, and the pipeline stops. The step uses `wget`, because curl inside a container sends every `*.localhost` name to 127.0.0.1. |
| `deploy` | Deploys that image to `flightops-prod` with the `prod_kubeconfig` secret and waits for the rollout. |
| `smoke` | Checks through the production ingress that the service reports the tagged commit. |
| `rollback` | Rolls production back if this run deployed and a step failed. |

Every step except `rollback` also checks `when: build.event == "tag"`. In step 4.1 you configure the pipeline so that only tags start it. The condition is a second safeguard: if someone adds a trigger by mistake, the pipeline still cannot deploy to production from a pull request.

Create `~/flight-status/.harness/promote.yaml` with this content.

<!-- file: ~/flight-status/.harness/promote.yaml -->
```yaml
# Promote a release to production (Lab 09).
# Runs when a tag is created. It deploys the image that the ci pipeline
# built and scanned for the tagged commit. Nothing is rebuilt.
kind: pipeline
spec:
  stages:
  - name: promote
    type: ci
    spec:
      steps:
      - name: check
        type: run
        when: build.event == "tag"
        spec:
          container: alpine/k8s:1.35.9
          script: |
            echo "Promoting commit ${{ build.commit }} (${{ build.ref }})"
            # wget, because curl sends every *.localhost name to 127.0.0.1.
            wget -q -O /dev/null \
              --header "Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json" \
              http://k3d-registry.localhost:5000/v2/flight-status/manifests/${{ build.commit }}
            echo "Image found: k3d-registry.localhost:5000/flight-status:${{ build.commit }}"
      - name: deploy
        type: run
        when: build.event == "tag"
        spec:
          container: alpine/k8s:1.35.9
          envs:
            KUBECONFIG_CONTENT: ${{ secrets.get("prod_kubeconfig") }}
          script: |
            printf '%s\n' "$KUBECONFIG_CONTENT" > /tmp/kubeconfig
            export KUBECONFIG=/tmp/kubeconfig
            touch .deploy-started
            cd k8s/prod
            kustomize edit set image flight-status=k3d-registry.localhost:5000/flight-status:${{ build.commit }}
            kubectl apply -k .
            kubectl rollout status deployment/flight-status --timeout=120s
      - name: smoke
        type: run
        when: build.event == "tag"
        spec:
          container: alpine/k8s:1.35.9
          script: |
            for attempt in $(seq 1 15); do
              if curl -fsS -H "Host: flights.localhost" http://k3d-devops-serverlb/version > version.json \
                && jq -e '.commit == "${{ build.commit }}"' version.json; then
                exit 0
              fi
              sleep 2
            done
            cat version.json
            exit 1
      - name: rollback
        type: run
        when: failure()
        spec:
          container: alpine/k8s:1.35.9
          envs:
            KUBECONFIG_CONTENT: ${{ secrets.get("prod_kubeconfig") }}
          script: |
            if [ ! -f .deploy-started ]; then
              echo "This run did not deploy anything. Nothing to roll back."
              exit 0
            fi
            printf '%s\n' "$KUBECONFIG_CONTENT" > /tmp/kubeconfig
            export KUBECONFIG=/tmp/kubeconfig
            kubectl rollout undo deployment/flight-status
            kubectl rollout status deployment/flight-status --timeout=120s
```

## Part 3: The pull request and the first delivery to dev

### 3.1 Commit and push

```bash
cd ~/flight-status
git add .harness k8s/prod
git status --short
git commit -m "Deliver to dev on merge and promote to prod with a tag"
git push -u origin feature/delivery
```

`git status --short` should show:

```text
M  .harness/ci.yaml
A  .harness/promote.yaml
A  k8s/prod/kustomization.yaml
```

### 3.2 Open the pull request

In Harness, open the **flight-status** repository and select **Pull Requests**, then **New Pull Request**. Choose `main` as the target branch and `feature/delivery` as the source branch. Enter the title `Add delivery and promotion` and create the pull request.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/01-open_pr-1.png" alt="Open the pull request, step 1 of 2">

<img src="img/09-end-to-end-delivery/01-open_pr-2.png" alt="Open the pull request, step 2 of 2">

<!-- shots:end -->

<!-- ui: open_pr flightops/flight-status feature/delivery main "Add delivery and promotion" -->

Harness reads the pipeline YAML from the commit it builds. The pull request run therefore already uses your new `ci.yaml`. A pull request can change its own pipeline. The branch rule and the review protect what reaches `main`.

<!-- test
h_wait_pr_check flightops/flight-status ci success
-->

### 3.3 Read the pull request run

Open **Pipelines**, select `ci`, and open the latest execution.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/02-view_execution-1.png" alt="Open the pipeline run">

<!-- shots:end -->

<!-- ui: view_execution flightops/flight-status ci -->

Check these points in the run:

- `image` built and pushed the image. Near the end of its log, a line ends with `digest: sha256:...`. The text before `digest:` is the commit SHA, which is the tag.
- `scan` passed. The log shows the scan result table for the image.
- `deploy` and `smoke` show as skipped, because the event was `pull_request`.
- `rollback` shows as skipped, because no step failed.

This run took longer than the Lab 03 runs, mostly because of the image build. The build starts from an empty cache in each run, because the plugin's Docker engine is new each time.

<!-- test
h_log flightops/flight-status ci image | grep -q "digest: sha256"
-->

### 3.4 Merge and watch the first delivery

Merge the pull request with **Squash and merge** and delete the source branch when Harness offers it.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/03-merge_pr-1.png" alt="Merge the pull request, step 1 of 2">

<img src="img/09-end-to-end-delivery/03-merge_pr-2.png" alt="Merge the pull request, step 2 of 2">

<!-- shots:end -->

<!-- ui: merge_pr flightops/flight-status -->

The merge is a push to `main`. The `ci` pipeline runs again, and this time it deploys. Open the new execution and follow it until the end. The `deploy` log shows the rollout, and the `smoke` log ends with `true`.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/04-view_execution-1.png" alt="Open the pipeline run">

<!-- shots:end -->

<!-- ui: view_execution flightops/flight-status ci -->

<!-- test
h_wait flightops/flight-status ci success --branch main
-->

### 3.5 Check dev

```bash
git switch main
git pull
git branch -D feature/delivery
curl -s http://flights-dev.localhost:8080/version; echo
git rev-parse HEAD
kubectl -n flightops-dev get deployment flight-status -o jsonpath='{.spec.template.spec.containers[0].image}'; echo
```

You should see:

```text
{"version":"1.0.14","commit":"9f2c4e1b...","environment":"dev"}
9f2c4e1b...
k3d-registry.localhost:5000/flight-status:9f2c4e1b...
```

The build number in your version differs. Check that three values agree: the commit in `/version`, the commit at the top of `main`, and the image tag in the cluster. You can trace the running code in dev to one commit and to the pipeline run that built it.

This image was built from the merge commit on `main`, not from the pull request's commit. The pull request image tested the change. The `main` image is the release candidate that dev runs and that production receives later.

<!-- test
dev_commit=$(h_get http://flights-dev.localhost:8080/version | jq -r .commit)
h_eq "$dev_commit" "$(git rev-parse HEAD)" "dev runs the commit at the top of main"
-->

## Part 4: Create the promotion pipeline

### 4.1 Create the pipeline and its trigger

In Harness, in the **flight-status** repository, select **Pipelines**, then **New Pipeline**. Enter the name `promote`, keep the branch `main`, and set the YAML path to `.harness/promote.yaml`. Create the pipeline.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/05-create_pipeline-1.png" alt="Create the pipeline, step 1 of 4">

<img src="img/09-end-to-end-delivery/05-create_pipeline-2.png" alt="Create the pipeline, step 2 of 4">

<img src="img/09-end-to-end-delivery/05-create_pipeline-3.png" alt="Create the pipeline, step 3 of 4">

<img src="img/09-end-to-end-delivery/05-create_pipeline-4.png" alt="Create the pipeline, step 4 of 4">

<!-- shots:end -->

<!-- ui: create_pipeline flightops/flight-status promote .harness/promote.yaml -->

A new pipeline gets a default trigger for pull request events. A pull request must never deploy to production, so disable it. Open the `promote` pipeline's settings, select the **Triggers** tab, and switch off the trigger named `default`.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/06-disable_trigger-1.png" alt="Turn off the default trigger, step 1 of 5">

<img src="img/09-end-to-end-delivery/06-disable_trigger-2.png" alt="Turn off the default trigger, step 2 of 5">

<img src="img/09-end-to-end-delivery/06-disable_trigger-3.png" alt="Turn off the default trigger, step 3 of 5">

<img src="img/09-end-to-end-delivery/06-disable_trigger-4.png" alt="Turn off the default trigger, step 4 of 5">

<img src="img/09-end-to-end-delivery/06-disable_trigger-5.png" alt="Turn off the default trigger, step 5 of 5">

<!-- shots:end -->

<!-- ui: disable_trigger flightops/flight-status promote default -->

Add the trigger that starts a release. In the **Triggers** tab, create a new trigger named `release`, select the event **Tag created**, and save it.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/07-add_trigger-1.png" alt="Add the trigger, step 1 of 6">

<img src="img/09-end-to-end-delivery/07-add_trigger-2.png" alt="Add the trigger, step 2 of 6">

<img src="img/09-end-to-end-delivery/07-add_trigger-3.png" alt="Add the trigger, step 3 of 6">

<img src="img/09-end-to-end-delivery/07-add_trigger-4.png" alt="Add the trigger, step 4 of 6">

<img src="img/09-end-to-end-delivery/07-add_trigger-5.png" alt="Add the trigger, step 5 of 6">

<img src="img/09-end-to-end-delivery/07-add_trigger-6.png" alt="Add the trigger, step 6 of 6">

<!-- shots:end -->

<!-- ui: add_trigger flightops/flight-status promote release tag_created -->

### 4.2 Why a tag

Creating a tag is a deliberate action by a person. That person decides that a version is ready for production. This makes the tag the approval step of this delivery process. Harness Open Source can restrict who may create tags with tag rules, for example for the pattern `v*`. The Harness platform uses an Approval stage instead: a manual approval, or an approval in Jira or ServiceNow, before the production Deploy stage.

Continuous delivery means every change on `main` could go to production at any time, and a person decides when. Continuous deployment means every change on `main` goes to production automatically. This pipeline does continuous delivery to production and continuous deployment to dev.

## Part 5: Release version 1.0 to production

### 5.1 Create and push the tag

A tag is a name for a commit. You tag the commit at the top of `main`, which is the commit dev runs.

```bash
cd ~/flight-status
git tag v1.0.0
git push origin v1.0.0
```

Open **Pipelines**, select `promote`, and follow the execution that the tag started. The `check` step prints `Image found`. The `deploy` step rolls out three pods. The `smoke` step checks the commit.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/08-view_execution-1.png" alt="Open the pipeline run">

<!-- shots:end -->

<!-- ui: view_execution flightops/flight-status promote -->

<!-- test
h_wait flightops/flight-status promote success
-->

### 5.2 Compare dev and production

```bash
curl -s http://flights.localhost:8080/version; echo
curl -s http://flights-dev.localhost:8080/version; echo
kubectl -n flightops-prod get deployment flight-status
```

You should see:

```text
{"version":"1.0.14","commit":"9f2c4e1b...","environment":"production"}
{"version":"1.0.14","commit":"9f2c4e1b...","environment":"dev"}
NAME            READY   UP-TO-DATE   AVAILABLE   AGE
flight-status   3/3     3            3           40s
```

Dev and production run the same version and the same commit. Only the environment differs. Production received the same image that was built once, scanned once and tested in dev.

<!-- test
prod_commit=$(h_get http://flights.localhost:8080/version | jq -r .commit)
dev_commit=$(h_get http://flights-dev.localhost:8080/version | jq -r .commit)
h_eq "$prod_commit" "$dev_commit" "prod and dev run the same commit"
h_eq "$prod_commit" "$(git rev-list -n 1 v1.0.0)" "prod runs the commit of tag v1.0.0"
test "$(kubectl -n flightops-prod get deployment flight-status -o jsonpath='{.status.readyReplicas}')" = "3"
-->

Open http://flights.localhost:8080 in the browser. The page shows `environment production`.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/09-browse-1.png" alt="The page in the browser">

<!-- shots:end -->

<!-- ui: browse http://flights.localhost:8080 -->

## Part 6: A bad release and the automatic rollback

### 6.1 Make a change that passes every test

A developer renames the readiness probe path in the Deployment to `/readyz`, a name that some frameworks use. The service still answers on `/ready`. The unit, API and integration tests do not read the Kubernetes manifests, so they all pass.

```bash
cd ~/flight-status
git switch -c feature/readiness-rename
sed -i 's|path: /ready$|path: /readyz|' k8s/base/deployment.yaml
git diff
git commit -am "Use /readyz for the readiness probe"
git push -u origin feature/readiness-rename
```

`git diff` shows one changed line:

```text
-              path: /ready
+              path: /readyz
```

### 6.2 Merge the change

In Harness, open a pull request from `feature/readiness-rename` to `main` with the title `Use /readyz for the readiness probe`.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/10-open_pr-1.png" alt="Open the pull request, step 1 of 2">

<img src="img/09-end-to-end-delivery/10-open_pr-2.png" alt="Open the pull request, step 2 of 2">

<!-- shots:end -->

<!-- ui: open_pr flightops/flight-status feature/readiness-rename main "Use /readyz for the readiness probe" -->

The `ci` check passes. The pull request run lints, tests, builds and scans, and none of these steps notices the problem.

<!-- test
h_wait_pr_check flightops/flight-status ci success
-->

Merge the pull request with **Squash and merge**.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/11-merge_pr-1.png" alt="Merge the pull request, step 1 of 2">

<img src="img/09-end-to-end-delivery/11-merge_pr-2.png" alt="Merge the pull request, step 2 of 2">

<!-- shots:end -->

<!-- ui: merge_pr flightops/flight-status -->

<!-- test
h_wait flightops/flight-status ci failure --branch main
-->

### 6.3 Watch the pipeline protect dev

Open the latest `ci` execution for `main`.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/12-view_execution-1.png" alt="Open the pipeline run">

<!-- shots:end -->

<!-- ui: view_execution flightops/flight-status ci -->

The run takes about two minutes longer than before. In the steps, look for this sequence:

- `deploy` waits for the rollout for about 90 seconds and fails with `error: deployment "flight-status" exceeded its progress deadline`. The new pod never became ready, because Kubernetes asked `/readyz`, and the service answered 404.
- `smoke` is skipped, because a step before it failed.
- `rollback` runs, finds the `.deploy-started` marker, and ends with `deployment "flight-status" successfully rolled out`.

The pipeline shows as failed. That is the correct result: the change did not reach dev, and the run tells everyone that `main` contains a broken change.

<!-- test
h_log flightops/flight-status ci deploy | grep -q "exceeded its progress deadline"
h_log flightops/flight-status ci rollback | grep -q "rolled back"
-->

### 6.4 Check dev

```bash
git switch main
git pull
git branch -D feature/readiness-rename
curl -s http://flights-dev.localhost:8080/version; echo
git rev-list -n 1 v1.0.0
kubectl -n flightops-dev get pods -l app=flight-status
kubectl -n flightops-dev rollout history deployment/flight-status
```

Dev still runs the commit of `v1.0.0`, with two ready pods. The rollout history has one more revision: the failed one, followed by the rollback.

Users of dev never received an error. During the failed rollout, `maxUnavailable: 0` kept both old pods serving, and the new pod never received traffic because it never became ready. The rollback then removed the new pod and restored the previous pod template.

The tests did not catch this problem because no test runs the manifests against the application. Teams close this gap in several ways:

- A test that reads the probe paths from `k8s/base/deployment.yaml` and checks that the application serves them. A test like this checks the agreement between the code and the deployment configuration.
- A temporary environment for each pull request, where the pipeline deploys and smoke-tests the change before the merge.
- Smaller, more frequent changes, so that a failed deployment points to one change.

<!-- test
dev_commit=$(h_get http://flights-dev.localhost:8080/version | jq -r .commit)
h_eq "$dev_commit" "$(git rev-list -n 1 v1.0.0)" "dev still runs the v1.0.0 commit after the rollback"
test "$(kubectl -n flightops-dev get deployment flight-status -o jsonpath='{.status.readyReplicas}')" = "2"
-->

## Part 7: Fix forward

### 7.1 Revert the change through a pull request

`main` still contains the broken manifest. The next merge would deploy it again. You fix `main` with a new commit that reverts the change, through the same pull request process as every other change. The history keeps both commits, so everyone can see what happened.

```bash
cd ~/flight-status
git switch -c fix/readiness-path
git revert --no-edit HEAD
git push -u origin fix/readiness-path
```

Open a pull request from `fix/readiness-path` to `main` with the title `Revert the readiness probe path`.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/13-open_pr-1.png" alt="Open the pull request, step 1 of 2">

<img src="img/09-end-to-end-delivery/13-open_pr-2.png" alt="Open the pull request, step 2 of 2">

<!-- shots:end -->

<!-- ui: open_pr flightops/flight-status fix/readiness-path main "Revert the readiness probe path" -->

<!-- test
h_wait_pr_check flightops/flight-status ci success
-->

Merge it with **Squash and merge**. The `main` run deploys the fixed version to dev.


<!-- shots:begin -->
<img src="img/09-end-to-end-delivery/14-merge_pr-1.png" alt="Merge the pull request, step 1 of 2">

<img src="img/09-end-to-end-delivery/14-merge_pr-2.png" alt="Merge the pull request, step 2 of 2">

<!-- shots:end -->

<!-- ui: merge_pr flightops/flight-status -->

<!-- test
h_wait flightops/flight-status ci success --branch main
-->

### 7.2 Check dev

```bash
git switch main
git pull
git branch -D fix/readiness-path
grep -n 'path: /ready' k8s/base/deployment.yaml
curl -s http://flights-dev.localhost:8080/version; echo
git rev-parse HEAD
```

The probe path is `/ready` again. Dev runs a new version with the commit at the top of `main`. Production still runs `v1.0.0`. To release the fix to production, you would create and push the tag `v1.0.1`.

<!-- test
dev_commit=$(h_get http://flights-dev.localhost:8080/version | jq -r .commit)
h_eq "$dev_commit" "$(git rev-parse HEAD)" "dev runs the fixed commit"
-->

## Part 8: The Harness platform and the DORA metrics

### 8.1 Map the pipeline to the Harness platform

Harness Open Source has no CD objects, so you scripted each step. The Harness platform that United uses provides each step as a feature.

| In this lab | In the Harness platform |
|---|---|
| Pipeline `ci`, stage of type `ci` | Pipeline with a Build (CI) stage |
| Background step `db` | Background step for a service dependency |
| Plugin step `image` | Build and Push step, with a connector for the registry (Amazon ECR) |
| Step `scan` with Trivy | Security Testing Orchestration scan step (Aqua Trivy) |
| Step `deploy` with the `dev_kubeconfig` secret | Deploy stage: Service (manifests and artifact), Environment (dev), Infrastructure Definition (cluster connector and namespace), run by a delegate |
| `kubectl rollout status` | Rolling Deployment step, which waits for the rollout |
| Step `smoke` | HTTP step, or a Verify step with Continuous Verification |
| Step `rollback` with `failure()` | Failure strategy with the Rollback action, and rollback steps |
| Pipeline `promote` started by a tag | Trigger, Approval stage, then a Deploy stage for production |
| Harness secrets `dev_kubeconfig`, `prod_kubeconfig` | Secrets in a secret manager, referenced as `<+secrets.getValue("name")>` |

### 8.2 Read the DORA metrics from this lab

The DORA research measures software delivery with four metrics. You can read all four from what you did in this lab:

```bash
kubectl -n flightops-dev rollout history deployment/flight-status
```

| Metric | Where you find it in this lab |
|---|---|
| Deployment frequency | The number of merges to `main` that deployed to dev today. Each one added a revision to the rollout history. |
| Lead time for changes | The time from a merge to the end of its `main` run. Read the duration of the run in Harness. |
| Change failure rate | Deployments that failed, divided by all deployments. Today that is the readiness rename, one of your pipeline deployments. |
| Failed deployment recovery time | The time from the failed `deploy` step to the end of the `rollback` step. Read the step durations in the failed execution. |

Answer these questions with your numbers:

1. How many minutes passed between the merge of the readiness rename and the moment dev was healthy again?
2. Which step of the pipeline would you speed up first to shorten the lead time?

<!-- runner: stop -->

## Troubleshooting

- **The `image` step pushes only the tag `latest`**: `tags` or `build_args` is a YAML list. Write them as strings, with commas between several values.
- **`scan` fails with a fixable critical vulnerability**: a new CVE was published for a package in the image. Read the table in the log. Rebuild on a newer base image, or update the affected library. Do not loosen the rule without a decision from the team.
- **`deploy` fails with `You must be logged in to the server (Unauthorized)`**: the `dev_kubeconfig` secret holds a token that no longer works, for example after the rotation in Lab 06. Build the kubeconfig again and update the secret.
- **`deploy` fails with `forbidden`**: the `deployer` Role does not allow the action, or the kubeconfig points to the wrong namespace. Check with `kubectl auth can-i ... --as=system:serviceaccount:flightops-dev:deployer`.
- **`smoke` fails although `deploy` passed**: run `curl -H 'Host: flights-dev.localhost' http://localhost:8080/version` on your machine. Check the Ingress host in the overlay. The check expects `1.0.<build number>` of this run.
- **`promote` does not start after `git push origin v1.0.0`**: check the triggers of `promote`. The trigger `release` must be enabled with the event "Tag created". A tag that already existed does not create a new event, so create a new tag such as `v1.0.1`.
- **The `check` step of `promote` fails**: the registry has no image for this commit. Tag a commit that the `ci` pipeline built on `main`, which is the commit at the top of `main` after a successful run, not a commit from a feature branch.
- **The `deploy` step waits for about 90 seconds and then fails**: the new pods did not become ready before the progress deadline. Read the `rollback` log, then `kubectl -n flightops-dev describe pods -l app=flight-status`.

## Going further (optional)

- **Release the fix.** Create the tag `v1.0.1` on the fixed commit and push it. Check that production now runs the same commit as dev.
- **Restrict release tags.** In the repository settings, create a tag rule for the pattern `v*` that allows only selected users to create tags. Discuss who should hold that right at United.
- **Test the probe paths.** Write a pytest test that reads `k8s/base/deployment.yaml`, finds the readiness and liveness paths, and calls them with the API test client. Run the readiness rename again and watch the pull request fail.
- **Smoke-test more than the version.** Extend the `smoke` step to also call `/ready` and `/airports/ORD/departures`, and to fail if either does not return HTTP 200.

## Summary

- The pipeline builds the image once per commit, tags it with the commit SHA, and scans it before anything deploys it (L12: build once, promote the same artifact; L9: supply chain checks).
- Merges to `main` deploy to dev with a least-privilege credential, then verify with `rollout status` and a smoke test through the ingress (L12: automated verification; L8: least privilege).
- A failed deployment rolled back automatically, and the rolling update kept dev available during the failure (L12: rollback; L11: readiness and rolling updates).
- A release tag promoted the same image to production. The tag is the approval step (L12: continuous delivery, promotion, approvals).
- Every step maps to a feature of the Harness platform, and the runs give you the four DORA metrics (L1 and L12).
