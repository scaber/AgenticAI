import traceback
import structlog
from langgraph.graph import StateGraph, END

from orchestrator.state import AgentState
from agents import RequirementsAgent, SearchAgent, CodingAgent, ReviewAgent, GitAgent, TestAgent

logger = structlog.get_logger()

MAX_REVIEW_RETRIES = 2
MAX_NODE_RETRIES = 2


# --- Safe Node Wrapper ---

def _safe_node(func):
    """Her node fonksiyonunu try-except ile sarar; hata durumunda state'e error yazar."""
    def wrapper(state: AgentState) -> dict:
        node_name = func.__name__
        try:
            return func(state)
        except Exception as e:
            logger.error("node_failed", node=node_name, error=str(e), traceback=traceback.format_exc())
            node_retries = state.get("node_retry_count", 0) + 1
            return {
                "error": f"[{node_name}] {type(e).__name__}: {e}",
                "failed_node": node_name,
                "node_retry_count": node_retries,
                "status": f"{node_name}_failed",
            }
    wrapper.__name__ = func.__name__
    return wrapper


# --- Node Functions ---

@_safe_node
def analyze_requirements(state: AgentState) -> dict:
    logger.info("node_analyze_requirements", work_item_id=state["work_item_id"])
    agent = RequirementsAgent()
    result = agent.analyze(state["work_item_id"])
    return {
        "work_item": result["work_item"],
        "analysis": result["analysis"],
        "status": "requirements_analyzed",
        "error": "",
        "failed_node": "",
        "node_retry_count": 0,
    }


@_safe_node
def search_codebase(state: AgentState) -> dict:
    logger.info("node_search_codebase")
    agent = SearchAgent()
    result = agent.search(state["analysis"])
    return {
        "search_results": result["search_results"],
        "search_analysis": result["search_analysis"],
        "status": "codebase_searched",
        "error": "",
        "failed_node": "",
        "node_retry_count": 0,
    }


@_safe_node
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
        "error": "",
        "failed_node": "",
        "node_retry_count": 0,
    }


@_safe_node
def test_code(state: AgentState) -> dict:
    logger.info("node_test_code")
    agent = TestAgent()
    result = agent.validate_changes(state["changes"])
    return {
        "test_result": result.summary,
        "test_passed": result.all_passed,
        "status": "code_tested",
        "error": "",
        "failed_node": "",
        "node_retry_count": 0,
    }


@_safe_node
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
        "error": "",
        "failed_node": "",
        "node_retry_count": 0,
    }


@_safe_node
def create_pr(state: AgentState) -> dict:
    logger.info("node_create_pr")
    review_approved = state.get("review_approved", False)
    agent = GitAgent()
    result = agent.execute(
        work_item_id=state["work_item_id"],
        work_item_title=state["work_item"].get("title", ""),
        changes=state["changes"],
        commit_message=state["commit_message"],
        review_summary=state["review_result"].get("summary", ""),
        labels=[] if review_approved else ["AI-Review-Failed", "Needs-Human-Review"],
    )
    return {
        "branch_name": result["branch_name"],
        "pr_id": result["pr_id"],
        "modified_files": result["modified_files"],
        "status": "pr_created",
        "error": "",
        "failed_node": "",
        "node_retry_count": 0,
    }


def handle_error(state: AgentState) -> dict:
    logger.error(
        "node_handle_error",
        error=state.get("error", "unknown"),
        failed_node=state.get("failed_node", "unknown"),
    )
    return {"status": "failed"}


# --- Conditional Edges ---

def _check_error_or_next(next_node: str):
    """Bir sonraki node'a geçmeden önce hata kontrolü yapar."""
    def router(state: AgentState) -> str:
        if state.get("error"):
            if state.get("node_retry_count", 0) < MAX_NODE_RETRIES:
                failed = state.get("failed_node", "")
                logger.warning("retrying_node", node=failed, attempt=state.get("node_retry_count"))
                return failed  # aynı node'u tekrar dene
            return "handle_error"
        return next_node
    return router


def should_retry_or_proceed(state: AgentState) -> str:
    if state.get("error"):
        if state.get("node_retry_count", 0) < MAX_NODE_RETRIES:
            return state.get("failed_node", "review_code")
        return "handle_error"
    if state.get("review_approved", False):
        return "create_pr"
    if state.get("retry_count", 0) >= MAX_REVIEW_RETRIES:
        logger.warning("max_retries_reached", retry_count=state["retry_count"])
        return "create_pr"  # Yine de PR aç, etiketlerle insan inceleyecek
    return "generate_code"


def after_create_pr(state: AgentState) -> str:
    if state.get("error"):
        if state.get("node_retry_count", 0) < MAX_NODE_RETRIES:
            return "create_pr"
        return "handle_error"
    return END


# --- Graph Builder ---

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("analyze_requirements", analyze_requirements)
    graph.add_node("search_codebase", search_codebase)
    graph.add_node("generate_code", generate_code)
    graph.add_node("test_code", test_code)
    graph.add_node("review_code", review_code)
    graph.add_node("create_pr", create_pr)
    graph.add_node("handle_error", handle_error)

    # Set entry point
    graph.set_entry_point("analyze_requirements")

    # Edges with error checking
    graph.add_conditional_edges(
        "analyze_requirements",
        _check_error_or_next("search_codebase"),
        {
            "search_codebase": "search_codebase",
            "analyze_requirements": "analyze_requirements",
            "handle_error": "handle_error",
        },
    )

    graph.add_conditional_edges(
        "search_codebase",
        _check_error_or_next("generate_code"),
        {
            "generate_code": "generate_code",
            "search_codebase": "search_codebase",
            "handle_error": "handle_error",
        },
    )

    graph.add_conditional_edges(
        "generate_code",
        _check_error_or_next("test_code"),
        {
            "test_code": "test_code",
            "generate_code": "generate_code",
            "handle_error": "handle_error",
        },
    )

    graph.add_conditional_edges(
        "test_code",
        _check_error_or_next("review_code"),
        {
            "review_code": "review_code",
            "test_code": "test_code",
            "handle_error": "handle_error",
        },
    )

    # Conditional: review sonucuna göre
    graph.add_conditional_edges(
        "review_code",
        should_retry_or_proceed,
        {
            "create_pr": "create_pr",
            "generate_code": "generate_code",
            "review_code": "review_code",
            "handle_error": "handle_error",
        },
    )

    graph.add_conditional_edges(
        "create_pr",
        after_create_pr,
        {
            "create_pr": "create_pr",
            "handle_error": "handle_error",
            END: END,
        },
    )

    graph.add_edge("handle_error", END)

    return graph


def get_compiled_graph():
    graph = build_graph()
    return graph.compile()
