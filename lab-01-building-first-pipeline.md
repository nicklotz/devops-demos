# Lab: Building Your First CI/CD Pipeline

## Overview

In this hands-on lab, you will:
- Install and configure Jenkins on an Ubuntu VM
- Create a sample application with tests
- Build a CI/CD pipeline with Build, Test, and Deploy stages
- Trigger the pipeline and monitor execution
- Understand pipeline configuration and best practices

## Prerequisites

- Ubuntu 24.04 VM (fresh installation)
- Terminal access to the VM
- Basic familiarity with Linux commands

## Time Required

Approximately 60-90 minutes

---

## Part 1: Environment Setup

### 1.1 Update the System

First, let's ensure our system is up to date.

```bash
sudo apt-get update
```

### 1.2 Install Java (Required for Jenkins)

Jenkins requires Java 21 or newer to run. We'll install OpenJDK 21.

```bash
sudo apt-get install -y fontconfig openjdk-21-jre
java -version
```

### 1.3 Install Jenkins

We'll install Jenkins from the official repository.

```bash
# Add Jenkins repository key
sudo wget -O /usr/share/keyrings/jenkins-keyring.asc \
  https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key

# Add Jenkins repository
echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc]" \
  https://pkg.jenkins.io/debian-stable binary/ | sudo tee \
  /etc/apt/sources.list.d/jenkins.list > /dev/null

# Update and install Jenkins
sudo apt-get update
sudo apt-get install -y jenkins
```

### 1.4 Start Jenkins Service and Configure for Local Repositories

```bash
# Enable Jenkins to use local Git repositories (required for file:// URLs)
sudo mkdir -p /etc/systemd/system/jenkins.service.d
sudo tee /etc/systemd/system/jenkins.service.d/override.conf > /dev/null << 'EOF'
[Service]
Environment="JAVA_OPTS=-Dhudson.plugins.git.GitSCM.ALLOW_LOCAL_CHECKOUT=true"
EOF

sudo systemctl daemon-reload
sudo systemctl enable jenkins
sudo systemctl restart jenkins

# Wait for Jenkins to be ready
echo "Waiting for Jenkins to start..."
sleep 20

sudo systemctl status jenkins --no-pager | head -10
```

### 1.5 Get Initial Admin Password

Jenkins generates an initial admin password during installation. We need this to unlock Jenkins for the first time.

```bash
echo "============================================"
echo "Jenkins Initial Admin Password:"
echo "============================================"
sudo cat /var/lib/jenkins/secrets/initialAdminPassword
echo ""
echo "============================================"
```

### 1.6 Get VM IP Address

```bash
VM_IP=$(hostname -I | awk '{print $1}')
echo "============================================"
echo "Access Jenkins at: http://${VM_IP}:8080"
echo "============================================"
```

### 1.7 Configure Jenkins (Manual Steps)

**Open your web browser and navigate to the Jenkins URL shown above.**

1. Paste the initial admin password when prompted
2. Click "Install suggested plugins" and wait for installation
3. Create your admin user:
   - Username: `admin`
   - Password: `admin123` (or your choice)
   - Full name: `Administrator`
   - Email: `admin@localhost`
4. Accept the default Jenkins URL
5. Click "Start using Jenkins"

---

## Part 2: Install Additional Tools

### 2.1 Install Git

```bash
sudo apt-get install -y git
git --version
```

### 2.2 Install Node.js (for our sample application)

```bash
# Install Node.js 20.x LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
node --version
npm --version
```

---

## Part 3: Create a Sample Application

We'll create a simple Node.js web application with tests that we can use in our pipeline.

### 3.1 Create Project Directory

```bash
mkdir -p ~/sample-app
cd ~/sample-app
pwd
```

### 3.2 Create package.json

```bash
cat > ~/sample-app/package.json << 'EOF'
{
  "name": "sample-app",
  "version": "1.0.0",
  "description": "Sample application for CI/CD pipeline lab",
  "main": "src/app.js",
  "scripts": {
    "start": "node src/app.js",
    "test": "node test/test.js",
    "lint": "echo 'Linting completed successfully'",
    "build": "echo 'Build completed successfully' && mkdir -p dist && cp -r src/* dist/"
  },
  "author": "DevOps Lab",
  "license": "MIT"
}
EOF
cat ~/sample-app/package.json
```

### 3.3 Create the Application Code

