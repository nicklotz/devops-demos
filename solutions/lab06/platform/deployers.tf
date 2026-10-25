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
