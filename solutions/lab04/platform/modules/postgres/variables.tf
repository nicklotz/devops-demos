variable "namespace" {
  description = "Namespace to create the database in."
  type        = string
}

variable "image" {
  description = "PostgreSQL container image."
  type        = string
  default     = "postgres:17-alpine"
}

variable "storage" {
  description = "Size of the data volume."
  type        = string
  default     = "1Gi"
}
