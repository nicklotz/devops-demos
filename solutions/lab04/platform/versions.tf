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
