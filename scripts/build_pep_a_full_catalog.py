from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/high-school-math-ai/curriculum/pep-a-required-1-knowledge-tree-v1.csv"
TARGET = ROOT / "docs/high-school-math-ai/curriculum/pep-a-full-knowledge-tree-v1.csv"

FIELDNAMES = [
    "node_id",
    "parent_id",
    "volume",
    "node_type",
    "code",
    "name",
    "description",
    "prerequisite_node_ids",
    "primary_competencies",
    "typical_question_types",
    "common_errors",
    "gaokao_priority",
    "status",
    "reviewed_by",
]

# These four volumes are a structured draft for the owner-teacher to review.
# Each tuple is: chapter number, chapter name, [(section code, section name, [knowledge points])].
VOLUMES = [
    (
        "r2",
        "必修第二册",
        [
            ("6", "平面向量及其应用", [
                ("6.1", "平面向量的概念", ["向量与数量", "零向量与单位向量", "相等向量与相反向量", "共线向量"]),
                ("6.2", "平面向量的运算", ["向量加法", "向量减法", "向量数乘", "向量线性运算", "向量数量积", "向量夹角与模"]),
                ("6.3", "平面向量基本定理及坐标表示", ["平面向量基本定理", "基底与向量分解", "平面向量坐标表示", "向量坐标运算", "向量共线的坐标表示", "数量积的坐标表示"]),
                ("6.4", "平面向量的应用", ["向量在几何中的应用", "向量在物理中的应用", "余弦定理", "正弦定理", "解三角形", "解三角形实际应用"]),
            ]),
            ("7", "复数", [
                ("7.1", "复数的概念", ["虚数单位", "复数的代数形式", "复数相等", "复平面与复数的几何意义", "共轭复数", "复数的模"]),
                ("7.2", "复数的四则运算", ["复数加减运算", "复数乘法", "复数除法", "复数运算的几何意义"]),
            ]),
            ("8", "立体几何初步", [
                ("8.1", "基本立体图形", ["棱柱棱锥棱台", "圆柱圆锥圆台", "球", "简单组合体", "斜二测画法"]),
                ("8.2", "立体图形的直观图", ["空间图形直观图", "斜二测画法应用"]),
                ("8.3", "简单几何体的表面积与体积", ["棱柱棱锥棱台表面积", "圆柱圆锥圆台表面积", "柱体锥体台体体积", "球的表面积与体积", "组合体表面积与体积"]),
                ("8.4", "空间点直线平面之间的位置关系", ["平面的基本事实", "空间点线面位置关系", "异面直线", "空间线面关系判定"]),
                ("8.5", "空间直线平面的平行", ["直线与直线平行", "直线与平面平行判定", "直线与平面平行性质", "平面与平面平行判定", "平面与平面平行性质"]),
                ("8.6", "空间直线平面的垂直", ["直线与直线垂直", "直线与平面垂直判定", "直线与平面垂直性质", "平面与平面垂直判定", "平面与平面垂直性质"]),
            ]),
            ("9", "统计", [
                ("9.1", "随机抽样", ["总体样本与样本量", "简单随机抽样", "分层随机抽样", "抽样方法选择"]),
                ("9.2", "用样本估计总体", ["频率分布表", "频率分布直方图", "百分位数", "众数中位数平均数", "方差与标准差", "样本数字特征应用"]),
                ("9.3", "统计案例", ["统计调查方案", "样本代表性分析", "统计结论解释"]),
            ]),
            ("10", "概率", [
                ("10.1", "随机事件与概率", ["随机试验与样本空间", "随机事件关系与运算", "古典概型", "概率基本性质", "互斥事件与对立事件"]),
                ("10.2", "事件的相互独立性", ["相互独立事件", "独立事件概率乘法", "独立重复试验初步"]),
                ("10.3", "频率与概率", ["频率的稳定性", "频率估计概率", "随机模拟"]),
            ]),
        ],
    ),
    (
        "s1",
        "选择性必修第一册",
        [
            ("1", "空间向量与立体几何", [
                ("1.1", "空间向量及其运算", ["空间向量的概念", "空间向量线性运算", "空间向量数量积", "空间向量夹角与模"]),
                ("1.2", "空间向量基本定理", ["共面向量定理", "空间向量基本定理", "空间向量基底"]),
                ("1.3", "空间向量及其运算的坐标表示", ["空间直角坐标系", "空间向量坐标表示", "空间向量坐标运算", "空间两点距离"]),
                ("1.4", "空间向量的应用", ["直线方向向量", "平面法向量", "线线角", "线面角", "二面角", "点到平面距离", "空间平行垂直的向量证明"]),
            ]),
            ("2", "直线和圆的方程", [
                ("2.1", "直线的倾斜角与斜率", ["直线倾斜角", "直线斜率", "两直线平行与垂直的斜率关系"]),
                ("2.2", "直线的方程", ["直线点斜式", "直线斜截式", "直线两点式", "直线截距式", "直线一般式"]),
                ("2.3", "直线的交点坐标与距离公式", ["两直线交点", "两点间距离", "点到直线距离", "两平行线间距离"]),
                ("2.4", "圆的方程", ["圆的标准方程", "圆的一般方程", "点与圆的位置关系", "直线与圆的位置关系", "圆与圆的位置关系", "圆的切线与弦"]),
            ]),
            ("3", "圆锥曲线的方程", [
                ("3.1", "椭圆", ["椭圆的定义", "椭圆的标准方程", "椭圆的几何性质", "直线与椭圆", "椭圆综合应用"]),
                ("3.2", "双曲线", ["双曲线的定义", "双曲线的标准方程", "双曲线的几何性质", "双曲线渐近线", "直线与双曲线"]),
                ("3.3", "抛物线", ["抛物线的定义", "抛物线的标准方程", "抛物线的几何性质", "直线与抛物线", "圆锥曲线综合"]),
            ]),
        ],
    ),
    (
        "s2",
        "选择性必修第二册",
        [
            ("4", "数列", [
                ("4.1", "数列的概念", ["数列与数列通项", "数列递推关系", "数列单调性与最值", "数列求通项"]),
                ("4.2", "等差数列", ["等差数列定义", "等差数列通项公式", "等差中项", "等差数列前n项和", "等差数列性质"]),
                ("4.3", "等比数列", ["等比数列定义", "等比数列通项公式", "等比中项", "等比数列前n项和", "等比数列性质"]),
                ("4.4", "数学归纳法", ["数学归纳法原理", "数学归纳法证明等式", "数学归纳法证明不等式", "数列综合与放缩"]),
            ]),
            ("5", "一元函数的导数及其应用", [
                ("5.1", "导数的概念及其意义", ["平均变化率", "瞬时变化率", "导数定义", "导数的几何意义", "导数的物理意义"]),
                ("5.2", "导数的运算", ["基本初等函数导数", "导数四则运算", "复合函数求导", "切线方程"]),
                ("5.3", "导数在研究函数中的应用", ["利用导数判断单调性", "函数极值", "函数最大值与最小值", "导数与函数零点", "导数与不等式", "导数与参数", "导数实际应用"]),
            ]),
        ],
    ),
    (
        "s3",
        "选择性必修第三册",
        [
            ("6", "计数原理", [
                ("6.1", "分类加法计数原理与分步乘法计数原理", ["分类加法计数原理", "分步乘法计数原理", "两个计数原理综合"]),
                ("6.2", "排列与组合", ["排列", "排列数公式", "组合", "组合数公式", "组合数性质", "排列组合综合"]),
                ("6.3", "二项式定理", ["二项式定理", "二项展开式通项", "二项式系数", "赋值法与系数和"]),
            ]),
            ("7", "随机变量及其分布", [
                ("7.1", "条件概率与全概率公式", ["条件概率", "乘法公式", "全概率公式", "贝叶斯公式"]),
                ("7.2", "离散型随机变量及其分布列", ["离散型随机变量", "分布列", "两点分布", "分布列性质"]),
                ("7.3", "二项分布与超几何分布", ["伯努利试验", "二项分布", "超几何分布", "二项分布与超几何分布辨析"]),
                ("7.4", "随机变量的数字特征", ["离散型随机变量均值", "离散型随机变量方差", "均值方差性质", "数字特征实际应用"]),
                ("7.5", "正态分布", ["正态曲线", "正态分布参数", "三倍标准差原则", "正态分布概率应用"]),
            ]),
            ("8", "成对数据的统计分析", [
                ("8.1", "成对数据的统计相关性", ["变量相关关系", "散点图", "相关系数", "相关性判断"]),
                ("8.2", "一元线性回归模型及其应用", ["经验回归直线", "最小二乘法", "残差分析", "回归预测"]),
                ("8.3", "列联表与独立性检验", ["二维列联表", "条件概率与独立性", "卡方统计量", "独立性检验"]),
            ]),
        ],
    ),
]


