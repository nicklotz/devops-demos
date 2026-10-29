# Lab 08: Kubernetes deployments, rollouts and rollbacks

In this lab you deploy the flight status image from Lab 07 to the `flightops-dev` namespace that Terraform created in Lab 04. You write the Kubernetes manifests yourself: a Deployment, a Service and an Ingress, plus a Kustomize overlay for the dev environment. You watch Kubernetes replace a pod you delete, run into the namespace quota when you scale up, and roll out a new version without downtime. Then you break the deployment in three different ways, read the symptoms, and recover. This lab puts lecture L11 into practice. Lab 09 automates the same deployment in a pipeline.

**Lecture:** L11 Kubernetes · **You need:** Lab 07 (or: run `~/devops-demos/scripts/catch-up.sh 08` on a fresh machine)

## Goals

- Write a Deployment with readiness and liveness probes, resource limits and a rolling update strategy, plus a Service and an Ingress.
- Use a Kustomize base and an overlay for one environment.
- Observe self-healing, a ResourceQuota limit, and a rolling update that keeps the service available.
- Diagnose an image that cannot be pulled, a container that crashes at start, and a pod that is not ready, and recover from each.
- Compare the local k3d cluster with Amazon EKS.

## Before you start

You need the `main` branch with the Dockerfile from Lab 07, the image `1.0.0` in the local registry, and the dev database that Terraform created in Lab 04.

```bash
cd ~/flight-status
git switch main
git pull
ls Dockerfile compose.yaml ecs/taskdef.json
curl -s http://k3d-registry.localhost:5000/v2/flight-status/tags/list; echo
kubectl -n flightops-dev get deployment postgres
kubectl -n flightops-dev get secret flight-status-db
```

You should see output like this:

```text
Dockerfile  compose.yaml  ecs/taskdef.json
{"name":"flight-status","tags":["1.0.0"]}
NAME       READY   UP-TO-DATE   AVAILABLE   AGE
postgres   1/1     1            1           1d
NAME               TYPE     DATA   AGE
flight-status-db   Opaque   4      1d
```

The Secret `flight-status-db` holds the database connection settings, including the password that Terraform generated. Your manifests refer to this Secret by name. The password never appears in the repository.

## Part 1: Write the manifests

### 1.1 Create a branch and the folders

The manifests go into the `flight-status` repository, next to the code they deploy. `k8s/base` holds the manifests that every environment shares. `k8s/dev` holds the settings for the dev environment only. Lab 09 adds `k8s/prod`.

```bash
cd ~/flight-status
git switch -c feature/kubernetes
mkdir -p k8s/base k8s/dev
```

### 1.2 The Deployment

A Deployment tells Kubernetes which container to run, how many copies (replicas) to keep, and how to replace them when the specification changes. The Deployment creates a ReplicaSet for each version of its pod template, and the ReplicaSet creates the pods. Read the fields before you create the file.

| Field | What it does |
|---|---|
| `replicas: 2` | Keeps two pods running. If one pod fails, the other one keeps serving requests while Kubernetes replaces the failed one. |
| `selector.matchLabels` and `template.metadata.labels` | The Deployment finds its pods by the label `app: flight-status`. The two must match. |
| `strategy.rollingUpdate` | `maxSurge: 1` allows one extra pod during an update. `maxUnavailable: 0` means the number of ready pods never drops below `replicas`. Together they replace pods one at a time, and a new pod must be ready before an old one stops. |
| `progressDeadlineSeconds: 90` | If an update makes no progress for 90 seconds, Kubernetes marks it as failed. The pipeline in Lab 09 relies on this. |
| `revisionHistoryLimit: 5` | Keeps the five previous ReplicaSets, so you can roll back to any of them. |
| `image: flight-status` | A placeholder. The Kustomize overlay replaces it with the registry address and the tag. |
| `envFrom.configMapRef` | Loads settings that are not secret, here `APP_ENV`, from a ConfigMap. Kustomize generates this ConfigMap. |
| `env` with `secretKeyRef` | Sets `DATABASE_URL` from the Secret `flight-status-db`. |
| `readinessProbe` on `/ready` | Kubernetes calls `/ready` every 5 seconds. After 3 failures in a row, the pod counts as not ready and stops receiving traffic. Kubernetes does not restart it. |
| `livenessProbe` on `/health` | Kubernetes calls `/health` every 10 seconds. After 3 failures in a row, the kubelet restarts the container. `/health` does not check the database on purpose. A restart does not fix a database problem. |
| `lifecycle.preStop` | Before Kubernetes stops a container, it waits 5 seconds. Removing a pod from the Service and from the ingress takes a moment. Without the pause, a few requests can still reach a pod that is already shutting down, and fail with `502 Bad Gateway`. |
| `resources.requests` | What the scheduler reserves for the container on a node: 0.1 CPU and 128 MiB of memory. |
| `resources.limits` | The maximum. A container that uses more CPU than its limit is slowed down. A container that uses more memory than its limit is stopped (OOMKilled). The namespace quota from Lab 04 counts the limits. |
| `securityContext` | `runAsNonRoot: true` makes the kubelet refuse to start the container as root. This check works because the image sets a numeric user (`USER 10001`, Lab 07). `allowPrivilegeEscalation: false` stops a process from gaining more rights than its parent. |

