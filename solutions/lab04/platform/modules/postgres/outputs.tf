output "secret_name" {
  description = "Name of the Secret with the connection settings."
  value       = kubernetes_secret_v1.db.metadata[0].name
}
