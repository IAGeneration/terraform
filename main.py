import os
import shutil
import subprocess
import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException,APIRouter
from fastapi.openapi.utils import get_openapi

from fastapi.staticfiles import StaticFiles

from starlette.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Dict, Optional
from fastapi.openapi.docs import get_swagger_ui_html

app = FastAPI(
    title="Auto Deploy Terraform",
    version="1.0.0",
    docs_url=None,  # Désactiver la doc par défaut pour éviter les conflits
    redoc_url=None
)

general_router = APIRouter(tags=["🚀 PAAS API"])  

app.mount("/static", StaticFiles(directory="."), name="static")


# --------- Schémas de données ---------

class RepoConfig(BaseModel):
    service_name: str
    repo: str
    branch: str
    env: Optional[Dict[str, str]] = None

class CreateClusterRequest(BaseModel):
    name: str
    repositories: List[RepoConfig]

class UpdateSettingsRequest(BaseModel):
    """
    Exemple de schéma pour mettre à jour la configuration (params.json).
    Adaptez selon vos variables Terraform ou votre format.
    """
    # On peut imaginer d'autres champs : region, zone, etc.
    name: Optional[str] = None
    repositories: Optional[List[RepoConfig]] = None


# --------- Configuration globale ---------

BASE_DIR = Path(__file__).parent.resolve()
TEMPLATE_DIR = BASE_DIR / "template"
CLUSTERS_BASE_DIR = BASE_DIR / "clusters"


# --------- Endpoints ---------


# Fonction pour servir la documentation avec un style personnalisé


# --------- Personnalisation de Swagger UI ---------
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=app.title,
        swagger_favicon_url="https://fastapi.tiangolo.com/img/favicon.png",
        swagger_css_url="/static/style.css",
        swagger_ui_parameters={"defaultModelsExpandDepth": -1}
    )


# --------- Route OpenAPI ---------
@app.get("/openapi.json", include_in_schema=False)
async def get_open_api_endpoint():
    return get_openapi(
        title=app.title,
        version="1.0.0",
        description=app.description,
        routes=app.routes
    )

@general_router.post("/create")
def create_cluster(request: CreateClusterRequest):
    """
    Crée un nouveau cluster Terraform :
      1) Duplique le dossier template/ dans clusters/<name>/
      2) Remplace '##name##' dans le contenu des fichiers (e.g. terraform.tfvars)
      3) Génère un fichier params.json avec les infos reçues
      4) Crée pour chaque repo un fichier .env
      5) Exécute terraform init && terraform apply
      6) Log l'activité
    """
    name = request.name
    new_cluster_dir = CLUSTERS_BASE_DIR / name

    # Vérifier si le cluster existe déjà
    if new_cluster_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Le cluster '{name}' existe déjà."
        )

    # 1) Copier le template/ vers clusters/<name>/
    try:
        log_activity(name, "Création démarrée.")
        shutil.copytree(TEMPLATE_DIR, new_cluster_dir)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la copie du template: {str(e)}"
        )

    # 2) Remplacer ##name## dans les fichiers (dont terraform.tfvars)
    try:
        replace_placeholder_in_directory(new_cluster_dir, "##name##", name)
    except Exception as e:
        log_activity(name, f"Création échouée : erreur de remplacement. {str(e)}")
        shutil.rmtree(new_cluster_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors du remplacement du placeholder: {str(e)}"
        )

    # 3) Générer un fichier params.json
    try:
        params_file = new_cluster_dir / "params.json"
        with open(params_file, "w", encoding="utf-8") as f:
            json.dump(request.dict(), f, indent=4)
    except Exception as e:
        log_activity(name, f"Création échouée : erreur écriture params.json. {str(e)}")
        shutil.rmtree(new_cluster_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la création de params.json: {str(e)}"
        )

    # 4) Créer un fichier .env pour chaque repo
    try:
        for repo_info in request.repositories:
            env_file = new_cluster_dir / f"{repo_info.repo}.env"
            with open(env_file, "w", encoding="utf-8") as f:
                if repo_info.env:
                    for k, v in repo_info.env.items():
                        f.write(f"{k}={v}\n")
                else:
                    f.write("# Pas de variables d'environnement\n")
    except Exception as e:
        log_activity(name, f"Création échouée : erreur création .env. {str(e)}")
        shutil.rmtree(new_cluster_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la création des fichiers .env: {str(e)}"
        )

    # 5) Exécuter terraform init && terraform apply
    """
    try:
        run_terraform_init_and_apply(new_cluster_dir)
    except Exception as e:
        log_activity(name, f"Création échouée : terraform apply. {str(e)}")
        shutil.rmtree(new_cluster_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))
    """

    # Si tout s'est bien passé
    log_activity(name, "Cluster créé avec succès.")
    return {"message": f"Cluster '{name}' créé avec succès."}

@general_router.get("/list")
def list_clusters():
    """
    Retourne la liste des clusters présents dans le dossier `CLUSTERS_BASE_DIR`.
    Un cluster est identifié par un dossier.
    """
    if not CLUSTERS_BASE_DIR.exists():
        return {"clusters": []}

    # Récupérer les sous-dossiers (uniquement dossiers, pas fichiers)
    clusters = []
    for item in CLUSTERS_BASE_DIR.iterdir():
        if item.is_dir():
            clusters.append(item.name)

    return {"clusters": clusters}


@general_router.delete("/delete/{name}")
def delete_cluster_path(name: str):
    """
    Supprime un cluster Terraform en indiquant le nom dans l'URL (REST classique).
    Exemple: DELETE /delete/test
    """
    return perform_delete_cluster(name)


