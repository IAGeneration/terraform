import os
import shutil
import subprocess
import json
from datetime import datetime
from pathlib import Path
import shutil
import time
import google.auth
from google.auth.transport.requests import Request
from google.cloud import storage

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException,APIRouter
# from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
# from starlette.responses import HTMLResponse
from typing import List, Dict, Optional
from fastapi.openapi.docs import get_swagger_ui_html



#Define base directories
CLUSTERS_BASE_DIR = Path('/home/whirldata/Generation5/terraform/clusters')
TEMPLATE_DIR = Path('/home/whirldata/Generation5/terraform/template')  # Modify this path to point to your template directory
WAIT_TIMEOUT = 60  # Max wait time for files to appear in seconds
WAIT_INTERVAL = 5  # Wait interval between checks in seconds


app = FastAPI(
    title="Auto Deploy Terraform",
    version="1.0.0",
    docs_url=None,  # Disable default docs to avoid conflicts
    redoc_url=None
)

general_router = APIRouter(tags=["🚀 PAAS API"])  
app.mount("/static", StaticFiles(directory="."), name="static")


# --------- Data Schemas ---------

# class RepoConfig(BaseModel):
#     repo: str
#     branch: str
#     env: Optional[Dict[str, str]] = None

class CreateClusterRequest(BaseModel):
    name: str
    region: str
    #repositories: List[RepoConfig]

    

class UpdateSettingsRequest(BaseModel):
    """
    Example schema for updating the configuration (params.json).
    Adapt according to your Terraform variables or format.
    """
    # You can imagine other fields: region, zone, etc.
    name: Optional[str] = None
    # repositories: Optional[List[RepoConfig]] = None


# --------- Global Configuration ---------

BASE_DIR = Path(__file__).parent.resolve()
TEMPLATE_DIR = BASE_DIR / "template"
CLUSTERS_BASE_DIR = BASE_DIR / "clusters"


# --------- Endpoints ---------


# Function to serve documentation with a custom style


# --------- Custom Swagger UI ---------
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=app.title,
        swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
        swagger_css_url="/static/style.css",
        swagger_ui_parameters={"defaultModelsExpandDepth": -1}
    )


# --------- OpenAPI Route ---------
@app.get("/openapi.json", include_in_schema=False)
async def get_open_api_endpoint():
    return get_openapi(
        title=app.title,
        version="1.0.0",
        description=app.description,
        routes=app.routes
    )



# Path to your service account key JSON file
service_account_file = "/home/whirldata/Generation5/terraform/template/terraform-key.json"

# Use the service account to authenticate and create a Google Cloud client
credentials, project = google.auth.load_credentials_from_file(service_account_file)

# If credentials are expired, refresh them
if credentials.expired and credentials.refresh_token:
    credentials.refresh(Request())

# Now, you can use the credentials to interact with Google Cloud APIs
storage_client = storage.Client(credentials=credentials, project=project)

################################## Creating a Cluster ############################################
@general_router.post("/create/{cluster_name/{cluster_region}")
def create_cluster(request: CreateClusterRequest):
    """
    Creates a new Terraform cluster by:
      1) Duplicating the template/ folder into clusters/<name>/
      2) Replacing '##name##' and '##region##' in the content of files
      3) Generating a params.json file with the received info
      4) Creating a .env file for each repository
      5) Running terraform init && terraform apply
      6) Logging the activity
    """
    name = request.name
    region = request.region
    new_cluster_dir = CLUSTERS_BASE_DIR / name

    # Check if the cluster already exists
    if new_cluster_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=f"The cluster '{name}' already exists."
        )

    # Step 1: Create the directory for the new cluster and log activity
    try:
        # log_activity(name, "Cluster creation started.")
        new_cluster_dir.mkdir(parents=True, exist_ok=True)

        # Copy the template/ to clusters/<name>/
        shutil.copytree(TEMPLATE_DIR, new_cluster_dir / "template")
        # Copy the terraform-key.json file to the new cluster directory
        shutil.copy2(TEMPLATE_DIR / "terraform-key.json", new_cluster_dir / "terraform-key.json")
        # log_activity(name, "Template copied successfully.")
        # Ensure that files were copied correctly before moving forward
        if not (new_cluster_dir / "template").exists():
            raise HTTPException(
                status_code=500,
                detail="Template files were not copied successfully."
            )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error while copying the template: {str(e)}"
        )

    # 2) Replace ##name## and ##region## in the files (including terraform.tfvars)
    try:
        replace_placeholder_in_directory(new_cluster_dir, "cluster-name", name)
        replace_placeholder_in_directory(new_cluster_dir, "cluster-region", region)
    except Exception as e:
        # log_activity(name, f"Creation failed: placeholder replacement error. {str(e)}")
        shutil.rmtree(new_cluster_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error while replacing placeholders: {str(e)}"
        )

    # 3) Generate a params.json file
    try:
        params_file = new_cluster_dir / "params.json"
        with open(params_file, "w", encoding="utf-8") as f:
            json.dump(request.dict(), f, indent=4)
    except Exception as e:
        # log_activity(name, f"Creation failed: error writing params.json. {str(e)}")
        shutil.rmtree(new_cluster_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error while creating params.json: {str(e)}"
        )

    # 4) Run terraform init && terraform apply
    try:
                # Ensure that the necessary files are in place before running terraform
        template_dir = new_cluster_dir / "template"
        if not check_files_ready(template_dir, ".tf", WAIT_TIMEOUT, WAIT_INTERVAL):
            raise HTTPException(
                status_code=500,
                detail="Terraform files are missing or incomplete after waiting."
            )
        run_terraform_init_and_apply(new_cluster_dir / "template")
    except Exception as e:
        # log_activity(name, f"Creation failed: terraform apply. {str(e)}")
        shutil.rmtree(new_cluster_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Error during terraform apply: {str(e)})")

    # If everything went well
    return {"message": f"Cluster '{name}' in region '{region}' created successfully."}
    # If everything went well
    # log_activity(name, "Cluster successfully created.")
    # return {"message": f"Cluster '{name}' in region '{region}' created successfully."}

