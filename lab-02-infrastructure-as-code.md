# Lab: Infrastructure as Code with Terraform & Ansible

## Overview

In this hands-on lab, you will:
- Install and use Terraform for infrastructure provisioning
- Learn Terraform workflow: init, plan, apply, destroy
- Manage infrastructure state and variables
- Install and use Ansible for configuration management
- Write Ansible playbooks to configure systems
- Integrate Terraform and Ansible for complete IaC workflows

## Prerequisites

- Ubuntu 24.04 VM (fresh installation)
- Terminal access to the VM
- Basic familiarity with Linux commands and YAML

## Time Required

Approximately 90-120 minutes

---

## Part 1: Environment Setup

### 1.2 Install Terraform

We'll install Terraform from HashiCorp's official repository.

```bash
# Install dependencies
sudo apt-get install -y gnupg software-properties-common curl

# Add HashiCorp GPG key
wget -O- https://apt.releases.hashicorp.com/gpg | \
    gpg --dearmor | \
    sudo tee /usr/share/keyrings/hashicorp-archive-keyring.gpg > /dev/null

# Add HashiCorp repository
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] \
    https://apt.releases.hashicorp.com $(lsb_release -cs) main" | \
    sudo tee /etc/apt/sources.list.d/hashicorp.list

# Install Terraform
sudo apt-get update
sudo apt-get install -y terraform

# Verify installation
terraform version
```

### 1.3 Install Ansible

We'll install Ansible system-wide for use with sudo.

```bash
# Install Ansible and dependencies
sudo apt-get install -y python3 ansible sshpass

# Verify installation
ansible --version | head -5
```

### 1.4 Install Docker (for later exercises)

We'll use Docker to simulate infrastructure that Terraform can provision.

```bash
# Install Docker
curl -fsSL https://get.docker.com | sudo sh

# Add current user to docker group
sudo usermod -aG docker $USER

# Start Docker service
sudo systemctl enable docker
sudo systemctl start docker

# Verify (using sudo for now, group membership takes effect on next login)
sudo docker --version
```

### 1.5 Create Working Directory

```bash
mkdir -p ~/iac-lab
cd ~/iac-lab
echo "Working directory: $(pwd)"
```

---

## Part 2: Terraform Fundamentals

### 2.1 Understanding HCL (HashiCorp Configuration Language)

Terraform uses HCL, a declarative language for defining infrastructure.

**Key concepts:**
- **Blocks**: Containers for configuration (resource, variable, output)
- **Arguments**: Settings within blocks (name = value)
- **Expressions**: Values that can be computed

### 2.2 Your First Terraform Configuration

Let's create a simple configuration using the `local` provider to create files.

```bash
mkdir -p ~/iac-lab/terraform-basics
cd ~/iac-lab/terraform-basics

cat > main.tf << 'EOF'
terraform {
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
EOF

echo "Created main.tf"
cat main.tf
```

### 2.3 Terraform Workflow: Init

The `terraform init` command initializes the working directory and downloads required providers.

```bash
cd ~/iac-lab/terraform-basics
terraform init
```

### 2.4 Terraform Workflow: Plan

The `terraform plan` command shows what changes Terraform will make.

```bash
cd ~/iac-lab/terraform-basics
terraform plan
```

### 2.5 Terraform Workflow: Apply

The `terraform apply` command executes the planned changes.

```bash
cd ~/iac-lab/terraform-basics
terraform apply -auto-approve
```

### 2.6 Verify the Results

```bash
cd ~/iac-lab/terraform-basics
echo "=== Generated Files ==="
ls -la output/
echo ""
echo "=== Config File Contents ==="
cat output/server-config.txt
echo ""
echo "=== Terraform Outputs ==="
terraform output
```

---

## Part 3: Terraform Variables and Outputs

### 3.1 Create a Configuration with Variables

```bash
mkdir -p ~/iac-lab/terraform-variables
cd ~/iac-lab/terraform-variables

cat > variables.tf << 'EOF'
variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "development"
}

variable "app_name" {
  description = "Application name"
  type        = string
  default     = "myapp"
}

variable "instance_count" {
  description = "Number of instances"
  type        = number
  default     = 2
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default = {
    project = "iac-lab"
    owner   = "devops-team"
  }
}
EOF

echo "Created variables.tf"
```

