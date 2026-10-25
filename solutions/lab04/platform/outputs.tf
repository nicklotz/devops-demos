output "namespaces" {
  description = "Namespaces created for the environments."
  value       = [for ns in kubernetes_namespace_v1.env : ns.metadata[0].name]
}

output "database_secrets" {
  description = "Secret in each namespace that holds the database connection settings."
  value       = { for env, db in module.postgres : env => db.secret_name }
}
