import re
import structlog

from config import get_settings
from services import AzureDevOpsService, GitService
from models import PRDetails

logger = structlog.get_logger()


class GitAgent:
    def __init__(self):
        self._devops_service = AzureDevOpsService()
        self._git_service = GitService()

    def execute(
        self,
        work_item_id: int,
        work_item_title: str,
        changes: list[dict],
        commit_message: str,
        review_summary: str,
    ) -> dict:
        branch_name = self._generate_branch_name(work_item_id, work_item_title)
        logger.info("git_agent_starting", branch=branch_name, work_item_id=work_item_id)

        # 1. Branch oluştur
        self._git_service.create_branch(branch_name)

        # 2. Değişiklikleri uygula
        modified_files = self._git_service.apply_changes(changes)

        # 3. Commit ve push
        self._git_service.commit_and_push(branch_name, commit_message, modified_files)

        # 4. PR oluştur
        pr_details = PRDetails(
            title=f"[AI-Agent] {work_item_title}",
            description=self._build_pr_description(work_item_id, commit_message, review_summary, changes),
            source_branch=branch_name,
            target_branch="dev",
            work_item_id=work_item_id,
        )

        settings = get_settings()
        repo_name = settings.git_remote_url.rstrip("/").split("/")[-1]
        pr_id = self._devops_service.create_pull_request(repo_name, pr_details)

        logger.info("git_agent_complete", pr_id=pr_id, branch=branch_name)

        return {
            "branch_name": branch_name,
            "pr_id": pr_id,
            "modified_files": modified_files,
            "commit_message": commit_message,
        }

    def _generate_branch_name(self, work_item_id: int, title: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:40]
        return f"ai-agent/{work_item_id}-{slug}"

    def _build_pr_description(
        self,
        work_item_id: int,
        commit_message: str,
        review_summary: str,
        changes: list[dict],
    ) -> str:
        files_list = "\n".join(f"- `{c.get('file_path', '')}`" for c in changes)
        return f"""## 🤖 AI Agent tarafından otomatik oluşturulmuştur

### İlgili İş Maddesi
AB#{work_item_id}

### Yapılan Değişiklikler
{commit_message}

### Değiştirilen Dosyalar
{files_list}

### AI İnceleme Özeti
{review_summary}

---
> ⚠️ Bu PR otomatik olarak oluşturulmuştur. Lütfen merge etmeden önce dikkatli bir şekilde inceleyin.
"""