```bash
cd ~/iac-lab/terraform-variables

cat > main.tf << 'EOF'
terraform {
  required_providers {
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
  }
}

resource "local_file" "instance_config" {
  count    = var.instance_count
  filename = "${path.module}/configs/${var.app_name}-${var.environment}-${count.index + 1}.json"
  content  = jsonencode({
    instance_id = count.index + 1
    app_name    = var.app_name
    environment = var.environment
    tags        = var.tags
  })

  provisioner "local-exec" {
    command = "mkdir -p ${path.module}/configs"
  }
}

output "instance_files" {
  value = local_file.instance_config[*].filename
}
EOF

echo "Created main.tf"
```

### 3.2 Create a terraform.tfvars File

```bash
cd ~/iac-lab/terraform-variables

cat > terraform.tfvars << 'EOF'
environment    = "staging"
app_name       = "webserver"
instance_count = 3

tags = {
  project     = "iac-lab"
  owner       = "devops-team"
  cost_center = "engineering"
}
EOF

echo "Created terraform.tfvars:"
cat terraform.tfvars
```

### 3.3 Apply the Configuration

```bash
cd ~/iac-lab/terraform-variables
terraform init
terraform apply -auto-approve
```

```bash
cd ~/iac-lab/terraform-variables
echo "=== Created Files ==="
ls -la configs/
echo ""
echo "=== Instance Config Example ==="
cat configs/webserver-staging-1.json | python3 -m json.tool
```

---

## Part 4: Terraform State Management

### 4.1 Examine the State File

```bash
cd ~/iac-lab/terraform-variables
echo "=== State File Info ==="
ls -la terraform.tfstate
echo ""
echo "=== State Contents (first 30 lines) ==="
head -30 terraform.tfstate
```

### 4.2 Terraform State Commands

```bash
cd ~/iac-lab/terraform-variables
echo "=== List Resources in State ==="
terraform state list
echo ""
echo "=== Show Specific Resource ==="
terraform state show 'local_file.instance_config[0]'
```

---

## Part 5: Ansible Fundamentals

### 5.1 Create Ansible Working Directory

```bash
mkdir -p ~/iac-lab/ansible-basics
cd ~/iac-lab/ansible-basics
echo "Working directory: $(pwd)"
```

### 5.2 Create Ansible Inventory

```bash
cd ~/iac-lab/ansible-basics

cat > inventory.ini << 'EOF'
[local]
localhost ansible_connection=local

[all:vars]
ansible_python_interpreter=/usr/bin/python3
EOF

echo "Created inventory.ini:"
cat inventory.ini
```

### 5.3 Ansible Ad-Hoc Commands

```bash
cd ~/iac-lab/ansible-basics
echo "=== Ping all hosts ==="
ansible -i inventory.ini all -m ping
echo ""
echo "=== Run shell command ==="
ansible -i inventory.ini localhost -m shell -a 'hostname && uptime'
```

### 5.4 Your First Ansible Playbook

```bash
cd ~/iac-lab/ansible-basics

cat > setup-playbook.yml << 'EOF'
---
- name: Basic System Setup
  hosts: localhost
  connection: local
  become: no
  
  vars:
    app_name: "myapp"
    app_dir: "/tmp/{{ app_name }}"
  
  tasks:
    - name: Create application directory
      file:
        path: "{{ app_dir }}"
        state: directory
        mode: '0755'
    
    - name: Create subdirectories
      file:
        path: "{{ app_dir }}/{{ item }}"
        state: directory
      loop:
        - config
        - logs
        - data
    
    - name: Create version file
      copy:
        content: |
          Application: {{ app_name }}
          Version: 1.0.0
          Deployed: {{ ansible_date_time.iso8601 }}
        dest: "{{ app_dir }}/VERSION"
EOF

echo "Created setup-playbook.yml"
```

### 5.5 Run the Playbook

```bash
cd ~/iac-lab/ansible-basics
ansible-playbook -i inventory.ini setup-playbook.yml
```

```bash
echo "=== Verify Created Structure ==="
find /tmp/myapp -type f -o -type d
echo ""
echo "=== VERSION File ==="
cat /tmp/myapp/VERSION
```

---

## Part 6: Terraform + Ansible Integration

### 6.1 Set Up the Integration Project

```bash
mkdir -p ~/iac-lab/terraform-ansible-integration/{terraform,ansible}
cd ~/iac-lab/terraform-ansible-integration
echo "Project structure:"
find . -type d
```

### 6.2 Create Terraform Configuration for Docker Containers