```bash
mkdir -p ~/sample-app/src

cat > ~/sample-app/src/app.js << 'EOF'
const http = require('http');

const hostname = '0.0.0.0';
const port = 3000;

// Calculator functions
function add(a, b) {
    return a + b;
}

function subtract(a, b) {
    return a - b;
}

function multiply(a, b) {
    return a * b;
}

function divide(a, b) {
    if (b === 0) {
        throw new Error('Division by zero');
    }
    return a / b;
}

// Export functions for testing
module.exports = { add, subtract, multiply, divide };

// Only start server if this is the main module
if (require.main === module) {
    const server = http.createServer((req, res) => {
        res.statusCode = 200;
        res.setHeader('Content-Type', 'application/json');
        
        const response = {
            message: 'Welcome to Sample App!',
            version: '1.0.0',
            status: 'healthy',
            timestamp: new Date().toISOString()
        };
        
        res.end(JSON.stringify(response, null, 2));
    });

    server.listen(port, hostname, () => {
        console.log(`Server running at http://${hostname}:${port}/`);
    });
}
EOF

echo "Application created:"
cat ~/sample-app/src/app.js
```

### 3.4 Create Test Suite

```bash
mkdir -p ~/sample-app/test

cat > ~/sample-app/test/test.js << 'EOF'
const { add, subtract, multiply, divide } = require('../src/app.js');

let passed = 0;
let failed = 0;

function test(name, fn) {
    try {
        fn();
        console.log(`✓ ${name}`);
        passed++;
    } catch (error) {
        console.log(`✗ ${name}`);
        console.log(`  Error: ${error.message}`);
        failed++;
    }
}

function assertEqual(actual, expected) {
    if (actual !== expected) {
        throw new Error(`Expected ${expected}, but got ${actual}`);
    }
}

console.log('\n========================================');
console.log('Running Unit Tests');
console.log('========================================\n');

// Addition tests
test('add(2, 3) should return 5', () => {
    assertEqual(add(2, 3), 5);
});

test('add(-1, 1) should return 0', () => {
    assertEqual(add(-1, 1), 0);
});

test('add(0, 0) should return 0', () => {
    assertEqual(add(0, 0), 0);
});

// Subtraction tests
test('subtract(5, 3) should return 2', () => {
    assertEqual(subtract(5, 3), 2);
});

test('subtract(3, 5) should return -2', () => {
    assertEqual(subtract(3, 5), -2);
});

// Multiplication tests
test('multiply(4, 3) should return 12', () => {
    assertEqual(multiply(4, 3), 12);
});

test('multiply(0, 100) should return 0', () => {
    assertEqual(multiply(0, 100), 0);
});

// Division tests
test('divide(10, 2) should return 5', () => {
    assertEqual(divide(10, 2), 5);
});

test('divide(7, 2) should return 3.5', () => {
    assertEqual(divide(7, 2), 3.5);
});

test('divide by zero should throw error', () => {
    try {
        divide(10, 0);
        throw new Error('Expected error was not thrown');
    } catch (e) {
        if (e.message !== 'Division by zero') {
            throw e;
        }
    }
});

console.log('\n========================================');
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('========================================\n');

// Exit with error code if any tests failed
if (failed > 0) {
    process.exit(1);
}
EOF

echo "Test file created successfully"
```

### 3.5 Verify the Application Works

```bash
cd ~/sample-app

echo "=== Running Tests ==="
npm test

echo ""
echo "=== Running Build ==="
npm run build

echo ""
echo "=== Checking dist folder ==="
ls -la dist/
```

### 3.6 Initialize Git Repository

```bash
cd ~/sample-app

# Create .gitignore
cat > .gitignore << 'EOF'
node_modules/
dist/
*.log
.DS_Store
EOF

# Initialize git repository
git init
git config user.email "lab@devops.local"
git config user.name "DevOps Lab"
git add .
git commit -m "Initial commit: Sample application with tests"

