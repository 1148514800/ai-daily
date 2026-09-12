"""False-positive focused tests for the deterministic GitHub AI filter.

These cases guard the Phase 6.1 goal: ordinary software must not be classified
as an AI project just because its marketing copy says "AI", "agent" or "model".
"""

from app.collectors.raw import RawTrendingRepo
from app.pipelines.github_filter import evaluate_ai_relevance, is_ai_repo
from app.services.github_client import RepoMetadata


def make_repo(repo: str, description: str = "", *, rank: int = 1) -> RawTrendingRepo:
    return RawTrendingRepo(
        rank=rank,
        repo=repo,
        name=repo.partition("/")[2],
        description=description,
        language="",
        url=f"https://github.com/{repo}",
        stars=0,
        stars_today=None,
    )


def meta(description: str = "", topics: tuple[str, ...] = ()) -> RepoMetadata:
    return RepoMetadata(description=description, topics=topics)


# --- should be accepted ---


def test_llm_framework_accepted() -> None:
    repo = make_repo("acme/llm-forge", "An LLM framework for fine-tuning.")
    assert is_ai_repo(repo, meta(topics=("llm", "fine-tuning")))


def test_rag_project_accepted() -> None:
    repo = make_repo("acme/rag-engine", "Retrieval augmented generation over your docs.")
    assert is_ai_repo(repo, meta(topics=("rag",)))


def test_diffusion_model_accepted() -> None:
    repo = make_repo("acme/diffusion-lab", "Diffusion model training toolkit.")
    result = evaluate_ai_relevance(repo, meta(topics=("diffusion", "machine-learning")))
    assert result.accepted
    assert "diffusion" in result.strong_keywords


def test_ai_agent_framework_accepted_with_llm() -> None:
    repo = make_repo("acme/agent-forge", "An agent framework built on an LLM.")
    result = evaluate_ai_relevance(repo, meta())
    assert result.accepted
    assert "llm" in result.strong_keywords


def test_computer_vision_model_accepted() -> None:
    repo = make_repo("acme/cv-kit", "Computer vision pipeline for detection.")
    assert is_ai_repo(repo, meta(topics=("computer-vision",)))


def test_mcp_ai_tool_accepted_with_metadata() -> None:
    repo = make_repo(
        "acme/mcp-server",
        "Model context protocol server for LLM tooling.",
        rank=3,
    )
    assert is_ai_repo(repo, meta(topics=("mcp", "llm")))


def test_llm_plus_agent_still_accepted() -> None:
    repo = make_repo("acme/llm-agent", "LLM driven agent orchestration.")
    result = evaluate_ai_relevance(repo, meta(topics=("llm", "agent")))
    assert result.accepted
    assert "llm" in result.strong_keywords


def test_machine_learning_description_accepted() -> None:
    repo = make_repo("acme/trainer", "Machine learning training loop.")
    assert is_ai_repo(repo, meta(topics=("machine-learning",)))


# --- should be rejected ---


def test_crm_rejected_even_with_ai_marketing() -> None:
    repo = make_repo(
        "melgarafael/DeskcommCRM",
        "Open-source AI sales OS - self-hosted CRM with native AI agents, MCP-ready.",
    )
    result = evaluate_ai_relevance(repo, meta(description="AI sales CRM", topics=("rag", "mcp", "ai")))
    assert not result.accepted
    assert "crm" in result.negative_keywords


def test_todo_app_rejected() -> None:
    repo = make_repo("acme/todo-app", "A simple todo app with a chat UI.")
    assert not is_ai_repo(repo, meta())


def test_desktop_utility_rejected() -> None:
    repo = make_repo("vastsa/PI-Desktop", "Local-first AI coding agent desktop utility.")
    assert not is_ai_repo(repo, meta(topics=("mcp",)))


def test_adhd_tracker_rejected() -> None:
    repo = make_repo("ayghri/i-have-adhd", "A skill to stop your coding agent from burying the answer.")
    result = evaluate_ai_relevance(repo, meta())
    assert not result.accepted
    assert "adhd" in result.negative_keywords


def test_game_rejected() -> None:
    repo = make_repo("acme/model-game", "A puzzle game about model trains.")
    assert not is_ai_repo(repo, meta())


def test_plain_chat_app_rejected_without_ai_evidence() -> None:
    repo = make_repo("acme/chat-client", "A chat client and assistant UI for teams.")
    assert not is_ai_repo(repo, meta())


# --- weak keyword isolation (the original bug) ---


def test_description_model_only_rejected() -> None:
    repo = make_repo("acme/cad", "A model viewer for CAD files.")
    result = evaluate_ai_relevance(repo, meta())
    assert not result.accepted
    assert result.strong_keywords == []


def test_description_agent_only_rejected() -> None:
    repo = make_repo("jordan-gibbs/hyperresearch", "Agent-driven research knowledge base.")
    result = evaluate_ai_relevance(repo, meta())
    assert not result.accepted
    assert result.weak_keywords == ["agent"]


def test_description_vision_only_rejected() -> None:
    repo = make_repo("acme/eyes", "Vision tools for image inspection.")
    assert not is_ai_repo(repo, meta())


def test_two_weak_keywords_in_one_description_rejected() -> None:
    repo = make_repo("acme/platform", "An agent and model platform for teams.")
    assert not is_ai_repo(repo, meta())


def test_repo_name_ai_alone_is_not_enough() -> None:
    repo = make_repo("acme/ai-notes", "A note taking app.")
    assert not is_ai_repo(repo, meta())


