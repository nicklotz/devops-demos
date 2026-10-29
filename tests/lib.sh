# Helpers for the hidden <!-- test --> and <!-- ui: --> directives in the lab files.
# tests/run-lab.py sources this file in a subshell with `set -e`.
# ui_* functions do through the Harness REST API what the lab asks the student to do in the UI.
# h_* functions wait for pipelines and check results.

H_URL="${H_URL:-http://localhost:3000}"
H_ADMIN="${H_ADMIN:-admin}"
H_PASSWORD="${H_PASSWORD:-Harness-Lab-2026}"
H_STATE="${H_STATE:-$HOME/.lab-runner}"
mkdir -p "$H_STATE"

# URL-encode a repository path: flightops/flight-status -> flightops%2Fflight-status
h_ref() { printf '%s' "${1//\//%2F}"; }
h_key() { printf '%s' "${1//\//_}"; }

h_session() {
  curl -fsS -X POST "$H_URL/api/v1/login" -H 'Content-Type: application/json' \
    -d "{\"login_identifier\":\"$H_ADMIN\",\"password\":\"$H_PASSWORD\"}" | jq -r .access_token
}

# Personal access token for API calls, created once and cached.
h_token() {
  if [ ! -s "$H_STATE/api-token" ]; then
    curl -fsS -X POST "$H_URL/api/v1/user/tokens" -H "Authorization: Bearer $(h_session)" \
      -H 'Content-Type: application/json' \
      -d "{\"identifier\":\"lab-runner-$(date +%s)\",\"lifetime\":2592000000000000}" \
      | jq -r .access_token > "$H_STATE/api-token"
    chmod 600 "$H_STATE/api-token"
  fi
  cat "$H_STATE/api-token"
}

# h_api METHOD PATH [JSON]: call the API, fail on HTTP errors.
h_api() {
  local method=$1 path=$2 data=${3:-}
  if [ -n "$data" ]; then
    curl -fsS -X "$method" "$H_URL$path" -H "Authorization: Bearer $(h_token)" \
      -H 'Content-Type: application/json' -d "$data"
  else
    curl -fsS -X "$method" "$H_URL$path" -H "Authorization: Bearer $(h_token)"
  fi
}

# h_create METHOD PATH JSON: like h_api, but "already exists" (HTTP 409) counts as success.
h_create() {
  local code
  code=$(curl -sS -o "$H_STATE/last-response.json" -w '%{http_code}' -X "$1" "$H_URL$2" \
    -H "Authorization: Bearer $(h_token)" -H 'Content-Type: application/json' -d "$3")
  case "$code" in
    2*|409) return 0 ;;
    *) echo "HTTP $code from $1 $2: $(cat "$H_STATE/last-response.json")" >&2; return 1 ;;
  esac
}

# Secret values: a literal, or @FILE to read a file.
h_value() {
  case "$1" in
    @*) local f="${1#@}"; cat "${f/#\~/$HOME}" ;;
    *) printf '%s' "$1" ;;
  esac
}

# ---------------------------------------------------------------- UI steps
ui_login() { h_token >/dev/null; }
ui_browse() { :; }
ui_view_execution() { :; }
ui_view_pr() { :; }

ui_create_project() { h_create POST /api/v1/spaces "{\"identifier\":\"$1\"}"; }

ui_create_repo() {
  h_create POST /api/v1/repos "{\"parent_ref\":\"$1\",\"identifier\":\"$2\",\"default_branch\":\"main\"}"
}

# A personal access token for git over HTTP, saved where `credential.helper store` reads it.
ui_create_token() {
  local token
  token=$(curl -fsS -X POST "$H_URL/api/v1/user/tokens" -H "Authorization: Bearer $(h_session)" \
    -H 'Content-Type: application/json' \
    -d "{\"identifier\":\"${1:-git}-$(date +%s)\",\"lifetime\":2592000000000000}" | jq -r .access_token)
  touch ~/.git-credentials && chmod 600 ~/.git-credentials
  grep -Ev '@localhost(:|%3a|%3A)3000' ~/.git-credentials > "$H_STATE/creds" || true
  printf 'http://%s:%s@localhost:3000\n' "$H_ADMIN" "$token" >> "$H_STATE/creds"
  cat "$H_STATE/creds" > ~/.git-credentials && rm -f "$H_STATE/creds"
}

ui_create_pipeline() { # REPO ID YAML_PATH
  h_create POST "/api/v1/repos/$(h_ref "$1")/pipelines" \
    "{\"identifier\":\"$2\",\"config_path\":\"$3\",\"default_branch\":\"main\"}"
}

