from app.modules.curriculum import CsvCurriculumCatalog
from app.core.config import get_settings


def test_curriculum_csv_builds_one_complete_tree() -> None:
    catalog = CsvCurriculumCatalog(get_settings().curriculum_csv)

    tree = catalog.get_tree()

    assert tree.node_id == "pep_a_r1"
    assert len(tree.children) == 5
    assert sum(len(chapter.children) for chapter in tree.children) == 24
    knowledge_point_count = sum(
        len(section.children) for chapter in tree.children for section in chapter.children
    )
    assert knowledge_point_count == 90


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