################################## Delete Cluster #################################################

@general_router.delete("/delete/{cluster_name}")
def delete_cluster(cluster_name: str):
    """
    Deletes an existing Terraform cluster by:
      1) Running terraform destroy to tear down the infrastructure
      2) Deleting the cluster directory and its contents
      3) Logging the activity
    """
    cluster_dir = CLUSTERS_BASE_DIR / cluster_name

    # Check if the cluster exists
    if not cluster_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"The cluster '{cluster_name}' does not exist."
        )

    # Step 1: Run terraform destroy
    try:
        template_dir = cluster_dir / "template"
        if not template_dir.exists():
            raise HTTPException(
                status_code=500,
                detail="Terraform template directory is missing."
            )

        # Run terraform destroy
        run_terraform_destroy(template_dir)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during terraform destroy: {str(e)}"
        )

    # Step 2: Delete the cluster directory
    try:
        shutil.rmtree(cluster_dir)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error while deleting the cluster directory: {str(e)}"
        )

    # If everything went well
    return {"message": f"Cluster '{cluster_name}' deleted successfully."}

def run_terraform_destroy(template_dir: Path):
    """
    Runs `terraform destroy` in the specified directory.
    """
    try:
        # Change to the template directory
        original_dir = Path.cwd()
        os.chdir(template_dir)

        # Run terraform destroy
        subprocess.run(["terraform", "destroy", "-auto-approve"], check=True)
    except subprocess.CalledProcessError as e:
        raise Exception(f"Terraform destroy failed: {str(e)}")
    finally:
        # Change back to the original directory
        os.chdir(original_dir)

############################  Deploy_Ansible  ######################################################

# Define the DeployRequest model with cluster_name, playbook, and branch
class DeployRequest(BaseModel):
    cluster_name: str
    pod: str  # Referring to the playbook
    branch: str

# Map the human-readable pod names to their corresponding Ansible playbook filenames
PLAYBOOK_OPTIONS = {
    "API": "deploy-api.yml",
    "POSTGRES": "deploy-postgres.yml",
    "REDIS": "deploy-redis.yml",
    "QDRANT": "deploy-qdrant-qdrantfastapi.yml",
    "CELERY": "deploy-celery.yml",
    "WEBSOCKET": "deploy-websocket.yml",
    "SEARCH": "deploy-search.yml"
}

BRANCH_OPTIONS = ["main", "test"]  # Predefined branch options

