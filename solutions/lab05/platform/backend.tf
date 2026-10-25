# Store the state in a Kubernetes Secret (tfstate-default-platform) in the
# "terraform" namespace. The backend uses a Lease object as the state lock.
# It reads the kubeconfig file named in KUBE_CONFIG_PATH.
terraform {
  backend "kubernetes" {
    secret_suffix = "platform"
    namespace     = "terraform"
  }
}