echo ""
echo "Git repository initialized:"
git log --oneline
```

---

## Part 4: Create the Jenkins Pipeline

### 4.1 Create a Jenkinsfile

The Jenkinsfile defines our pipeline as code. This is a declarative pipeline with Build, Test, and Deploy stages.

```bash
cat > ~/sample-app/Jenkinsfile << 'EOF'
pipeline {
    agent any
    
    environment {
        APP_NAME = 'sample-app'
        BUILD_VERSION = "${BUILD_NUMBER}"
    }
    
    stages {
        stage('Checkout') {
            steps {
                echo "========================================"
                echo "Stage: Checkout"
                echo "========================================"
                echo "Checking out source code..."
                checkout scm
                sh 'ls -la'
            }
        }
        
        stage('Build') {
            steps {
                echo "========================================"
                echo "Stage: Build"
                echo "========================================"
                echo "Building ${APP_NAME} version ${BUILD_VERSION}..."
                sh '''
                    echo "Installing dependencies..."
                    npm install --production 2>/dev/null || echo "No dependencies to install"
                    
                    echo "Running build..."
                    npm run build
                    
                    echo "Build artifacts:"
                    ls -la dist/
                '''
            }
        }
        
        stage('Test') {
            steps {
                echo "========================================"
                echo "Stage: Test"
                echo "========================================"
                echo "Running automated tests..."
                sh '''
                    echo "Running unit tests..."
                    npm test
                    
                    echo "Running linter..."
                    npm run lint
                '''
            }
        }
        
        stage('Deploy') {
            steps {
                echo "========================================"
                echo "Stage: Deploy"
                echo "========================================"
                echo "Deploying ${APP_NAME} version ${BUILD_VERSION}..."
                sh '''
                    # Create deployment directory
                    DEPLOY_DIR="/tmp/deployments/${BUILD_NUMBER}"
                    mkdir -p $DEPLOY_DIR
                    
                    # Copy artifacts to deployment location
                    cp -r dist/* $DEPLOY_DIR/
                    
                    # Create deployment manifest
                    cat > $DEPLOY_DIR/manifest.json << MANIFEST
{
    "app": "sample-app",
    "version": "1.0.${BUILD_NUMBER}",
    "build": "${BUILD_NUMBER}",
    "deployed_at": "$(date -Iseconds)",
    "status": "deployed"
}
MANIFEST
                    
                    echo "Deployment complete!"
                    echo "Deployed to: $DEPLOY_DIR"
                    ls -la $DEPLOY_DIR/
                    echo "Manifest:"
                    cat $DEPLOY_DIR/manifest.json
                '''
            }
        }
    }
    
    post {
        always {
            echo "========================================"
            echo "Pipeline Complete"
            echo "========================================"
            echo "Build: ${BUILD_NUMBER}"
            echo "Result: ${currentBuild.currentResult}"
        }
        success {
            echo "SUCCESS: All stages completed successfully!"
        }
        failure {
            echo "FAILURE: Pipeline failed. Check the logs above."
        }
    }
}
EOF

echo "Jenkinsfile created:"
cat ~/sample-app/Jenkinsfile
```

### 4.2 Commit the Jenkinsfile

```bash
cd ~/sample-app
git add Jenkinsfile
git commit -m "Add Jenkinsfile for CI/CD pipeline"

echo ""
echo "Git history:"
git log --oneline
```

### 4.3 Set Repository Permissions for Jenkins

Jenkins runs as the `jenkins` user, which needs read access to our repository. We need to adjust permissions on both the home directory and the sample-app directory.

```bash
# Allow Jenkins to access the home directory and sample-app
chmod 755 ~
chmod -R 755 ~/sample-app

# Configure git safe directory for Jenkins user (required for Git 2.35.2+)
# This allows Jenkins to access repositories owned by other users
sudo -u jenkins git config --global --add safe.directory '*'

echo "============================================"
echo "Repository path for Jenkins:"
echo "file:///home/training/sample-app"
echo "============================================"
echo ""
echo "Directory permissions:"
ls -la ~/sample-app
```

---

## Part 5: Configure Jenkins Pipeline Job

### 5.1 Create the Pipeline Job in Jenkins (Manual Steps)

**In your web browser, go to Jenkins (http://VM_IP:8080):**

1. Click **"New Item"** on the left sidebar
2. Enter name: `sample-app-pipeline`
3. Select **"Pipeline"** (not "Multibranch Pipeline")
4. Click **"OK"**

### 5.2 Configure the Pipeline

**In the Pipeline configuration page:**

1. Scroll down to the **"Pipeline"** section
2. For **"Definition"**, select: **"Pipeline script from SCM"**
3. For **"SCM"**, select: **"Git"**
4. For **"Repository URL"**, enter the path shown below:

```
file:///home/training/sample-app
```

5. For **"Branch Specifier"**, change to: `*/master`
   - Note: Git defaults to `master` on Ubuntu. If you see `main` in your git log, use `*/main` instead.
6. **"Script Path"** should be: `Jenkinsfile`
7. Click **"Save"**

---

## Part 6: Run the Pipeline

### 6.1 Trigger the First Build (Manual Step)

1. From the pipeline job page, click **"Build Now"** on the left sidebar
2. Watch the build progress in the **"Build History"** section
3. Click on the build number (e.g., **#1**) to see details
4. Click **"Console Output"** to see the full log

### 6.2 Verify Deployment

```bash
echo "Checking deployments directory:"
ls -la /tmp/deployments/ 2>/dev/null || echo "No deployments yet - run the pipeline first!"