@general_router.post("/deploy")
def deploy_to_cluster(request: DeployRequest):
    """
    Deploys Ansible playbooks to a selected cluster by:
      1) Listing available clusters (excluding 'futurandco')
      2) Selecting the cluster and playbook to deploy
      3) Running the Ansible playbooks from the local ansible/ folder
    """
    cluster_name = request.cluster_name
    playbook_name = PLAYBOOK_OPTIONS.get(request.pod)
    branch = request.branch
    ansible_dir = Path("ansible")  # Local directory containing Ansible playbooks
    clusters_base_dir = Path("clusters")  # Base directory for clusters

    # Step 1: List available clusters, excluding 'futurandco'
    clusters = list_clusters()

    # Step 2: Check if the selected cluster exists and is not 'futurandco' 
    if cluster_name not in clusters or cluster_name == "futurandco":
        raise HTTPException(
            status_code=404,
            detail=f"Cluster '{cluster_name}' not found or excluded."
        )

    # Step 3: Ensure the inventory folder exists for the selected cluster
    inventory_dir = clusters_base_dir / cluster_name / "inventory"
    inventory_dir.mkdir(parents=True, exist_ok=True)  # Create the inventory folder if it doesn't exist

    inventry_file =inventory_dir / "hosts.ini"
    if not inventry_file.exists():
        with open(inventry_file,"w") as f:
            f.write(f"[gke_cluster]\n{cluster_name}-gke\n")

    # Step 4: Deploy the selected Ansible playbook to the selected cluster
    try:
        # Change to the Ansible directory
        original_dir = os.getcwd()  # Save the original working directory
        os.chdir(ansible_dir)

        # Checkout the specified branch
        subprocess.run(["git", "checkout", branch], check=True)

        # Run the selected Ansible playbook
        playbook_command = [
            "ansible-playbook",
            "-i", str(inventory_dir),  # Assuming you have an inventory file per cluster
            playbook_name  # Selected playbook
        ]
        subprocess.run(playbook_command, check=True)

    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during Ansible playbook execution: {str(e)}"
        )
    finally:
        os.chdir(original_dir)  # Restore the original working directory

    return {"message": f"Ansible playbook '{playbook_name}' deployed to cluster '{cluster_name}' on branch '{branch}' successfully."}


def list_clusters() -> List[str]:
    """
    Lists all available clusters by scanning the clusters/ directory, excluding 'futurandco'.
    """
    clusters_base_dir = Path("clusters")
    clusters = []
    for cluster_dir in clusters_base_dir.iterdir():
        if cluster_dir.is_dir() and cluster_dir.name != "futurandco":
            clusters.append(cluster_dir.name)
    return clusters


def get_playbook_options() -> Dict[str, str]:
    """
    Returns a dictionary of human-readable playbook options mapped to filenames.
    """
    return PLAYBOOK_OPTIONS


def get_branch_options() -> List[str]:
    """
    Returns the predefined branch options.
    """
    return BRANCH_OPTIONS

##################################################################################

# @general_router.get("/list")
# def list_clusters():
    """
    Returns the list of clusters present in the `CLUSTERS_BASE_DIR` folder.
    A cluster is identified by a folder.
    """
    if not CLUSTERS_BASE_DIR.exists():
        return {"clusters": []}

    # Get subdirectories (only directories, not files)
    clusters = []
    for item in CLUSTERS_BASE_DIR.iterdir():
        if item.is_dir():
            clusters.append(item.name)

    return {"clusters": clusters}


# @general_router.delete("/delete/{name}")
# def delete_cluster_path(name: str):
    """
    Deletes a Terraform cluster by specifying the name in the URL (classic REST).
    Example: DELETE /delete/test
    """
    return perform_delete_cluster(name)


# @general_router.get("/activity/{name}")
# def get_activity(name: str):
#     """
#     Returns the content of the activity.log file for the <name> cluster.
#     Allows tracking the deployment progress: ongoing, created, error, etc.
#     """
#     cluster_dir = CLUSTERS_BASE_DIR / name
#     if not cluster_dir.exists():
#         raise HTTPException(status_code=404, detail="Cluster does not exist.")

#     log_file = cluster_dir / "activity.log"
#     if not log_file.exists():
#         # No logs yet
#         return {"activity": []}

#     with open(log_file, "r", encoding="utf-8") as f:
#         lines = f.readlines()

#     # Return each line as a distinct event or parse a JSON format if more structure is needed
#     return {"activity": [line.strip() for line in lines]}



