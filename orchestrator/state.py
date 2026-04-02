from typing import TypedDict, Annotated
from models import ReviewResult


class AgentState(TypedDict):
    # Input
    work_item_id: int

    # Requirements Agent output
    work_item: dict
    analysis: str

    # Search Agent output
    search_results: list[dict]
    search_analysis: str

    # Coding Agent output
    changes: list[dict]
    commit_message: str

    # Review Agent output
    review_result: dict
    review_approved: bool
    retry_count: int

    # Git Agent output
    branch_name: str
    pr_id: int
    modified_files: list[str]

    # Status
    status: str
    error: str
