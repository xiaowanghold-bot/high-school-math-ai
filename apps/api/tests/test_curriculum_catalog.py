from app.modules.curriculum import CsvCurriculumCatalog
from app.core.config import get_settings


def test_curriculum_csv_builds_one_complete_tree() -> None:
    catalog = CsvCurriculumCatalog(get_settings().curriculum_csv)

    tree = catalog.get_tree()

    assert tree.node_id == "pep_a"
    assert [item.name for item in tree.children] == [
        "必修第一册",
        "必修第二册",
        "选择性必修第一册",
        "选择性必修第二册",
        "选择性必修第三册",
    ]
    assert sum(1 for item in _walk(tree) if item.node_type == "chapter") == 18
    assert sum(1 for item in _walk(tree) if item.node_type == "section") == 71
    assert sum(1 for item in _walk(tree) if item.node_type == "knowledge_point") == 302


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def test_known_node_can_be_retrieved() -> None:
    catalog = CsvCurriculumCatalog(get_settings().curriculum_csv)

    node = catalog.get_node("kp_r1_3_2_01")

    assert node.name == "函数单调性"
    assert node.gaokao_priority == "high"


def test_curriculum_search_returns_selectable_node_with_path() -> None:
    catalog = CsvCurriculumCatalog(get_settings().curriculum_csv)

    results = catalog.search("单调性", limit=5)

    assert results
    assert results[0].node_id == "kp_r1_3_2_01"
    assert results[0].chapter == "函数的概念与性质"
    assert results[0].section == "函数的基本性质"
    assert results[0].match_score >= 0.9


def test_curriculum_search_can_filter_volume_and_return_browse_results() -> None:
    catalog = CsvCurriculumCatalog(get_settings().curriculum_csv)

    results = catalog.search("", volume="必修第一册", limit=12)

    assert len(results) == 12
    assert all(item.node_type == "knowledge_point" for item in results)
    assert all(item.volume == "必修第一册" for item in results)


def test_new_volume_nodes_are_drafts_pending_teacher_review() -> None:
    catalog = CsvCurriculumCatalog(get_settings().curriculum_csv)

    node = catalog.get_node("kp_s2_5_3_05")

    assert node.name == "导数与不等式"
    assert node.volume == "选择性必修第二册"
    assert node.status == "draft_for_teacher_review"
    assert node.reviewed_by == "pending_owner_teacher"
