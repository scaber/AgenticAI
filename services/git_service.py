import os
import structlog
from git import Repo

from config import get_settings

logger = structlog.get_logger()

# Yazma işlemlerinde izin verilen dizinler (repo kökünden göreceli)
ALLOWED_WRITE_DIRS = {"src", "tests", "test", "lib", "app", "Api", "Services", "Models", "Controllers", "Repositories"}

# Dokunulmaması gereken dosya/dizin desenleri
FORBIDDEN_PATTERNS = {".git", ".env", ".github", "node_modules", "bin", "obj", ".vscode", ".vs"}


class PathSecurityError(Exception):
    """Güvenlik kontrolünden geçemeyen dosya yolu hatası."""
    pass


class GitService:
    def __init__(self):
        settings = get_settings()
        self._repo_path = os.path.realpath(settings.git_repo_path)
        self._remote_url = settings.git_remote_url
        self._repo: Repo | None = None

    def _get_repo(self) -> Repo:
        if self._repo is None:
            self._repo = Repo(self._repo_path)
        return self._repo

    def _validate_path(self, file_path: str, *, write: bool = False) -> str:
        """Dosya yolunun güvenli olduğunu doğrular.

        - Repo dizini dışına çıkmayı engeller (path traversal koruması).
        - write=True ise yasak dosya/dizin desenlerini kontrol eder.
        - Mutlak (resolved) yolu döndürür.
        """
        # Normalize ve resolve
        joined = os.path.join(self._repo_path, file_path)
        resolved = os.path.realpath(joined)

        # Path traversal kontrolü
        if not resolved.startswith(self._repo_path + os.sep) and resolved != self._repo_path:
            raise PathSecurityError(
                f"Güvenlik ihlali: '{file_path}' repo dizini dışına çıkıyor. "
                f"Resolved: {resolved}, Repo: {self._repo_path}"
            )

        # Yazma işlemi için ek güvenlik kontrolleri
        if write:
            rel = os.path.relpath(resolved, self._repo_path)
            parts = rel.replace("\\", "/").split("/")

            # Yasak dizin/dosya kontrolü
            for part in parts:
                if part in FORBIDDEN_PATTERNS:
                    raise PathSecurityError(
                        f"Güvenlik ihlali: '{file_path}' yasak bir dizin/dosya içeriyor: '{part}'"
                    )

        return resolved

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
            file_path = change["file_path"]

            # Güvenlik doğrulaması
            resolved = self._validate_path(file_path, write=True)

            os.makedirs(os.path.dirname(resolved), exist_ok=True)

            with open(resolved, "w", encoding="utf-8") as f:
                f.write(change["new_content"])

            modified_files.append(file_path)
            logger.info("file_modified", path=file_path)

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
        try:
            full_path = self._validate_path(file_path, write=False)
        except PathSecurityError:
            logger.warning("path_security_blocked_read", file=file_path)
            return None

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
