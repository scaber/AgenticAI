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

    # Test Agent output
    test_result: str
    test_passed: bool

    # Review Agent output
    review_result: dict
    review_approved: bool
    retry_count: int

    # Git Agent output
    branch_name: str
    pr_id: int
    modified_files: list[str]

    # Status & Error Handling
    status: str
    error: str
    failed_node: str
    node_retry_count: int