# @general_router.get("/settings/{name}")
# def get_settings(name: str):
    """
    Retrieves the content of params.json for a given cluster.
    You can adapt this to read terraform.tfvars if needed.
    """
    cluster_dir = CLUSTERS_BASE_DIR / name
    if not cluster_dir.exists():
        raise HTTPException(status_code=404, detail="Cluster does not exist.")

    params_file = cluster_dir / "params.json"
    if not params_file.exists():
        raise HTTPException(status_code=404, detail="params.json file does not exist.")

    with open(params_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


# @general_router.put("/settings/{name}")
# def update_settings(name: str, updated: UpdateSettingsRequest):
    """
    Partially updates the configuration (params.json) of a cluster,
    then optionally reruns terraform apply if desired.
    """
    cluster_dir = CLUSTERS_BASE_DIR / name
    if not cluster_dir.exists():
        raise HTTPException(status_code=404, detail="Cluster does not exist.")

    params_file = cluster_dir / "params.json"
    if not params_file.exists():
        raise HTTPException(status_code=404, detail="params.json file does not exist.")

    # Read the existing config
    with open(params_file, "r", encoding="utf-8") as f:
        current_data = json.load(f)

    # Merge the fields
    # For example, if updated.name is not null, we overwrite it
    if updated.name is not None:
        current_data["name"] = updated.name
    if updated.repositories is not None:
        # Completely replace the list of repositories
        current_data["repositories"] = [r.dict() for r in updated.repositories]

    # Write the new config
    with open(params_file, "w", encoding="utf-8") as f:
        json.dump(current_data, f, indent=4)


    # Optional: you can rerun a terraform apply to take into account
    # the new variables if relevant
    try:
        log_activity(name, "Updating settings, rerunning Terraform.")
        run_terraform_init_and_apply(cluster_dir)
        log_activity(name, "Update completed successfully.")
    except Exception as e:
        log_activity(name, f"Error during settings update: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": f"Settings for cluster '{name}' updated successfully."}



# --------- Utility Functions ---------

# def ignore_files(dir, files):
#     ignored_files = ['activity.log']
#     ignored = [f for f in files if f in ignored_files]
#     if ignored:
#         print(f"Ignored files: {ignored} in directory {dir}")
#     return ignored

def safe_copytree(src, dst, ignore):
    # Ensure activity.log is skipped if it exists
    if os.path.exists(src / "activity.log"):
        print("activity.log found, skipping copy.")
    else:
        shutil.copytree(src, dst, ignore=ignore)


# def perform_delete_cluster(name: str):
    """
    Common logic to delete a cluster:
     1) check existence
     2) terraform destroy
     3) delete the folder
     4) log the activity
    """
    cluster_dir = CLUSTERS_BASE_DIR / name
    if not cluster_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=f"The cluster '{name}' does not exist."
        )

    log_activity(name, "Cluster deletion started.")

    # 1) Terraform destroy
    try:
        run_terraform_destroy(cluster_dir)
    except Exception as e:
        log_activity(name, f"Suppression échouée : terraform destroy. {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    # 2) Delete the folder
    try:
        shutil.rmtree(cluster_dir)
    except Exception as e:
        log_activity(name, f"Suppression échouée : {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la suppression du dossier: {str(e)}"
        )

    log_activity(name, "Cluster supprimé avec succès.")
    return {"message": f"Cluster '{name}' supprimé avec succès."}

def replace_placeholder_in_directory(directory, placeholder, value):
    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            content = content.replace(f"##{placeholder}##", value)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)


def run_terraform_init_and_apply(directory: Path):
    """
    Runs `terraform init` followed by `terraform apply -auto-approve`
    in the specified directory.
    """
    init_cmd = ["terraform", "init"]
    apply_cmd = ["terraform", "apply", "-auto-approve"]

    # Terraform init
    process_init = subprocess.run(
        init_cmd, cwd=str(directory), capture_output=True, text=True
    )
    if process_init.returncode != 0:
        raise Exception(f"Error during terraform init:\n{process_init.stderr}")

    # Terraform apply
    process_apply = subprocess.run(
        apply_cmd, cwd=str(directory), capture_output=True, text=True
    )
    if process_apply.returncode != 0:
        raise Exception(f"Error during terraform apply:\n{process_apply.stderr}")

# def run_terraform_destroy(directory: Path):
#     """
#     Runs `terraform destroy -auto-approve` in the specified directory.
#     """
#     destroy_cmd = ["terraform", "destroy", "-auto-approve"]
#     process_destroy = subprocess.run(
#         destroy_cmd, cwd=str(directory), capture_output=True, text=True
#     )
#     if process_destroy.returncode != 0:
#         raise Exception(f"Error during terraform destroy:\n{process_destroy.stderr}")


def log_activity(cluster_name: str, message: str):
    """
    Adds a log message (e.g., "Creation in progress", "Successfully created", "Error", etc.)
    in the activity.log file of the concerned cluster, with a timestamp.
    """
    cluster_dir = CLUSTERS_BASE_DIR / cluster_name / 'activity.log'
    log_file = cluster_dir / "activity.log"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {message}\n"

    # Create the file if it does not exist
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line)


def check_files_ready(directory: Path, file_extension: str, timeout: int, interval: int):
    """
    Waits for the presence of files with the given extension in the specified directory.
    
    Args:
        directory (Path): The directory to check for files.
        file_extension (str): The file extension to look for.
        timeout (int): Maximum time to wait in seconds.
        interval (int): Time to wait between each check in seconds.

    Returns:
        bool: True if files are found, False if timeout is reached.
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        if any(f.suffix == file_extension for f in directory.glob("*")):
            return True
        time.sleep(interval)
    
    return False
