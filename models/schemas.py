from pydantic import BaseModel, Field
from enum import Enum


class WorkItemType(str, Enum):
    USER_STORY = "User Story"
    BUG = "Bug"
    TASK = "Task"
    FINDING = "Finding"
    FEATURE = "Feature"
    EPIC = "Epic"
    ISSUE = "Issue"


class WorkItem(BaseModel):
    id: int
    title: str
    description: str = ""
    acceptance_criteria: str = ""
    work_item_type: WorkItemType = WorkItemType.USER_STORY
    state: str = ""
    assigned_to: str = ""
    area_path: str = ""
    iteration_path: str = ""


class CodeChange(BaseModel):
    file_path: str
    original_content: str = ""
    new_content: str
    change_description: str


class ReviewResult(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    summary: str = ""


class PRDetails(BaseModel):
    title: str
    description: str
    source_branch: str
    target_branch: str = "dev"
    work_item_id: int | None = None


class WebhookPayload(BaseModel):
    subscription_id: str = ""
    event_type: str = ""
    resource: dict = Field(default_factory=dict)

    @property
    def work_item_id(self) -> int | None:
        return self.resource.get("id")

    @property
    def work_item_fields(self) -> dict:
        return self.resource.get("fields", {})
