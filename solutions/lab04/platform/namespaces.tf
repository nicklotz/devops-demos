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