Because the requests are lower than the limits, Kubernetes puts these pods in the quality of service class "Burstable". When a node runs out of memory, Kubernetes evicts "BestEffort" pods first, then "Burstable" pods, then "Guaranteed" pods.

Create `~/flight-status/k8s/base/deployment.yaml` with this content.

<!-- file: ~/flight-status/k8s/base/deployment.yaml -->
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: flight-status
  labels:
    app: flight-status
spec:
  replicas: 2
  revisionHistoryLimit: 5
  # Mark the rollout as failed if it makes no progress for 90 seconds.
  progressDeadlineSeconds: 90
  selector:
    matchLabels:
      app: flight-status
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1        # at most one extra pod during an update
      maxUnavailable: 0  # never go below the desired number of ready pods
  template:
    metadata:
      labels:
        app: flight-status
    spec:
      containers:
        - name: app
          image: flight-status   # replaced by the overlay's "images" setting
          ports:
            - name: http
              containerPort: 8000
          envFrom:
            - configMapRef:
                name: flight-status-config
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: flight-status-db
                  key: DATABASE_URL
          readinessProbe:
            httpGet:
              path: /ready
              port: http
            periodSeconds: 5
            failureThreshold: 3
          livenessProbe:
            httpGet:
              path: /health
              port: http
            periodSeconds: 10
            failureThreshold: 3
          # Keep serving for 5 seconds after the pod is told to stop, while the
          # Service and the ingress stop sending requests to it.
          lifecycle:
            preStop:
              sleep:
                seconds: 5
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
          securityContext:
            runAsNonRoot: true
            allowPrivilegeEscalation: false
```

### 1.3 The Service

Pods come and go, and each new pod gets a new IP address. A Service gives the pods one stable name and one virtual IP address. It sends each connection to one of the ready pods that match its selector. Inside the namespace, other pods reach the service at `http://flight-status`. The Service listens on port 80 and forwards to the container port named `http` (8000).

Create `~/flight-status/k8s/base/service.yaml`.

<!-- file: ~/flight-status/k8s/base/service.yaml -->
```yaml
apiVersion: v1
kind: Service
metadata:
  name: flight-status
spec:
  selector:
    app: flight-status
  ports:
    - name: http
      port: 80
      targetPort: http
```

### 1.4 The Ingress

A Service is reachable only inside the cluster. An Ingress routes HTTP requests from outside the cluster to a Service, based on the host name and the path. k3s, the Kubernetes distribution inside k3d, includes the Traefik ingress controller. The k3d load balancer forwards port 8080 of your machine to Traefik. The host name in the base file is a placeholder. Each overlay sets its own host name.

Create `~/flight-status/k8s/base/ingress.yaml`.

<!-- file: ~/flight-status/k8s/base/ingress.yaml -->
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: flight-status
spec:
  rules:
    - host: flights.localhost   # replaced by each overlay
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: flight-status
                port:
                  name: http
```

### 1.5 The Kustomize base and the dev overlay

Kustomize combines and changes YAML files without templates. The base lists the shared manifests. An overlay starts from the base and applies the changes for one environment. Kustomize is built into kubectl (`kubectl kustomize` and `kubectl apply -k`). The Harness platform accepts Kustomize folders as the manifests of a Kubernetes service.

Create `~/flight-status/k8s/base/kustomization.yaml`.

<!-- file: ~/flight-status/k8s/base/kustomization.yaml -->
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
  - ingress.yaml
```

The dev overlay sets four things:

- `namespace: flightops-dev` puts every object into the dev namespace.
- `configMapGenerator` creates the ConfigMap `flight-status-config` with `APP_ENV=dev`. Kustomize adds a hash of the content to the name, for example `flight-status-config-7t5g9hc6c4`, and updates the reference in the Deployment. If you change a value, the name changes, and the Deployment rolls out new pods that read the new value.
- `images` replaces the placeholder `flight-status` with `k3d-registry.localhost:5000/flight-status:1.0.0`.
- `patches` replaces the Ingress host with `flights-dev.localhost`. The patch uses the JSON Patch format: an operation, a path inside the object, and a value.

Create `~/flight-status/k8s/dev/kustomization.yaml`.