@general_router.get("/activity/{name}")
def get_activity(name: str):
    """
    Retourne le contenu du fichier activity.log pour le cluster <name>.
    Permet de suivre l'avancement du déploiement : en cours, créé, erreur, etc.
    """
    cluster_dir = CLUSTERS_BASE_DIR / name
    if not cluster_dir.exists():
        raise HTTPException(status_code=404, detail="Cluster inexistant.")

    log_file = cluster_dir / "activity.log"
    if not log_file.exists():
        # Pas de logs encore
        return {"activity": []}

    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # On retourne chaque ligne comme un événement distinct
    # ou on peut parser un format JSON si on veut plus de structure.
    return {"activity": [line.strip() for line in lines]}


@general_router.get("/settings/{name}")
def get_settings(name: str):
    """
    Récupère le contenu de params.json pour un cluster donné.
    Vous pouvez l'adapter pour lire terraform.tfvars si souhaité.
    """
    cluster_dir = CLUSTERS_BASE_DIR / name
    if not cluster_dir.exists():
        raise HTTPException(status_code=404, detail="Cluster inexistant.")

    params_file = cluster_dir / "params.json"
    if not params_file.exists():
        raise HTTPException(status_code=404, detail="Fichier params.json inexistant.")

    with open(params_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data


@general_router.put("/settings/{name}")
def update_settings(name: str, updated: UpdateSettingsRequest):
    """
    Met à jour partiellement la configuration (params.json) d'un cluster,
    puis relance (facultatif) un terraform apply si vous le souhaitez.
    """
    cluster_dir = CLUSTERS_BASE_DIR / name
    if not cluster_dir.exists():
        raise HTTPException(status_code=404, detail="Cluster inexistant.")

    params_file = cluster_dir / "params.json"
    if not params_file.exists():
        raise HTTPException(status_code=404, detail="Fichier params.json inexistant.")

    # Lire l'existant
    with open(params_file, "r", encoding="utf-8") as f:
        current_data = json.load(f)

    # Fusionner les champs
    # Par exemple, si updated.name est non-null, on l'écrase
    if updated.name is not None:
        current_data["name"] = updated.name
    if updated.repositories is not None:
        # On remplace complètement la liste des repos
        current_data["repositories"] = [r.dict() for r in updated.repositories]

    # Écrire la nouvelle config
    with open(params_file, "w", encoding="utf-8") as f:
        json.dump(current_data, f, indent=4)

    # Optionnel : on peut relancer un terraform apply pour prendre en compte
    # les nouvelles variables, si c'est pertinent
    try:
        log_activity(name, "Mise à jour des settings, relance Terraform.")
        run_terraform_init_and_apply(cluster_dir)
        log_activity(name, "Mise à jour terminée avec succès.")
    except Exception as e:
        log_activity(name, f"Erreur lors de la mise à jour des settings : {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": f"Settings du cluster '{name}' mis à jour."}


# --------- Fonctions utilitaires ---------

def perform_delete_cluster(name: str):
    """
    Logique commune pour supprimer un cluster :
     1) vérifier existence
     2) terraform destroy
     3) suppression du dossier
     4) log l'activité
    """
    cluster_dir = CLUSTERS_BASE_DIR / name
    if not cluster_dir.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Le cluster '{name}' n'existe pas."
        )

    log_activity(name, "Suppression du cluster démarrée.")

    # 1) Terraform destroy
    try:
        run_terraform_destroy(cluster_dir)
    except Exception as e:
        log_activity(name, f"Suppression échouée : terraform destroy. {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    # 2) Supprimer le dossier
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


def replace_placeholder_in_directory(directory: Path, placeholder: str, replacement: str):
    """
    Parcourt récursivement tous les fichiers du répertoire `directory`
    et remplace la chaîne `placeholder` par `replacement`.
    Ne touche pas aux noms des dossiers/fichiers (juste le contenu).
    """
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_path = Path(root) / file

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Fichier binaire ou encodage non-UTF8 => on ignore
                continue

            if placeholder in content:
                new_content = content.replace(placeholder, replacement)
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(new_content)


def run_terraform_init_and_apply(directory: Path):
    """
    Exécute `terraform init` puis `terraform apply -auto-approve`
    dans le répertoire spécifié.
    """
    init_cmd = ["terraform", "init"]
    apply_cmd = ["terraform", "apply", "-auto-approve"]

    # Terraform init
    process_init = subprocess.run(
        init_cmd, cwd=str(directory), capture_output=True, text=True
    )
    if process_init.returncode != 0:
        raise Exception(f"Erreur lors du terraform init:\n{process_init.stderr}")

    # Terraform apply
    process_apply = subprocess.run(
        apply_cmd, cwd=str(directory), capture_output=True, text=True
    )
    if process_apply.returncode != 0:
        raise Exception(f"Erreur lors du terraform apply:\n{process_apply.stderr}")


def run_terraform_destroy(directory: Path):
    """
    Exécute `terraform destroy -auto-approve` dans le répertoire spécifié.
    """
    destroy_cmd = ["terraform", "destroy", "-auto-approve"]
    process_destroy = subprocess.run(
        destroy_cmd, cwd=str(directory), capture_output=True, text=True
    )
    if process_destroy.returncode != 0:
        raise Exception(f"Erreur lors du terraform destroy:\n{process_destroy.stderr}")


def log_activity(cluster_name: str, message: str):
    """
    Ajoute un message de log (ex: "En cours de création", "Créé avec succès", "Erreur", etc.)
    dans le fichier activity.log du cluster concerné, avec un timestamp.
    """




app.include_router(general_router)