def test_explicit_llm_name_is_enough() -> None:
    repo = make_repo("nashsu/llm_wiki", "Cross-platform desktop app for your documents.")
    result = evaluate_ai_relevance(repo, meta())
    assert result.accepted
    assert "llm" in result.strong_keywords


def test_topics_alone_are_not_enough() -> None:
    repo = make_repo("acme/marketing", "Marketing website for a shoe store.")
    assert not is_ai_repo(repo, meta(topics=("llm", "rag", "machine-learning")))


# --- strict fallback ---


def test_strict_fallback_rejects_tooling_only() -> None:
    repo = make_repo("acme/mcp-server", "MCP tools for your editor.")
    assert not is_ai_repo(repo, None)


def test_strict_fallback_rejects_weak_only() -> None:
    repo = make_repo("acme/agents", "Agents and models for workflow automation.")
    assert not is_ai_repo(repo, None)


def test_strict_fallback_keeps_core_evidence() -> None:
    repo = make_repo("ggml-org/llama.cpp", "LLM inference in C/C++")
    assert is_ai_repo(repo, None)


def test_strict_fallback_accepts_explicit_rag_name() -> None:
    repo = make_repo("acme/rag-pipeline", "Pipeline for document search.")
    assert is_ai_repo(repo, None)


def test_missing_metadata_switches_to_strict_mode() -> None:
    repo = make_repo("acme/ai-tools", "AI powered tools for developers.")
    assert evaluate_ai_relevance(repo, None).mode == "strict"
    assert not is_ai_repo(repo, None)


# --- evidence reporting ---


def test_debug_fields_capture_evidence() -> None:
    repo = make_repo("acme/rag-app", "A RAG app.")
    result = evaluate_ai_relevance(repo, meta(topics=("rag", "llm")))
    assert result.accepted
    assert result.mode == "normal"
    assert "rag" in result.strong_keywords
    assert "llm" in result.strong_keywords
    assert "topics" in result.matched_fields
    assert result.score > 0
    assert result.reason


def test_rejection_reason_is_populated() -> None:
    repo = make_repo("acme/notes", "A note taking app.")
    result = evaluate_ai_relevance(repo, meta())
    assert not result.accepted
    assert result.reason
    assert result.route == "none"


def test_mcp_tooling_alone_rejected() -> None:
    """An editor that merely ships MCP tools is not an AI project."""
    repo = make_repo(
        "pascalorg/editor",
        "Open-source 3D architectural editor with a local CLI, MCP tools, and practical workflows.",
    )
    result = evaluate_ai_relevance(repo, meta(topics=("mcp",)))
    assert not result.accepted
    assert result.strong_keywords == ["mcp"]


def test_vertex_cad_tool_rejected() -> None:
    repo = make_repo("acme/vertex-modeler", "Vertex modeler for CAD workflows.")
    assert not is_ai_repo(repo, meta(topics=("ai",)))




# --- real Trending false positives captured during Phase 6.1 ---
# These encode the exact repositories that the old rule accepted, with the
# metadata shape observed from the live GitHub REST API.


def test_real_pi_desktop_rejected_with_metadata() -> None:
    repo = make_repo(
        "vastsa/PI-Desktop",
        "Local-first AI coding agent desktop: Electron + Rust host core + pi Agent Harness",
    )
    result = evaluate_ai_relevance(repo, meta(topics=("mcp", "ai-agent")))
    assert not result.accepted
    assert result.strong_keywords == ["mcp"]


def test_real_pascalorg_editor_rejected_with_metadata() -> None:
    repo = make_repo(
        "pascalorg/editor",
        "Open-source 3D architectural editor with a local CLI, MCP tools, and practical workflows for humans and AI agents.",
    )
    result = evaluate_ai_relevance(repo, meta(topics=("mcp", "ai", "editor")))
    assert not result.accepted


def test_real_cloddsbot_rejected_with_metadata() -> None:
    repo = make_repo(
        "alsk1992/CloddsBot",
        "Open Source AI trading agent that operates autonomously across 1000+ markets. Built on Claude.",
    )
    result = evaluate_ai_relevance(repo, meta(topics=("ai", "agent", "trading")))
    assert not result.accepted
    assert result.strong_keywords == []


def test_real_deskcomm_crm_rejected_with_metadata() -> None:
    repo = make_repo(
        "melgarafael/DeskcommCRM",
        "Open-source AI sales OS - self-hosted CRM with native AI agents + WhatsApp. MCP-ready, multi-tenant.",
    )
    result = evaluate_ai_relevance(
        repo,
        meta(
            description="Open-source AI sales CRM",
            topics=("rag", "mcp", "ai", "crm"),
        ),
    )
    assert not result.accepted
    assert "crm" in result.negative_keywords


def test_real_llm_wiki_accepted_with_metadata() -> None:
    repo = make_repo(
        "nashsu/llm_wiki",
        "LLM Wiki is a cross-platform desktop application that turns your documents into an organized knowledge base. Instead of traditional RAG, the LLM incrementally builds a wiki.",
    )
    result = evaluate_ai_relevance(repo, meta(topics=("llm", "rag", "knowledge-base")))
    assert result.accepted
    assert "llm" in result.strong_keywords


def test_real_gods_eye_view_rejected_with_metadata() -> None:
    repo = make_repo(
        "bilawalsidhu/gods-eye-view",
        "A spy satellite simulator in your browser. Live open source spatial intelligence on a photorealistic 3D globe.",
    )
    result = evaluate_ai_relevance(repo, meta(topics=("satellite", "gis", "3d")))
    assert not result.accepted
    assert result.strong_keywords == []