<!-- file: ~/flight-status/k8s/dev/kustomization.yaml -->
```yaml
# The dev environment: namespace flightops-dev, http://flights-dev.localhost:8080
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: flightops-dev
resources:
  - ../base
configMapGenerator:
  - name: flight-status-config
    literals:
      - APP_ENV=dev
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
        value: flights-dev.localhost
```

### 1.6 Render the overlay

`kubectl kustomize` prints the final YAML without sending anything to the cluster. Read the full output once, then filter it for the values the overlay changed.

```bash
kubectl kustomize k8s/dev
kubectl kustomize k8s/dev | grep -E 'namespace:|image:|host:|name: flight-status-config'
```

In the filtered output, check these values:

```text
  name: flight-status-config-7t5g9hc6c4
  namespace: flightops-dev
                name: flight-status-config-7t5g9hc6c4
        image: k3d-registry.localhost:5000/flight-status:1.0.0
  - host: flights-dev.localhost
```

The generated ConfigMap name and the reference in the Deployment end with the same hash suffix. Every object has the namespace `flightops-dev`.

<!-- test
kubectl kustomize k8s/dev | grep -q "image: k3d-registry.localhost:5000/flight-status:1.0.0"
kubectl kustomize k8s/dev | grep -q "host: flights-dev.localhost"
-->

## Part 2: Deploy to dev

### 2.1 Apply the overlay

`kubectl apply -k` renders the overlay and sends the objects to the API server. Kubernetes stores them as the desired state, and its controllers start working towards it. `kubectl rollout status` waits until the Deployment reports that all new pods are ready.

```bash
cd ~/flight-status
kubectl apply -k k8s/dev
kubectl -n flightops-dev rollout status deployment/flight-status --timeout=120s
```

You should see:

```text
configmap/flight-status-config-7t5g9hc6c4 created
service/flight-status created
deployment.apps/flight-status created
ingress.networking.k8s.io/flight-status created
Waiting for deployment "flight-status" rollout to finish: 0 of 2 updated replicas are available...
Waiting for deployment "flight-status" rollout to finish: 1 of 2 updated replicas are available...
deployment "flight-status" successfully rolled out
```

### 2.2 Look at what Kubernetes created

```bash
kubectl -n flightops-dev get deployment,replicaset,pods,service,ingress
```

The output also lists the PostgreSQL objects from Lab 04. For `flight-status`, follow the chain:

- The Deployment `flight-status` shows `2/2` ready.
- One ReplicaSet `flight-status-<hash>` has 2 desired and 2 ready pods. The hash identifies the pod template.
- Two pods `flight-status-<hash>-<id>` are `Running` with `1/1` ready.
- The Service `flight-status` has a cluster IP and port 80.
- The Ingress `flight-status` has the host `flights-dev.localhost`.

### 2.3 See which pods receive traffic

A Service keeps a list of endpoints, the IP addresses of the matching pods, in EndpointSlice objects. Only ready pods receive traffic. The second command prints the quality of service class of a pod.

```bash
kubectl -n flightops-dev get endpointslices -l kubernetes.io/service-name=flight-status \
  -o jsonpath='{range .items[*].endpoints[*]}{.targetRef.name}{"  ready="}{.conditions.ready}{"\n"}{end}'
kubectl -n flightops-dev get pods -l app=flight-status -o jsonpath='{.items[0].status.qosClass}'; echo
```

You should see:

```text
flight-status-5d8c7b9f6d-2kq4x  ready=true
flight-status-5d8c7b9f6d-x7m2p  ready=true
Burstable
```

### 2.4 Call the service

On your machine, every name that ends in `.localhost` resolves to your machine. A request to `http://flights-dev.localhost:8080` takes this path: port 8080 on your machine, the k3d load balancer container, Traefik inside the cluster, the Service `flight-status`, and one of the two pods on port 8000.

```bash
curl -s http://flights-dev.localhost:8080/version; echo
curl -s http://flights-dev.localhost:8080/ready; echo
```

You should see:

```text
{"version":"1.0.0","commit":"3c1f0a9e...","environment":"dev"}
{"status":"ready","storage":"postgres"}
```

The service uses the dev database. On its first start it created its table and loaded the sample flights.

<!-- test
h_get http://flights-dev.localhost:8080/version | jq -e '.version == "1.0.0" and .environment == "dev"' > /dev/null
h_get http://flights-dev.localhost:8080/ready | jq -e '.storage == "postgres"' > /dev/null
-->

Open http://flights-dev.localhost:8080 in the browser. The page lists the flights and shows `Version 1.0.0 · environment dev`.


<!-- shots:begin -->
<img src="img/08-kubernetes-rollouts/01-browse-1.png" alt="The page in the browser">

<!-- shots:end -->