def row(**values: str) -> dict[str, str]:
    defaults = {
        "node_id": "",
        "parent_id": "",
        "volume": "",
        "node_type": "",
        "code": "",
        "name": "",
        "description": "",
        "prerequisite_node_ids": "",
        "primary_competencies": "数学抽象|逻辑推理|数学运算",
        "typical_question_types": "选择题|填空题|解答题",
        "common_errors": "",
        "gaokao_priority": "high",
        "status": "draft_for_teacher_review",
        "reviewed_by": "pending_owner_teacher",
    }
    defaults.update(values)
    return defaults


def build() -> list[dict[str, str]]:
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        required_one = list(csv.DictReader(handle))
    required_one[0]["parent_id"] = "pep_a"
    rows = [
        row(
            node_id="pep_a",
            volume="全册",
            node_type="textbook",
            code="PEP-A",
            name="人教A版高中数学",
            description="普通高中教科书数学A版五册课程树",
            primary_competencies="数学抽象|逻辑推理|数学运算|直观想象|数学建模|数据分析",
            typical_question_types="",
        ),
        *required_one,
    ]
    for volume_key, volume_name, chapters in VOLUMES:
        volume_id = f"pep_a_{volume_key}"
        rows.append(row(node_id=volume_id, parent_id="pep_a", volume=volume_name, node_type="volume", code=volume_key.upper(), name=volume_name, description=f"人教A版普通高中教科书数学{volume_name}", typical_question_types=""))
        for chapter_code, chapter_name, sections in chapters:
            chapter_id = f"pep_a_{volume_key}_c{chapter_code}"
            rows.append(row(node_id=chapter_id, parent_id=volume_id, volume=volume_name, node_type="chapter", code=chapter_code, name=chapter_name, description=chapter_name, typical_question_types=""))
            for section_code, section_name, knowledge_points in sections:
                section_token = section_code.replace(".", "_")
                section_id = f"pep_a_{volume_key}_c{chapter_code}_s{section_code.split('.')[-1]}"
                rows.append(row(node_id=section_id, parent_id=chapter_id, volume=volume_name, node_type="section", code=section_code, name=section_name, description=section_name, typical_question_types=""))
                for index, knowledge_point in enumerate(knowledge_points, start=1):
                    rows.append(row(node_id=f"kp_{volume_key}_{section_token}_{index:02d}", parent_id=section_id, volume=volume_name, node_type="knowledge_point", code=f"{section_code}.{index}", name=knowledge_point, description=knowledge_point))
    return rows


def main() -> None:
    rows = build()
    with TARGET.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} nodes to {TARGET}")


if __name__ == "__main__":
    main()
