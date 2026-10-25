#!/usr/bin/env bash
# Bring a FRESH lab machine to the start of a lab by replaying the earlier labs.
#
#   sudo apt-get update && sudo apt-get install -y git
#   git clone https://github.com/nicklotz/devops-demos.git ~/devops-demos
#   ~/devops-demos/scripts/catch-up.sh 04      # ready to start Lab 04
#
# It runs the commands from each earlier lab, does the Harness UI steps through
# the Harness API, and checks the results. Run it on a machine where you have not
# started the labs; it does not repair a half-finished lab.
set -euo pipefail
target=$((10#${1:?usage: catch-up.sh NN   (the number of the lab you want to start)}))
repo="$(cd "$(dirname "$0")/.." && pwd)"
labs=()
for f in "$repo"/labs/[0-9][0-9]-*.md; do
  n=$((10#$(basename "$f" | cut -c1-2)))
  if [ "$n" -lt "$target" ]; then labs+=("$f"); fi
done
if [ ${#labs[@]} -eq 0 ]; then echo "Nothing to replay before lab $1."; exit 0; fi
echo "Replaying ${#labs[@]} lab(s): ${labs[*]##*/}"
echo "This takes several minutes per lab. A log is written to ~/lab-runs/."
exec python3 "$repo/tests/run-lab.py" --catchup "${labs[@]}"