<!-- ui: browse http://flights-dev.localhost:8080 -->

## Part 3: Self-healing, scaling and the quota

### 3.1 Delete a pod

Kubernetes controllers compare the desired state with the actual state and act on the difference. This is called reconciliation. Delete one of the two pods and watch the ReplicaSet controller create a replacement.

```bash
kubectl -n flightops-dev get pods -l app=flight-status
POD=$(kubectl -n flightops-dev get pods -l app=flight-status -o jsonpath='{.items[0].metadata.name}')
kubectl -n flightops-dev delete pod "$POD"
kubectl -n flightops-dev get pods -l app=flight-status
kubectl -n flightops-dev rollout status deployment/flight-status --timeout=120s
```

The second list shows a new pod with a different name and an age of a few seconds. You did not restart anything. The ReplicaSet wanted two pods, saw one, and created one.

### 3.2 Scale up within the quota

`kubectl scale` changes the number of replicas. The ResourceQuota that Terraform created in Lab 04 limits the dev namespace to 4 CPUs of limits, 4 GiB of memory limits and 12 pods. `kubectl describe resourcequota` shows how much of the quota is in use.

```bash
kubectl -n flightops-dev scale deployment/flight-status --replicas=4
kubectl -n flightops-dev rollout status deployment/flight-status --timeout=120s
kubectl -n flightops-dev describe resourcequota quota
```

You should see:

```text
Resource       Used    Hard
--------       ----    ----
limits.cpu     3       4
limits.memory  1536Mi  4Gi
pods           5       12
```

Four app pods with a limit of 0.5 CPU each use 2 CPUs. PostgreSQL uses 1 CPU. Together they use 3 of the 4 CPUs the quota allows.

### 3.3 Scale past the quota

Ask for 8 replicas. Eight app pods would need 4 CPUs, plus 1 CPU for PostgreSQL, which is more than the quota allows.

```bash
kubectl -n flightops-dev scale deployment/flight-status --replicas=8
sleep 10
kubectl -n flightops-dev get deployment flight-status
kubectl -n flightops-dev get events --field-selector reason=FailedCreate | tail -3
```

You should see 6 of 8 pods ready, and events like this one:

```text
NAME            READY   UP-TO-DATE   AVAILABLE   AGE
flight-status   6/8     6            6           12m
... Error creating: pods "flight-status-5d8c7b9f6d-q2w8r" is forbidden: exceeded quota: quota, requested: limits.cpu=500m, used: limits.cpu=4, limited: limits.cpu=4
```

The API server refused to create the last two pods. The ReplicaSet keeps trying, and the quota keeps refusing. A quota protects the cluster and the other teams on it from one namespace that grows too much.

<!-- test
for attempt in $(seq 1 20); do
  if kubectl -n flightops-dev get events --field-selector reason=FailedCreate 2>/dev/null | grep -q "exceeded quota"; then exit 0; fi
  sleep 2
done
echo "No 'exceeded quota' event found"
exit 1
-->

### 3.4 Return to the declared state

```bash
kubectl -n flightops-dev scale deployment/flight-status --replicas=2
kubectl -n flightops-dev rollout status deployment/flight-status --timeout=120s
kubectl -n flightops-dev get pods -l app=flight-status
```

`kubectl scale` is an imperative change. The file in Git still says `replicas: 2`. If you had left 4 replicas running, the cluster would have drifted from Git, as the namespace quota drifted from Terraform in Lab 04. The next `kubectl apply -k` would set 2 again. In a GitOps setup, a controller in the cluster would undo such a change by itself.

## Part 4: Roll out version 1.1.0

### 4.1 Build and push version 1.1.0

A new version of a service is a new image. Here only the version number changes, so the build reuses every cached layer except the version settings.

```bash
cd ~/flight-status
docker build -t k3d-registry.localhost:5000/flight-status:1.1.0 \
  --build-arg APP_VERSION=1.1.0 \
  --build-arg GIT_COMMIT="$(git rev-parse HEAD)" \
  .
docker push k3d-registry.localhost:5000/flight-status:1.1.0
```

### 4.2 Optional: watch the rollout in two more terminals

To see the rolling update as it happens, open two more terminal windows before the next step. In the first one, watch the pods:

<!-- skip -->
```bash
kubectl -n flightops-dev get pods -l app=flight-status -w
```

In the second one, call the service twice a second:

<!-- skip -->
```bash
while true; do curl -s http://flights-dev.localhost:8080/version; echo; sleep 0.5; done
```

Leave both running. Stop them with Ctrl+C after step 4.3.

### 4.3 Change the tag and apply

You change the version in the overlay file, not with a kubectl command, so Git records which version dev runs. Then you apply the overlay.

