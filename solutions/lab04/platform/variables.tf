variable "environments" {
  description = "Environments to create, with the resource limits of each namespace."
  type = map(object({
    cpu_limit    = string
    memory_limit = string
    max_pods     = number
  }))
  default = {
    dev = {
      cpu_limit    = "4"
      memory_limit = "4Gi"
      max_pods     = 10
    }
    prod = {
      cpu_limit    = "6"
      memory_limit = "6Gi"
      max_pods     = 15
    }
  }
}
