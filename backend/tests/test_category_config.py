from pathlib import Path

import pytest
from pytest import CaptureFixture

from repovil.category_config import CategoryConfigError, load_category_config, main

EXPECTED_CATEGORIES = (
    (
        "AI Agents",
        "ai-agents",
        True,
        1,
        ("ai-agent", "ai-agents", "agentic-ai", "ai-agent-framework"),
    ),
    (
        "Skills",
        "skills",
        True,
        2,
        ("agent-skills", "ai-agent-skills", "claude-code-skills", "codex-skills"),
    ),
    ("MCP Servers", "mcp-servers", True, 3, ("mcp-server", "mcp-servers")),
    (
        "Dev Tools",
        "dev-tools",
        True,
        4,
        ("ai-coding", "ai-coding-assistant", "ai-developer-tools", "coding-agents"),
    ),
    ("RAG", "rag", True, 5, ("rag", "retrieval-augmented-generation", "vector-database")),
    (
        "Observability&Eval",
        "observability-eval",
        True,
        6,
        ("llm-observability", "agent-observability", "llm-evaluation", "agent-evaluation"),
    ),
)


def test_default_configuration_matches_prd() -> None:
    configuration = load_category_config()

    actual = tuple(
        (
            category.name,
            category.slug,
            category.active,
            category.display_order,
            category.topics,
        )
        for category in configuration.categories
    )

    assert actual == EXPECTED_CATEGORIES
    assert all(category.name.casefold() != "all" for category in configuration.categories)
    assert all(category.slug != "all" for category in configuration.categories)
    assert all(
        topic.casefold() != "all"
        for category in configuration.categories
        for topic in category.topics
    )


def test_loading_same_configuration_is_idempotent() -> None:
    first = load_category_config()
    second = load_category_config()

    assert second == first


@pytest.mark.parametrize(
    ("second_name", "second_slug", "second_order", "second_topic", "error_match"),
    [
        ("First", "second", 2, "other-topic", "duplicate category name"),
        ("Second", "first", 2, "other-topic", "duplicate category slug"),
        ("Second", "second", 1, "other-topic", "duplicate category display_order"),
        ("Second", "second", 2, "shared-topic", "duplicate topic"),
    ],
)
def test_duplicate_values_are_rejected(
    tmp_path: Path,
    second_name: str,
    second_slug: str,
    second_order: int,
    second_topic: str,
    error_match: str,
) -> None:
    path = _write_config(
        tmp_path,
        f"""categories:
  - name: First
    slug: first
    active: true
    display_order: 1
    topics: [shared-topic]
  - name: {second_name}
    slug: {second_slug}
    active: true
    display_order: {second_order}
    topics: [{second_topic}]
""",
    )

    with pytest.raises(CategoryConfigError, match=error_match):
        load_category_config(path)


@pytest.mark.parametrize(
    ("yaml_text", "error_match"),
    [
        ("categories: []\n", "too_short"),
        (
            """categories:
  - name: Empty Topics
    slug: empty-topics
    active: true
    display_order: 1
    topics: []
""",
            "too_short",
        ),
        (
            """categories:
  - name: Bad Slug
    slug: Bad_Slug
    active: true
    display_order: 1
    topics: [valid-topic]
""",
            "string_pattern_mismatch",
        ),
        (
            """categories:
  - name: All
    slug: all
    active: true
    display_order: 1
    topics: [valid-topic]
""",
            "cannot be a category",
        ),
        (
            """categories:
  - name: Reserved Topic
    slug: reserved-topic
    active: true
    display_order: 1
    topics: [All]
""",
            "cannot be a topic",
        ),
        (
            """categories:
  - name: Missing Active
    slug: missing-active
    display_order: 1
    topics: [valid-topic]
""",
            "active",
        ),
        (
            """categories:
  - name: Wrong Type
    slug: wrong-type
    active: "yes"
    display_order: 1
    topics: [valid-topic]
""",
            "bool_type",
        ),
        ("not_categories: []\n", "categories"),
        ("categories: [\n", "Could not read"),
    ],
)
def test_invalid_configuration_is_rejected(
    tmp_path: Path, yaml_text: str, error_match: str
) -> None:
    path = _write_config(tmp_path, yaml_text)

    with pytest.raises(CategoryConfigError, match=error_match):
        load_category_config(path)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CategoryConfigError, match="Could not read"):
        load_category_config(tmp_path / "missing.yaml")


def test_validation_command_reports_counts(capsys: CaptureFixture[str]) -> None:
    main()

    assert capsys.readouterr().out == (
        "Validated 6 categories and 21 topics from config/categories.yaml\n"
    )


def _write_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "categories.yaml"
    path.write_text(content, encoding="utf-8")
    return path
