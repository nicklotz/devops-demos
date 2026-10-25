# Reference solutions

Each folder holds the files that a lab creates or changes, at the end of that lab. The paths inside each folder match your working copies:

- `labNN/flight-status/...` corresponds to `~/flight-status/...`
- `labNN/platform/...` corresponds to `~/platform/...`

A file appears in the folder of the lab that last changed it. For example, `.harness/ci.yaml` is in `lab02`, `lab03` and `lab09`, and the `lab09` version is the final one.

To compare one of your files with the reference:

```bash
diff ~/flight-status/.harness/ci.yaml ~/devops-demos/solutions/lab03/flight-status/.harness/ci.yaml
```

No output means the files are the same. Lines that start with `<` are only in your file, and lines that start with `>` are only in the reference.

Try to solve a lab step yourself before you look here. If you only want to reach the start of a later lab, use `scripts/catch-up.sh` instead (see the course README).
