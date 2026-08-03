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