```bash
sed -i 's/newTag: "1.0.0"/newTag: "1.1.0"/' k8s/dev/kustomization.yaml
grep newTag k8s/dev/kustomization.yaml
kubectl apply -k k8s/dev
kubectl -n flightops-dev rollout status deployment/flight-status --timeout=120s
```

You should see:

```text
    newTag: "1.1.0"
configmap/flight-status-config-7t5g9hc6c4 unchanged
service/flight-status unchanged
deployment.apps/flight-status configured
ingress.networking.k8s.io/flight-status unchanged
Waiting for deployment "flight-status" rollout to finish: 1 out of 2 new replicas have been updated...
Waiting for deployment "flight-status" rollout to finish: 1 old replicas are pending termination...
deployment "flight-status" successfully rolled out
```

Only the Deployment changed. If you watched the second terminal, the answers switched from `1.0.0` to `1.1.0` with no failed request in between.

### 4.4 Walk through the rolling update

With 2 replicas, `maxSurge: 1` and `maxUnavailable: 0`, the rollout went through these states:

| State | Pods with 1.0.0 | Pods with 1.1.0 | Ready pods |
|---|---|---|---|
| Start | 2 | 0 | 2 |
| One new pod starts (surge) | 2 | 1, starting | 2 |
| New pod ready, one old pod stops | 1 | 1 | 2 |
| Second new pod starts | 1 | 2, one starting | 2 |
| Second new pod ready, last old pod stops | 0 | 2 | 2 |

The number of ready pods never dropped below 2. Each step waited for the readiness probe of the new pod. Look at the result:

```bash
kubectl -n flightops-dev get replicasets -l app=flight-status
curl -s http://flights-dev.localhost:8080/version; echo
kubectl -n flightops-dev rollout history deployment/flight-status
kubectl -n flightops-dev rollout history deployment/flight-status --revision=1 | grep Image
```

You should see:

```text
NAME                       DESIRED   CURRENT   READY   AGE
flight-status-5d8c7b9f6d   0         0         0       14m
flight-status-7f9b6c5d4e   2         2         2       40s
{"version":"1.1.0","commit":"3c1f0a9e...","environment":"dev"}
deployment.apps/flight-status
REVISION  CHANGE-CAUSE
1         <none>
2         <none>
    Image:	k3d-registry.localhost:5000/flight-status:1.0.0
```

The old ReplicaSet still exists with 0 pods. Kubernetes keeps it for a rollback. `CHANGE-CAUSE` is empty because nobody recorded a reason. A delivery pipeline keeps that record instead: each Harness execution shows which commit and image it deployed.

<!-- test
h_get http://flights-dev.localhost:8080/version | jq -e '.version == "1.1.0"' > /dev/null
-->

## Part 5: Failure 1, an image that does not exist

### 5.1 Deploy a tag that was never pushed

A typing mistake in an image tag is a common failure. `kubectl set image` changes the image of the container `app` without editing the files. You use it here to cause the failure quickly. In real work, every change goes through Git.

```bash
kubectl -n flightops-dev set image deployment/flight-status app=k3d-registry.localhost:5000/flight-status:9.9.9
```

Wait up to 40 seconds for the rollout. The command fails, because the new pod never becomes ready.

<!-- expect-fail -->
```bash
kubectl -n flightops-dev rollout status deployment/flight-status --timeout=40s
```

You should see:

```text
Waiting for deployment "flight-status" rollout to finish: 1 out of 2 new replicas have been updated...
error: timed out waiting for the condition
```

### 5.2 Read the symptoms

```bash
kubectl -n flightops-dev get pods -l app=flight-status
curl -s http://flights-dev.localhost:8080/version; echo
kubectl -n flightops-dev get events --field-selector reason=Failed --sort-by=.lastTimestamp | tail -3
```

You should see:

```text
NAME                             READY   STATUS             RESTARTS   AGE
flight-status-7f9b6c5d4e-8hx2k   1/1     Running            0          5m
flight-status-7f9b6c5d4e-m4q7z   1/1     Running            0          5m
flight-status-6c8d7e9f5a-t2v9w   0/1     ImagePullBackOff   0          45s
{"version":"1.1.0","commit":"3c1f0a9e...","environment":"dev"}
... Failed to pull image "k3d-registry.localhost:5000/flight-status:9.9.9": ... not found
```

The status may also show `ErrImagePull`. Kubernetes retries the pull with growing pauses, which is what `BackOff` means. The two old pods still run version 1.1.0 and still answer requests. `maxUnavailable: 0` stopped Kubernetes from removing an old pod before a new pod was ready.

### 5.3 Roll back

`kubectl rollout undo` applies the pod template of the previous revision again. Here that is the template with version 1.1.0. Kubernetes scales the failed ReplicaSet down to 0.

