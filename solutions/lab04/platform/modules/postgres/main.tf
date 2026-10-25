# A single PostgreSQL instance for one environment.
# Terraform generates the password and stores it, with a ready-made
# DATABASE_URL for the application, in the Secret "flight-status-db".

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "kubernetes_secret_v1" "db" {
  metadata {
    name      = "flight-status-db"
    namespace = var.namespace
  }
  data = {
    POSTGRES_USER     = "flights"
    POSTGRES_PASSWORD = random_password.db.result
    POSTGRES_DB       = "flights"
    DATABASE_URL      = "postgresql://flights:${random_password.db.result}@postgres:5432/flights"
  }
}

resource "kubernetes_persistent_volume_claim_v1" "db" {
  metadata {
    name      = "postgres-data"
    namespace = var.namespace
  }
  spec {
    access_modes = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = var.storage
      }
    }
  }
  # k3d's local-path storage creates the volume only when a pod uses it.
  wait_until_bound = false
}

resource "kubernetes_deployment_v1" "db" {
  metadata {
    name      = "postgres"
    namespace = var.namespace
    labels = {
      app = "postgres"
    }
  }
  spec {
    replicas = 1
    # Stop the old pod before starting a new one: the volume allows one writer.
    strategy {
      type = "Recreate"
    }
    selector {
      match_labels = {
        app = "postgres"
      }
    }
    template {
      metadata {
        labels = {
          app = "postgres"
        }
      }
      spec {
        container {
          name  = "postgres"
          image = var.image
          # POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB come from the Secret.
          env_from {
            secret_ref {
              name = kubernetes_secret_v1.db.metadata[0].name
            }
          }
          env {
            name  = "PGDATA"
            value = "/var/lib/postgresql/data/pgdata"
          }
          port {
            container_port = 5432
          }
          readiness_probe {
            exec {
              command = ["pg_isready", "-U", "flights"]
            }
            period_seconds = 5
          }
          resources {
            requests = {
              cpu    = "100m"
              memory = "128Mi"
            }
            limits = {
              cpu    = "1"
              memory = "512Mi"
            }
          }
          volume_mount {
            name       = "data"
            mount_path = "/var/lib/postgresql/data"
          }
        }
        volume {
          name = "data"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.db.metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_service_v1" "db" {
  metadata {
    name      = "postgres"
    namespace = var.namespace
  }
  spec {
    selector = {
      app = "postgres"
    }
    port {
      port        = 5432
      target_port = 5432
    }
  }
}
