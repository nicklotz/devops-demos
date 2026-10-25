# One PostgreSQL database per environment, built from the local module.
module "postgres" {
  source   = "./modules/postgres"
  for_each = var.environments

  namespace = kubernetes_namespace_v1.env[each.key].metadata[0].name
}