ui_run_pipeline() { # REPO ID BRANCH
  h_api POST "/api/v1/repos/$(h_ref "$1")/pipelines/$2/executions?branch=${3:-main}" >/dev/null
}

ui_add_trigger() { # REPO PIPELINE TRIGGER ACTION[,ACTION]
  local actions
  actions=$(printf '%s' "$4" | jq -Rc 'split(",")')
  h_create POST "/api/v1/repos/$(h_ref "$1")/pipelines/$2/triggers" \
    "{\"identifier\":\"$3\",\"actions\":$actions,\"disabled\":false}"
}

ui_disable_trigger() { # REPO PIPELINE TRIGGER
  h_api PATCH "/api/v1/repos/$(h_ref "$1")/pipelines/$2/triggers/$3" '{"disabled":true}' >/dev/null
}

ui_create_branch_rule() { # REPO RULE CHECK[,CHECK]
  local checks
  checks=$(printf '%s' "$3" | jq -Rc 'split(",")')
  h_create POST "/api/v1/repos/$(h_ref "$1")/rules" "{
    \"identifier\":\"$2\",\"type\":\"branch\",\"state\":\"active\",\"pattern\":{\"default\":true},
    \"definition\":{\"bypass\":{\"repo_owners\":false},
      \"lifecycle\":{\"delete_forbidden\":true,\"update_forbidden\":true,\"update_force_forbidden\":true},
      \"pullreq\":{\"status_checks\":{\"require_identifiers\":$checks},
                   \"merge\":{\"strategies_allowed\":[\"squash\",\"merge\"],\"delete_branch\":true}}}}"
}

ui_enable_secret_scanning() {
  h_api PATCH "/api/v1/repos/$(h_ref "$1")/settings/security" '{"secret_scanning_enabled":true}' >/dev/null
}

ui_open_pr() { # REPO SOURCE TARGET TITLE
  local n
  n=$(h_api GET "/api/v1/repos/$(h_ref "$1")/pullreq?state=open&source_branch=$2&target_branch=$3" | jq -r '.[0].number // empty')
  if [ -z "$n" ]; then
    n=$(h_api POST "/api/v1/repos/$(h_ref "$1")/pullreq" \
      "$(jq -n --arg s "$2" --arg t "$3" --arg title "$4" '{source_branch:$s,target_branch:$t,title:$title}')" | jq -r .number)
  fi
  echo "$n" > "$H_STATE/pr_$(h_key "$1")"
  echo "pull request #$n"
}

h_last_pr() { cat "$H_STATE/pr_$(h_key "$1")"; }

ui_merge_pr() { # REPO: squash-merge the last opened pull request (waits until the checks allow it)
  local n sha out deadline=$((SECONDS + 600))
  n=$(h_last_pr "$1")
  while :; do
    sha=$(h_api GET "/api/v1/repos/$(h_ref "$1")/pullreq/$n" | jq -r .source_sha)
    if out=$(h_api POST "/api/v1/repos/$(h_ref "$1")/pullreq/$n/merge" \
        "{\"method\":\"squash\",\"source_sha\":\"$sha\",\"delete_source_branch\":true}" 2>&1); then
      echo "merged pull request #$n"
      return 0
    fi
    if [ $SECONDS -gt $deadline ]; then echo "merge of #$n failed: $out" >&2; return 1; fi
    sleep 10
  done
}

ui_close_pr() { # REPO
  h_api POST "/api/v1/repos/$(h_ref "$1")/pullreq/$(h_last_pr "$1")/state" '{"state":"closed"}' >/dev/null
}

ui_create_secret() { # SPACE NAME VALUE|@FILE  (an existing secret gets the new value)
  local body
  body=$(jq -n --arg s "$1" --arg n "$2" --arg d "$(h_value "$3")" '{space_ref:$s,identifier:$n,data:$d}')
  if h_api GET "/api/v1/secrets/$(h_ref "$1/$2")" >/dev/null 2>&1; then
    ui_update_secret "$1" "$2" "$3"
  else
    h_api POST /api/v1/secrets "$body" >/dev/null
  fi
}

ui_update_secret() { # SPACE NAME VALUE|@FILE
  h_api PATCH "/api/v1/secrets/$(h_ref "$1/$2")" \
    "$(jq -n --arg d "$(h_value "$3")" '{data:$d}')" >/dev/null
}

# ---------------------------------------------------------------- checks

