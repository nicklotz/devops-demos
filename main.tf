erraform {
  required_version = ">= 1.0.0"
  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

resource "random_id" "server_id" {
  byte_length = 4
}

resource "null_resource" "create_output_dir" {
  provisioner "local-exec" {
    command = "mkdir -p ${path.module}/output"
  }
}

resource "local_file" "config" {
  filename = "${path.module}/output/server-config.txt"
  content  = <<-EOT
    Server Configuration
    ====================
    Server ID: ${random_id.server_id.hex}
    Environment: development
  EOT
  depends_on = [null_resource.create_output_dir]
}

output "server_id" {
  value = random_id.server_id.hex
}
