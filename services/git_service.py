import os
import structlog
from git import Repo

from config import get_settings

logger = structlog.get_logger()


class GitService:
    def __init__(self):
        settings = get_settings()
        self._repo_path = settings.git_repo_path
        self._remote_url = settings.git_remote_url
        self._repo: Repo | None = None

    def _get_repo(self) -> Repo:
        if self._repo is None:
            self._repo = Repo(self._repo_path)
        return self._repo

    def create_branch(self, branch_name: str, base_branch: str = "dev") -> None:
        repo = self._get_repo()
        repo.remotes.origin.fetch()

        # Önceki denemeden kalmış yerel branch varsa sil
        if branch_name in repo.heads:
            repo.heads[base_branch if base_branch in repo.heads else "main"].checkout()
            repo.delete_head(branch_name, force=True)

        if base_branch in repo.heads:
            base = repo.heads[base_branch]
        else:
            base = repo.remotes.origin.refs[base_branch]

        new_branch = repo.create_head(branch_name, base)
        new_branch.checkout()
        logger.info("branch_created", branch=branch_name, base=base_branch)

    def apply_changes(self, changes: list[dict]) -> list[str]:
        repo = self._get_repo()
        modified_files = []

        for change in changes:
            file_path = os.path.join(self._repo_path, change["file_path"])
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(change["new_content"])

            modified_files.append(change["file_path"])
            logger.info("file_modified", path=change["file_path"])

        return modified_files

    def commit_and_push(self, branch_name: str, message: str, files: list[str]) -> str:
        repo = self._get_repo()

        for f in files:
            repo.index.add([f])

        commit = repo.index.commit(message)
        refspec = f"refs/heads/{branch_name}:refs/heads/{branch_name}"
        repo.remotes.origin.push(refspec, force=True)

        logger.info("changes_pushed", branch=branch_name, commit=str(commit))
        return str(commit)

    def get_file_content(self, file_path: str) -> str | None:
        full_path = os.path.join(self._repo_path, file_path)
        if not os.path.isfile(full_path):
            return None
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()

    def list_files(self, extensions: list[str] | None = None) -> list[str]:
        repo = self._get_repo()
        all_files = []

        for item in repo.tree().traverse():
            if item.type == "blob":
                if extensions is None or any(item.path.endswith(ext) for ext in extensions):
                    all_files.append(item.path)

        return all_files

    def cleanup_branch(self, branch_name: str) -> None:
        repo = self._get_repo()
        repo.heads.dev.checkout()
        repo.delete_head(branch_name, force=True)
        logger.info("branch_cleaned_up", branch=branch_name)
