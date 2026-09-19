import json
import subprocess
import sys
from pathlib import Path

from app.tasks.celery_app import celery_app

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_TASK_NAMES = {
    "ingestion.process_cv",
    "ingestion.trigger_indexing",
    "graph.index_candidat",
    "gdpr.nettoyer_entites_orphelines",
}


def test_celery_app_registers_all_expected_tasks_in_process():
    """Sanity check in the current (pytest) process. NOT sufficient on its own:
    conftest.py imports app.main, whose routers import some task modules
    directly (e.g. app.routers.ingestion imports process_cv_task) -- so a
    broken autodiscover can still "pass" here by transitive-import accident.
    test_celery_worker_registers_tasks_in_isolated_process below is the real guard."""
    registered = set(celery_app.tasks.keys())
    missing = EXPECTED_TASK_NAMES - registered
    assert not missing, f"Tâches Celery manquantes dans le registre : {sorted(missing)}"


def test_celery_worker_registers_tasks_in_isolated_process():
    """Spawns a fresh Python process that imports ONLY app.tasks.celery_app --
    exactly what `celery -A app.tasks.celery_app worker` does at boot, with no
    FastAPI app / routers ever loaded. This reproduces the real production
    topology (API and worker as separate processes) and is what would have
    caught the original bug: autodiscover_tasks(["app.tasks"]) looked for a
    non-existent "app.tasks.tasks" submodule and silently registered zero
    custom tasks."""
    script = (
        "import json\n"
        "from app.tasks.celery_app import celery_app\n"
        "names = [k for k in celery_app.tasks.keys() if not k.startswith('celery.')]\n"
        "print(json.dumps(names))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Le process worker isolé a échoué au démarrage :\n{result.stderr}"

    registered = set(json.loads(result.stdout))
    missing = EXPECTED_TASK_NAMES - registered
    assert not missing, (
        "Un vrai worker Celery isolé (celery -A app.tasks.celery_app worker) n'enregistre pas "
        f"les tâches suivantes -- elles lèveraient NotRegistered en production : {sorted(missing)}"
    )