# h_wait REPO PIPELINE STATUS [--branch BRANCH | --commit SHA]
# Waits for the newest execution of PIPELINE for a commit (default: local HEAD) and checks its status.
h_wait() {
  local repo=$1 pipe=$2 want=$3 sha ex num="" st="" deadline=$((SECONDS + 900))
  case "${4:-}" in
    --branch) sha=$(h_api GET "/api/v1/repos/$(h_ref "$repo")/branches/$5" | jq -r '.sha // .commit.sha') ;;
    --commit) sha=$5 ;;
    *) sha=$(git rev-parse HEAD) ;;
  esac
  while :; do
    ex=$(h_api GET "/api/v1/repos/$(h_ref "$repo")/pipelines/$pipe/executions?limit=25" \
      | jq -c --arg s "$sha" '[.[] | select(.after == $s)] | max_by(.number) // empty')
    if [ -n "$ex" ]; then
      num=$(jq -r .number <<<"$ex"); st=$(jq -r .status <<<"$ex")
      case "$st" in success|failure|error|killed) break ;; esac
    fi
    if [ $SECONDS -gt $deadline ]; then echo "h_wait: timed out: $pipe for ${sha:0:8} (last: #$num $st)" >&2; return 1; fi
    sleep 5
  done
  echo "h_wait: $repo $pipe #$num $st (commit ${sha:0:8})"
  h_steps "$repo" "$pipe" "$num"
  if [ "$st" != "$want" ]; then echo "h_wait: expected $want, got $st" >&2; return 1; fi
}

h_steps() { # REPO PIPELINE NUMBER: one line per step
  h_api GET "/api/v1/repos/$(h_ref "$1")/pipelines/$2/executions/$3" \
    | jq -r '.stages[]?.steps[]? | "   \(.name): \(.status)"'
}

# h_wait_pr_check REPO CHECK STATUS: wait until all runs for the PR head are finished, then check the status.
h_wait_pr_check() {
  local repo=$1 check=$2 want=$3 n sha st running deadline=$((SECONDS + 900))
  n=$(h_last_pr "$repo")
  sha=$(h_api GET "/api/v1/repos/$(h_ref "$repo")/pullreq/$n" | jq -r .source_sha)
  while :; do
    running=$(h_api GET "/api/v1/repos/$(h_ref "$repo")/pipelines/$check/executions?limit=25" \
      | jq --arg s "$sha" '[.[] | select(.after == $s and (.status == "running" or .status == "pending"))] | length')
    st=$(h_api GET "/api/v1/repos/$(h_ref "$repo")/checks/commits/$sha" \
      | jq -r --arg c "$check" '[.[] | select(.identifier == $c)][0].status // "none"')
    if [ "$running" = "0" ]; then
      case "$st" in success|failure|error) break ;; esac
    fi
    if [ $SECONDS -gt $deadline ]; then echo "h_wait_pr_check: timed out ($check=$st)" >&2; return 1; fi
    sleep 5
  done
  echo "h_wait_pr_check: PR #$n check $check = $st (commit ${sha:0:8})"
  if [ "$st" != "$want" ]; then echo "h_wait_pr_check: expected $want" >&2; return 1; fi
}

# h_log REPO PIPELINE STEP: log of a step in the newest execution.
h_log() {
  local repo=$1 pipe=$2 step=$3 ex num stepno
  ex=$(h_api GET "/api/v1/repos/$(h_ref "$repo")/pipelines/$pipe/executions?limit=1")
  num=$(jq -r '.[0].number' <<<"$ex")
  stepno=$(h_api GET "/api/v1/repos/$(h_ref "$repo")/pipelines/$pipe/executions/$num" \
    | jq -r --arg s "$step" '.stages[0].steps[] | select(.name == $s) | .number')
  [ -n "$stepno" ] || { echo "h_log: no step $step in $pipe #$num" >&2; return 1; }
  h_api GET "/api/v1/repos/$(h_ref "$repo")/pipelines/$pipe/executions/$num/logs/1/$stepno" \
    | jq -r 'if type == "array" then .[].out else empty end'
}

h_eq() { # ACTUAL EXPECTED MESSAGE
  if [ "$1" != "$2" ]; then echo "check failed: ${3:-values differ}: got '$1', expected '$2'" >&2; return 1; fi
}

h_contains() { # TEXT MESSAGE  (reads stdin)
  if ! grep -qF -- "$1"; then echo "check failed: ${2:-text not found}: '$1'" >&2; return 1; fi
}

h_get() { # URL: GET with retries. While old pods stop during a rollout, the ingress can answer 502 for a moment.
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    curl -sf "$1" && return 0
    sleep 1
  done
  echo "check failed: no successful answer from $1" >&2; return 1
}
