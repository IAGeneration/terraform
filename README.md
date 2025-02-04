# Terraform Deployment API 🚀

<img src="Terraform_Logo.svg" alt="Terraform Logo" width="300px">

## 📌 Description
This repository provides a **FastAPI-based API** to dynamically create and manage Terraform-based Kubernetes clusters. It allows:
- 🚀 **Dynamic cluster creation** with Terraform
- 🔄 **Automatic repository and branch selection**
- ⚙️ **Custom environment variables for deployments**
- 🔥 **Easy cluster deletion with Terraform destroy**

## 📁 Directory Structure
```plaintext
terraform/
├── template/          # Template Terraform files
│   ├── main.tf
│   ├── vpc.tf
│   ├── gke.tf
│   ├── terraform.tfvars
├── main.py            # FastAPI service for managing Terraform clusters
├── README.md          # Project documentation
├── Terraform_Logo.svg # Terraform logo used in this README
```

# 🚀 Getting Started

## 1️⃣ Install Dependencies
Make sure you have Python and Terraform installed:
```bash
pip install fastapi uvicorn
```

## 2️⃣ Run the API Server
```bash
uvicorn main:app --reload
```

# 🛠 Technologies Used
- FastAPI (Python) for the API
- Terraform for infrastructure management
- Kubernetes for container orchestration
- GitHub for repository selection
