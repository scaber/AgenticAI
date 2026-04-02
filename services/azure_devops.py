import base64
import structlog
from azure.devops.connection import Connection
from azure.devops.v7_1.work_item_tracking import WorkItemTrackingClient
from azure.devops.v7_1.git import GitClient, GitPullRequest, GitRefUpdate
from msrest.authentication import BasicAuthentication

from config import get_settings
from models import WorkItem, WorkItemType, PRDetails

logger = structlog.get_logger()


class AzureDevOpsService:
    def __init__(self):
        settings = get_settings()
        credentials = BasicAuthentication("", settings.azure_devops_pat)
        self._connection = Connection(
            base_url=settings.azure_devops_org_url,
            creds=credentials,
        )
        self._project = settings.azure_devops_project
        self._wit_client: WorkItemTrackingClient = self._connection.clients.get_work_item_tracking_client()
        self._git_client: GitClient = self._connection.clients.get_git_client()

    def get_work_item(self, work_item_id: int) -> WorkItem:
        raw = self._wit_client.get_work_item(work_item_id, expand="All")
        fields = raw.fields

        wi_type_str = fields.get("System.WorkItemType", "User Story")
        try:
            wi_type = WorkItemType(wi_type_str)
        except ValueError:
            wi_type = WorkItemType.TASK  # Bilinmeyen tipler için fallback

        return WorkItem(
            id=raw.id,
            title=fields.get("System.Title", ""),
            description=fields.get("System.Description", ""),
            acceptance_criteria=fields.get("Microsoft.VSTS.Common.AcceptanceCriteria", ""),
            work_item_type=wi_type,
            state=fields.get("System.State", ""),
            assigned_to=fields.get("System.AssignedTo", {}).get("displayName", ""),
            area_path=fields.get("System.AreaPath", ""),
            iteration_path=fields.get("System.IterationPath", ""),
        )

    def update_work_item_state(self, work_item_id: int, state: str) -> None:
        from azure.devops.v7_1.work_item_tracking.models import JsonPatchOperation

        patch = [
            JsonPatchOperation(
                op="replace",
                path="/fields/System.State",
                value=state,
            )
        ]
        self._wit_client.update_work_item(patch, work_item_id, self._project)
        logger.info("work_item_state_updated", work_item_id=work_item_id, new_state=state)

    def create_pull_request(self, repo_name: str, pr_details: PRDetails) -> int:
        pr = GitPullRequest(
            title=pr_details.title,
            description=pr_details.description,
            source_ref_name=f"refs/heads/{pr_details.source_branch}",
            target_ref_name=f"refs/heads/{pr_details.target_branch}",
        )

        if pr_details.work_item_id:
            pr.work_item_refs = [{"id": str(pr_details.work_item_id)}]

        created_pr = self._git_client.create_pull_request(
            pr, repo_name, project=self._project
        )
        logger.info("pull_request_created", pr_id=created_pr.pull_request_id, title=pr_details.title)
        return created_pr.pull_request_id

    def get_repositories(self) -> list[dict]:
        repos = self._git_client.get_repositories(self._project)
        return [{"id": r.id, "name": r.name, "url": r.remote_url} for r in repos]