```bash
kubectl -n flightops-dev rollout undo deployment/flight-status
kubectl -n flightops-dev rollout status deployment/flight-status --timeout=120s
kubectl -n flightops-dev get pods -l app=flight-status
```

The failed pod is gone, and two pods are running. The cluster matches Git again (`newTag: "1.1.0"`).

<!-- test
h_get http://flights-dev.localhost:8080/version | jq -e '.version == "1.1.0"' > /dev/null
test "$(kubectl -n flightops-dev get deployment flight-status -o jsonpath='{.status.readyReplicas}')" = "2"
-->

## Part 6: Failure 2, a wrong database password

### 6.1 Deploy a bad configuration

A wrong setting is another common failure. `kubectl set env` replaces the `DATABASE_URL` that came from the Secret with a literal value that contains the wrong password.

```bash
kubectl -n flightops-dev set env deployment/flight-status DATABASE_URL=postgresql://flights:wrong@postgres:5432/flights
```

The rollout does not finish:

<!-- expect-fail -->
```bash
kubectl -n flightops-dev rollout status deployment/flight-status --timeout=40s
```

### 6.2 Read the symptoms

```bash
kubectl -n flightops-dev get pods -l app=flight-status
```

The new pod shows `Error` or `CrashLoopBackOff`, and its `RESTARTS` count goes up. The container starts, stops with an error, and the kubelet starts it again after a growing pause. Read the log of the newest pod:

```bash
POD=$(kubectl -n flightops-dev get pods -l app=flight-status --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}')
echo "$POD"
kubectl -n flightops-dev logs "$POD" --tail=20
```

You should see lines like these near the end:

```text
psycopg.OperationalError: connection failed: connection to server at "10.43.12.34", port 5432 failed: FATAL:  password authentication failed for user "flights"
ERROR:    Application startup failed. Exiting.
```

At startup, the service connects to the database to create its table. With the wrong password the connection fails, the service exits, and the container stops. `kubectl logs` shows the output of the last run of the container. `kubectl logs --previous` shows the run before that.

The old pods still serve version 1.1.0, for the same reason as in Part 5: the new pod never became ready, so Kubernetes did not remove an old one.

<!-- test
POD=$(kubectl -n flightops-dev get pods -l app=flight-status --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].metadata.name}')
( kubectl -n flightops-dev logs "$POD" --tail=50 2>/dev/null || true; kubectl -n flightops-dev logs "$POD" --previous --tail=50 2>/dev/null || true ) | grep -q "password authentication failed"
h_get http://flights-dev.localhost:8080/version | jq -e '.version == "1.1.0"' > /dev/null
-->

### 6.3 Roll back

```bash
kubectl -n flightops-dev rollout undo deployment/flight-status
kubectl -n flightops-dev rollout status deployment/flight-status --timeout=120s
kubectl -n flightops-dev get deployment flight-status -o jsonpath='{.spec.template.spec.containers[0].env[0].valueFrom.secretKeyRef.name}'; echo
```

The last command prints `flight-status-db`. The rollback restored the reference to the Secret.

## Part 7: Failure 3, the database goes away

### 7.1 Stop the database

Readiness and liveness answer different questions. Readiness asks whether the pod can serve requests right now. Liveness asks whether the process is stuck and needs a restart. To see the difference, scale the PostgreSQL Deployment to zero pods. Terraform manages this Deployment with one replica, so you return it to one at the end of this part.

```bash
kubectl -n flightops-dev scale deployment/postgres --replicas=0
kubectl -n flightops-dev wait --for=condition=Ready=false pod -l app=flight-status --timeout=90s
kubectl -n flightops-dev get pods
```

You should see:

```text
NAME                             READY   STATUS    RESTARTS   AGE
flight-status-7f9b6c5d4e-8hx2k   0/1     Running   0          12m
flight-status-7f9b6c5d4e-m4q7z   0/1     Running   0          12m
```

There is no PostgreSQL pod. The app pods are `Running`, but `0/1` ready. `RESTARTS` stays at 0.

### 7.2 Read the symptoms

```bash
kubectl -n flightops-dev get events --field-selector reason=Unhealthy --sort-by=.lastTimestamp | tail -3
kubectl -n flightops-dev get endpointslices -l kubernetes.io/service-name=flight-status \
  -o jsonpath='{range .items[*].endpoints[*]}{.targetRef.name}{"  ready="}{.conditions.ready}{"\n"}{end}'
curl -s -o /dev/null -w '%{http_code}\n' http://flights-dev.localhost:8080/version
```

You should see:

```text
... Readiness probe failed: HTTP probe failed with statuscode: 503
flight-status-7f9b6c5d4e-8hx2k  ready=false
flight-status-7f9b6c5d4e-m4q7z  ready=false
404
```

