from app.infrastructure.cost_manager import get_usage_context, reset_usage_context, set_usage_context
from app.infrastructure.thread_pool import submit_background


def test_submit_background_propagates_usage_context():
    tokens = set_usage_context(account_id=42, user_id=7, feature="drafting")
    try:
        future = submit_background(get_usage_context)
        assert future.result(timeout=5) == (42, 7, "drafting")
    finally:
        reset_usage_context(tokens)


def test_submit_background_propagates_llm_account_context_to_nested_agents():
    from app.infrastructure.llm_attribution import current_account_id, llm_attribution

    def task():
        with llm_attribution("critic"):
            return current_account_id()

    tokens = set_usage_context(account_id=42, user_id=7, feature="drafting")
    try:
        future = submit_background(task)
        assert future.result(timeout=5) == 42
    finally:
        reset_usage_context(tokens)