# Show the latest deployment if it exists
if [ -d "/tmp/deployments" ]; then
    LATEST=$(ls -t /tmp/deployments/ | head -1)
    if [ -n "$LATEST" ]; then
        echo ""
        echo "Latest deployment (#$LATEST):"
        ls -la /tmp/deployments/$LATEST/
        echo ""
        echo "Manifest:"
        cat /tmp/deployments/$LATEST/manifest.json
    fi
fi
```

---

## Part 7: Pipeline Modifications and Experiments

### 7.1 Experiment: Break the Tests

Let's see what happens when tests fail. Modify the application to introduce a bug:

```bash
cd ~/sample-app

# Introduce a bug in the add function
sed -i 's/return a + b;/return a - b; \/\/ BUG: subtraction instead of addition/' src/app.js

# Commit the change
git add .
git commit -m "Introduce bug for testing pipeline failure"

echo "Bug introduced! The add function now subtracts instead of adds."
echo ""
echo "Go to Jenkins and click 'Build Now' to see the pipeline fail."
```

**Now go to Jenkins and run the pipeline again. You should see it fail at the Test stage!**

### 7.2 Fix the Bug

```bash
cd ~/sample-app

# Fix the bug
sed -i 's/return a - b; \/\/ BUG: subtraction instead of addition/return a + b;/' src/app.js

# Commit the fix
git add .
git commit -m "Fix addition bug"

echo "Bug fixed! Run the pipeline again to verify."
git log --oneline -3
```

### 7.3 Add a New Stage: Code Quality

Let's enhance our pipeline with a code quality stage:

```bash
cat > ~/sample-app/Jenkinsfile << 'EOF'
pipeline {
    agent any
    
    environment {
        APP_NAME = 'sample-app'
        BUILD_VERSION = "${BUILD_NUMBER}"
    }
    
    stages {
        stage('Checkout') {
            steps {
                echo "========================================"
                echo "Stage: Checkout"
                echo "========================================"
                checkout scm
                sh 'ls -la'
            }
        }
        
        stage('Build') {
            steps {
                echo "========================================"
                echo "Stage: Build"
                echo "========================================"
                sh '''
                    npm install --production 2>/dev/null || echo "No dependencies"
                    npm run build
                    ls -la dist/
                '''
            }
        }
        
        stage('Code Quality') {
            steps {
                echo "========================================"
                echo "Stage: Code Quality"
                echo "========================================"
                sh '''
                    echo "Running code quality checks..."
                    
                    # Count lines of code
                    echo "Lines of code:"
                    find src -name "*.js" -exec wc -l {} + | tail -1
                    
                    # Check for TODO comments
                    echo "\nTODO comments found:"
                    grep -r "TODO" src/ || echo "No TODO comments found"
                    
                    # Check for console.log statements
                    echo "\nConsole.log statements:"
                    grep -r "console.log" src/ || echo "No console.log found"
                    
                    echo "\nCode quality checks completed!"
                '''
            }
        }
        
        stage('Test') {
            steps {
                echo "========================================"
                echo "Stage: Test"
                echo "========================================"
                sh '''
                    npm test
                    npm run lint
                '''
            }
        }
        
        stage('Deploy') {
            steps {
                echo "========================================"
                echo "Stage: Deploy"
                echo "========================================"
                sh '''
                    DEPLOY_DIR="/tmp/deployments/${BUILD_NUMBER}"
                    mkdir -p $DEPLOY_DIR
                    cp -r dist/* $DEPLOY_DIR/
                    
                    cat > $DEPLOY_DIR/manifest.json << MANIFEST
{
    "app": "sample-app",
    "version": "1.0.${BUILD_NUMBER}",
    "build": "${BUILD_NUMBER}",
    "deployed_at": "$(date -Iseconds)",
    "status": "deployed"
}
MANIFEST
                    
                    echo "Deployed to: $DEPLOY_DIR"
                    cat $DEPLOY_DIR/manifest.json
                '''
            }
        }
    }
    
    post {
        always {
            echo "Pipeline finished with status: ${currentBuild.currentResult}"
        }
        success {
            echo "SUCCESS: All stages completed!"
        }
        failure {
            echo "FAILURE: Check logs for details."
        }
    }
}
EOF

cd ~/sample-app
git add Jenkinsfile
git commit -m "Add Code Quality stage to pipeline"