`/ready` answers 503 because the service cannot reach its database. Kubernetes marked both pods as not ready and took them out of the Service. The request through the ingress fails because no pod is ready to receive it. Traefik in k3s answers 404 in this case, while other ingress controllers answer 503. The liveness probe on `/health` still passes, so the kubelet does not restart the containers. A restart would not help, because the problem is the database.

<!-- test
test "$(kubectl -n flightops-dev get pods -l app=flight-status -o jsonpath='{.items[*].status.containerStatuses[0].ready}' | tr ' ' '\n' | sort -u)" = "false"
code=$(curl -s -o /dev/null -w '%{http_code}' http://flights-dev.localhost:8080/version)
test "$code" != "200"
-->

### 7.3 Start the database again

```bash
kubectl -n flightops-dev scale deployment/postgres --replicas=1
kubectl -n flightops-dev rollout status deployment/postgres --timeout=120s
kubectl -n flightops-dev wait --for=condition=Ready pod -l app=flight-status --timeout=120s
curl -s http://flights-dev.localhost:8080/ready; echo
```

You should see `{"status":"ready","storage":"postgres"}`. The app pods became ready again without a restart. The data is still there, because PostgreSQL keeps its files on the persistent volume claim that Terraform created. The Deployment `postgres` has one replica again, as Terraform expects, so the next `terraform plan` shows no drift.

<!-- test
h_get http://flights-dev.localhost:8080/ready | jq -e '.status == "ready"' > /dev/null
h_get http://flights-dev.localhost:8080/version | jq -e '.version == "1.1.0"' > /dev/null
-->

### 7.4 What the three failures have in common

| Failure | Pod status | Old version kept serving? | How you found the cause |
|---|---|---|---|
| Image does not exist | `ErrImagePull`, `ImagePullBackOff` | Yes | `kubectl get events` |
| Wrong configuration | `Error`, `CrashLoopBackOff` | Yes | `kubectl logs` |
| Database unavailable | `Running`, `0/1` ready | No, nothing could serve | Readiness events and EndpointSlices |

In the first two cases, the rolling update strategy and the readiness probe protected the users. In the third case, no deployment happened. The cause was outside the pods, and the readiness probe stopped traffic to pods that could not serve it.

## Part 8: k3d and Amazon EKS

At United, applications run on Amazon EKS. Everything you used in this lab is the standard Kubernetes API, so the manifests and the kubectl commands work the same way on EKS. The table shows what differs.

| Area | k3d on your machine | Amazon EKS |
|---|---|---|
| Control plane | A k3s server in a Docker container that you manage | Run by AWS across several availability zones. AWS upgrades and backs it up. |
| Nodes | One Docker container | EC2 instances in managed node groups, or Fargate profiles |
| Ingress | Traefik, included in k3s | The AWS Load Balancer Controller creates an Application Load Balancer from Ingress objects |
| Images | `k3d-registry.localhost:5000` over HTTP | Amazon ECR over HTTPS, with IAM authentication and image scanning |
| Access from pods to AWS services | None | IAM roles for service accounts, or EKS Pod Identity |
| Persistent volumes | Folders on the VM disk (local-path) | Amazon EBS or EFS volumes through CSI drivers |
| Same on both | Deployments, Services, Ingress, probes, quotas, RBAC, rollouts, kubectl, Kustomize | |

At United, the Harness platform deploys to EKS. A Harness Kubernetes rolling deployment applies the manifests, waits for the rollout like `kubectl rollout status`, and runs rollback steps when it fails. Lab 09 builds the same behaviour into the pipeline.

## Part 9: Commit and merge

### 9.1 Commit and push the branch

```bash
cd ~/flight-status
git add k8s
git status --short
git commit -m "Add Kubernetes manifests and the dev overlay"
git push -u origin feature/kubernetes
```

`git status --short` should list five new files, with `newTag: "1.1.0"` in the dev overlay:

```text
A  k8s/base/deployment.yaml
A  k8s/base/ingress.yaml
A  k8s/base/kustomization.yaml
A  k8s/base/service.yaml
A  k8s/dev/kustomization.yaml
```

### 9.2 Open and merge the pull request

In Harness, open the **flight-status** repository and select **Pull Requests**, then **New Pull Request**. Choose `main` as the target branch and `feature/kubernetes` as the source branch. Enter the title `Add Kubernetes manifests` and create the pull request.


<!-- shots:begin -->
<img src="img/08-kubernetes-rollouts/02-open_pr-1.png" alt="Open the pull request, step 1 of 2">

<img src="img/08-kubernetes-rollouts/02-open_pr-2.png" alt="Open the pull request, step 2 of 2">

<!-- shots:end -->

<!-- ui: open_pr flightops/flight-status feature/kubernetes main "Add Kubernetes manifests" -->

Wait until the `ci` check shows success.

<!-- test
h_wait_pr_check flightops/flight-status ci success
-->

Merge the pull request with **Squash and merge** and delete the source branch when Harness offers it.


<!-- shots:begin -->
<img src="img/08-kubernetes-rollouts/03-merge_pr-1.png" alt="Merge the pull request, step 1 of 2">

<img src="img/08-kubernetes-rollouts/03-merge_pr-2.png" alt="Merge the pull request, step 2 of 2">

<!-- shots:end -->

<!-- ui: merge_pr flightops/flight-status -->

<!-- test
h_wait flightops/flight-status ci success --branch main
-->

### 9.3 Update your local main branch

```bash
git switch main
git pull
git branch -D feature/kubernetes
kubectl -n flightops-dev get deployment flight-status
```

The `main` branch now contains the manifests, and dev runs version 1.1.0 with two ready pods.

<!-- test
git show HEAD:k8s/dev/kustomization.yaml | grep -q 'newTag: "1.1.0"'
test "$(kubectl -n flightops-dev get deployment flight-status -o jsonpath='{.status.readyReplicas}')" = "2"
h_get http://flights-dev.localhost:8080/version | jq -e '.version == "1.1.0"' > /dev/null
-->

<!-- runner: stop -->

## Troubleshooting

- **`namespaces "flightops-dev" not found`**: the Terraform from Lab 04 has not run against this cluster. Run `terraform apply` in `~/platform`, or use the catch-up script.
- **Pods stay in `CreateContainerConfigError`**: the Secret `flight-status-db` or the generated ConfigMap is missing. Check with `kubectl -n flightops-dev get secret,configmap`. Terraform creates the Secret.
- **`ErrImagePull` for version 1.0.0 or 1.1.0**: the image is not in the registry. Check with `curl -s http://k3d-registry.localhost:5000/v2/flight-status/tags/list` and push it again.
- **`Error: container has runAsNonRoot and image will run as root`**: the image was built without the `USER 10001` line. Rebuild it from the Lab 07 Dockerfile.
- **`curl http://flights-dev.localhost:8080` returns `404 page not found`**: no ready pod matches the Ingress, or the host name is wrong. Check `kubectl -n flightops-dev get ingress` and `kubectl -n flightops-dev get pods`.
- **`exceeded quota` events**: the namespace has reached its quota. Scale down, or raise the quota through Terraform in the `platform` repository.
- **A rollout seems stuck**: run `kubectl -n flightops-dev describe deployment flight-status` and `kubectl -n flightops-dev get events --sort-by=.lastTimestamp`. Use `kubectl -n flightops-dev rollout undo deployment/flight-status` to return to the previous version.
- **`kubectl wait` times out in Part 7**: the probes need up to 15 seconds to change state. Run the `kubectl get pods` command again after a few seconds.

## Going further (optional)

- **Resource usage.** k3s includes the metrics server. Run `kubectl -n flightops-dev top pods` and compare the CPU and memory use with the requests and limits in the Deployment.
- **Record a change cause.** Run `kubectl -n flightops-dev annotate deployment/flight-status kubernetes.io/change-cause="Version 1.1.0" --overwrite`, then `kubectl -n flightops-dev rollout history deployment/flight-status`. Remove the annotation afterwards with `kubectl -n flightops-dev annotate deployment/flight-status kubernetes.io/change-cause-`, because Kubernetes copies it to every later revision.
- **Check the pipeline's permissions.** For each kubectl command you used, ask whether the `deployer` ServiceAccount from Lab 06 may run it, for example `kubectl auth can-i patch deployments -n flightops-dev --as=system:serviceaccount:flightops-dev:deployer`. Which commands would the pipeline in Lab 09 be unable to run?
- **Scan the manifests.** Run `trivy config k8s/` and read the findings about the security context and resource settings.
- **Add a startup probe.** Read about `startupProbe` in the Kubernetes documentation. Decide whether this service needs one, and what would change for an application that needs two minutes to start.

## Summary

- You wrote a Deployment, a Service and an Ingress, and used a Kustomize overlay to set the namespace, image, configuration and host for dev (L11: objects, Services and Ingress).
- You saw reconciliation replace a deleted pod, and a ResourceQuota from Terraform refuse pods beyond the namespace limit (L11: the declarative API and control loops).
- You rolled out a new version with `maxSurge: 1` and `maxUnavailable: 0` and kept two ready pods the whole time (L11: rolling-update arithmetic).
- You diagnosed a missing image, a crashing container and a failing readiness probe from pod status, events, logs and EndpointSlices, and recovered with `rollout undo` (L11: probes; L12: rollback).
- You compared k3d with Amazon EKS: the API and the manifests are the same, and the managed services around the cluster differ.
