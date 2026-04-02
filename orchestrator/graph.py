import structlog
from langgraph.graph import StateGraph, END

from orchestrator.state import AgentState
from agents import RequirementsAgent, SearchAgent, CodingAgent, ReviewAgent, GitAgent

logger = structlog.get_logger()

MAX_REVIEW_RETRIES = 2


# --- Node Functions ---

def analyze_requirements(state: AgentState) -> dict:
    logger.info("node_analyze_requirements", work_item_id=state["work_item_id"])
    agent = RequirementsAgent()
    result = agent.analyze(state["work_item_id"])
    return {
        "work_item": result["work_item"],
        "analysis": result["analysis"],
        "status": "requirements_analyzed",
    }


def search_codebase(state: AgentState) -> dict:
    logger.info("node_search_codebase")
    agent = SearchAgent()
    result = agent.search(state["analysis"])
    return {
        "search_results": result["search_results"],
        "search_analysis": result["search_analysis"],
        "status": "codebase_searched",
    }


def generate_code(state: AgentState) -> dict:
    logger.info("node_generate_code")
    agent = CodingAgent()
    work_item_title = state["work_item"].get("title", "")
    result = agent.generate_changes(
        analysis=state["analysis"],
        search_results=state["search_analysis"],
        work_item_title=work_item_title,
    )
    return {
        "changes": result.get("changes", []),
        "commit_message": result.get("commit_message", "chore: automated changes"),
        "status": "code_generated",
    }


def review_code(state: AgentState) -> dict:
    logger.info("node_review_code", retry_count=state.get("retry_count", 0))
    agent = ReviewAgent()
    result = agent.review(
        analysis=state["analysis"],
        changes=state["changes"],
    )
    return {
        "review_result": result.model_dump(),
        "review_approved": result.approved,
        "retry_count": state.get("retry_count", 0) + 1,
        "status": "code_reviewed",
    }


def create_pr(state: AgentState) -> dict:
    logger.info("node_create_pr")
    agent = GitAgent()
    result = agent.execute(
        work_item_id=state["work_item_id"],
        work_item_title=state["work_item"].get("title", ""),
        changes=state["changes"],
        commit_message=state["commit_message"],
        review_summary=state["review_result"].get("summary", ""),
    )
    return {
        "branch_name": result["branch_name"],
        "pr_id": result["pr_id"],
        "modified_files": result["modified_files"],
        "status": "pr_created",
    }


def handle_error(state: AgentState) -> dict:
    logger.error("node_handle_error", error=state.get("error", "unknown"))
    return {"status": "failed"}


# --- Conditional Edges ---

def should_retry_or_proceed(state: AgentState) -> str:
    if state.get("review_approved", False):
        return "create_pr"
    if state.get("retry_count", 0) >= MAX_REVIEW_RETRIES:
        logger.warning("max_retries_reached", retry_count=state["retry_count"])
        return "create_pr"  # Yine de PR aç, insan inceleyecek
    return "generate_code"


# --- Graph Builder ---

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("analyze_requirements", analyze_requirements)
    graph.add_node("search_codebase", search_codebase)
    graph.add_node("generate_code", generate_code)
    graph.add_node("review_code", review_code)
    graph.add_node("create_pr", create_pr)

    # Set entry point
    graph.set_entry_point("analyze_requirements")

    # Add edges
    graph.add_edge("analyze_requirements", "search_codebase")
    graph.add_edge("search_codebase", "generate_code")
    graph.add_edge("generate_code", "review_code")

    # Conditional: review sonucuna göre
    graph.add_conditional_edges(
        "review_code",
        should_retry_or_proceed,
        {
            "create_pr": "create_pr",
            "generate_code": "generate_code",
        },
    )

    graph.add_edge("create_pr", END)

    return graph


def get_compiled_graph():
    graph = build_graph()
    return graph.compile()