```bash
cd ~/iac-lab/terraform-ansible-integration/terraform

cat > main.tf << 'EOF'
terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
  }
}

provider "docker" {
  host = "unix:///var/run/docker.sock"
}

variable "container_count" {
  default = 2
}

resource "docker_image" "ubuntu" {
  name         = "ubuntu:22.04"
  keep_locally = true
}

resource "docker_container" "webserver" {
  count   = var.container_count
  name    = "webserver-${count.index + 1}"
  image   = docker_image.ubuntu.image_id
  command = ["tail", "-f", "/dev/null"]
  
  labels {
    label = "managed_by"
    value = "terraform"
  }
}

resource "local_file" "ansible_inventory" {
  filename = "${path.module}/../ansible/inventory.ini"
  content  = <<-EOT
[webservers]
%{for c in docker_container.webserver~}
${c.name} ansible_connection=docker
%{endfor~}

[all:vars]
ansible_python_interpreter=/usr/bin/python3
  EOT
}

output "container_names" {
  value = docker_container.webserver[*].name
}
EOF

echo "Created Terraform configuration"
```

### 6.3 Apply Terraform to Create Containers

```bash
cd ~/iac-lab/terraform-ansible-integration/terraform
terraform init
```

```bash
cd ~/iac-lab/terraform-ansible-integration/terraform
sudo terraform apply -auto-approve
```

```bash
echo "=== Running Containers ==="
sudo docker ps --filter "label=managed_by=terraform"
echo ""
echo "=== Generated Ansible Inventory ==="
cat ~/iac-lab/terraform-ansible-integration/ansible/inventory.ini
```

### 6.4 Create Ansible Playbook to Configure Containers

```bash
cd ~/iac-lab/terraform-ansible-integration/ansible

cat > configure-webservers.yml << 'EOF'
---
- name: Configure Web Servers
  hosts: webservers
  gather_facts: no
  
  tasks:
    - name: Update apt cache
      raw: apt-get update
      changed_when: false
    
    - name: Install Python
      raw: apt-get install -y python3
      changed_when: false
    
    - name: Gather facts
      setup:
    
    - name: Create web directory
      file:
        path: /var/www/html
        state: directory
    
    - name: Create index page
      copy:
        content: |
          <h1>{{ inventory_hostname }}</h1>
          <p>Provisioned by Terraform, Configured by Ansible</p>
        dest: /var/www/html/index.html
    
    - name: Create server info
      copy:
        content: "hostname={{ inventory_hostname }}\n"
        dest: /etc/server-info
EOF

echo "Created configure-webservers.yml"
```

### 6.5 Run Ansible to Configure the Containers

```bash
cd ~/iac-lab/terraform-ansible-integration/ansible
sudo ansible-playbook -i inventory.ini configure-webservers.yml
```

### 6.6 Verify the Configuration

```bash
echo "=== webserver-1 index.html ==="
sudo docker exec webserver-1 cat /var/www/html/index.html
echo ""
echo "=== webserver-1 server-info ==="
sudo docker exec webserver-1 cat /etc/server-info
echo ""
echo "=== webserver-2 server-info ==="
sudo docker exec webserver-2 cat /etc/server-info
```

---

## Part 7: Cleanup

### 7.1 Destroy Terraform Resources

```bash
cd ~/iac-lab/terraform-ansible-integration/terraform
echo "=== Destroying Terraform Resources ==="
sudo terraform destroy -auto-approve
```

```bash
echo "=== Verify Containers Removed ==="
sudo docker ps --filter "label=managed_by=terraform"
echo "(Should show no containers)"
```

---

## Summary

In this lab, you learned:

### Terraform
- **HCL Syntax**: Blocks, arguments, expressions
- **Workflow**: init, plan, apply, destroy
- **Providers**: local, random, docker
- **Variables**: Input variables, tfvars files
- **State**: How Terraform tracks infrastructure

### Ansible
- **Inventory**: Defining hosts and groups
- **Ad-hoc Commands**: Quick tasks
- **Playbooks**: YAML-based automation

### Integration
- Terraform provisions infrastructure (Docker containers)
- Terraform generates Ansible inventory
- Ansible configures the provisioned resources

### Key Takeaways

1. **Terraform** = provisioning (creating resources)
2. **Ansible** = configuration management (configuring resources)
3. Together = complete Infrastructure as Code solution

---

**Congratulations!** You have completed the Infrastructure as Code lab!