echo "Enhanced Jenkinsfile committed! Run the pipeline again."
```

### 7.4 Add Parallel Stages

Parallel stages can speed up your pipeline by running independent tasks simultaneously:

```bash
cat > ~/sample-app/Jenkinsfile << 'EOF'
pipeline {
    agent any
    
    environment {
        APP_NAME = 'sample-app'
        BUILD_VERSION = "${BUILD_NUMBER}"
    }
    
    stages {
        stage('Checkout') {
            steps {
                echo "Checking out source code..."
                checkout scm
            }
        }
        
        stage('Build') {
            steps {
                echo "Building application..."
                sh '''
                    npm install --production 2>/dev/null || true
                    npm run build
                '''
            }
        }
        
        stage('Quality Gates') {
            parallel {
                stage('Unit Tests') {
                    steps {
                        echo "Running unit tests..."
                        sh 'npm test'
                    }
                }
                
                stage('Lint') {
                    steps {
                        echo "Running linter..."
                        sh 'npm run lint'
                    }
                }
                
                stage('Security Check') {
                    steps {
                        echo "Running security checks..."
                        sh '''
                            echo "Checking for hardcoded secrets..."
                            ! grep -r "password" src/ || echo "Warning: Possible hardcoded password"
                            ! grep -r "api_key" src/ || echo "Warning: Possible hardcoded API key"
                            echo "Security check completed"
                        '''
                    }
                }
            }
        }
        
        stage('Deploy') {
            steps {
                echo "Deploying application..."
                sh '''
                    DEPLOY_DIR="/tmp/deployments/${BUILD_NUMBER}"
                    mkdir -p $DEPLOY_DIR
                    cp -r dist/* $DEPLOY_DIR/
                    
                    cat > $DEPLOY_DIR/manifest.json << MANIFEST
{
    "app": "${APP_NAME}",
    "version": "1.0.${BUILD_NUMBER}",
    "deployed_at": "$(date -Iseconds)"
}
MANIFEST
                    echo "Deployed successfully!"
                '''
            }
        }
    }
    
    post {
        success {
            echo "Pipeline completed successfully!"
        }
        failure {
            echo "Pipeline failed!"
        }
    }
}
EOF

cd ~/sample-app
git add Jenkinsfile
git commit -m "Add parallel quality gate stages"

echo "Parallel stages Jenkinsfile committed!"
echo "Run the pipeline and notice the parallel execution in the Stage View."
```

---

## Part 8: View Pipeline Visualization

### 8.1 Install Blue Ocean Plugin (Optional)

Blue Ocean provides a modern, visual interface for Jenkins pipelines.

**In Jenkins:**
1. Go to **Manage Jenkins** > **Plugins**
2. Click **Available plugins**
3. Search for **"Blue Ocean"**
4. Check the box and click **Install**
5. After installation, access via the **"Open Blue Ocean"** link in the sidebar

---

## Part 9: Cleanup

```bash
# Clean up deployments (optional)
echo "Deployment history:"
ls -la /tmp/deployments/ 2>/dev/null || echo "No deployments found"

# Uncomment to clean up:
# rm -rf /tmp/deployments/*
# echo "Deployments cleaned up"
```

---

## Summary

In this lab, you learned how to:

1. **Install and configure Jenkins** on an Ubuntu VM
2. **Create a sample application** with source code and tests
3. **Write a Jenkinsfile** defining a CI/CD pipeline
4. **Configure pipeline stages**: Checkout, Build, Test, Deploy
5. **Handle pipeline failures** when tests fail
6. **Add parallel stages** for improved performance
7. **View pipeline execution** and logs

### Key Takeaways

- **Pipeline as Code**: Jenkinsfile allows version-controlled, reproducible pipelines
- **Stages**: Organize work into logical steps (Build → Test → Deploy)
- **Fail Fast**: Tests catch bugs before deployment
- **Parallel Execution**: Independent tasks can run simultaneously
- **Post Actions**: Handle success/failure notifications

### Next Steps

- Explore Jenkins plugins for code coverage, notifications
- Add deployment to staging and production environments
- Integrate with Git webhooks for automatic triggers
- Add manual approval gates for production deployments

---

## Appendix: Jenkins CLI Commands

```bash
echo "Useful Jenkins management commands:"
echo ""
echo "# Check Jenkins status"
echo "sudo systemctl status jenkins"
echo ""
echo "# Restart Jenkins"
echo "sudo systemctl restart jenkins"
echo ""
echo "# View Jenkins logs"
echo "sudo journalctl -u jenkins -f"
echo ""
echo "# Jenkins home directory"
echo "ls /var/lib/jenkins/"
```

---

**Congratulations!** You have successfully completed the CI/CD Pipeline lab!
