"""Deterministic provider used for development and tests without API charges."""

from photography_coach.providers.base import ProviderResult
from photography_coach.schemas.report import (
    DimensionAssessment,
    PhotographyDimensions,
    PhotographyReport,
    PriorityAction,
    ShootingExercise,
)


class MockPhotographyProvider:
    """Return a stable example report without inspecting or storing the image."""

    name = "mock"
    model = "mock-photography-coach-v1"

    async def analyze(
        self,
        image_bytes: bytes,
        media_type: str,
        shooting_intent: str | None,
    ) -> ProviderResult:
        del image_bytes, media_type, shooting_intent

        report = PhotographyReport(
            dimensions=PhotographyDimensions(
                composition=_assessment(
                    rating=4,
                    summary="主体位置清楚，画面结构容易理解。",
                    evidence=(
                        "主体位于画面左侧三分线附近，右侧保留了环境空间。"
                    ),
                    strength="主体与背景之间有足够分离，视觉重心明确。",
                    issue="右边缘的高亮小物体会分散注意力。",
                    suggestion=(
                        "拍摄前沿画面四条边检查一遍，"
                        "并向左移动半步排除干扰物。"
                    ),
                ),
                lighting=_assessment(
                    rating=3,
                    summary="光线能呈现主体，但明暗层次还可以更稳定。",
                    evidence="主体亮度足够，背景局部高光明显比主体更亮。",
                    strength="主体主要轮廓没有陷入阴影。",
                    issue="背景高光抢走了第一视觉落点。",
                    suggestion=(
                        "等待更柔和的侧光，或改变机位避开背景最亮区域。"
                    ),
                ),
                color=_assessment(
                    rating=4,
                    summary="主色关系简洁，主体颜色容易被识别。",
                    evidence="画面以冷色背景为主，主体的较暖颜色形成对比。",
                    strength="冷暖对比帮助主体从背景中突出。",
                    issue="边缘区域存在少量饱和度过高的颜色。",
                    suggestion=(
                        "构图时排除高饱和杂物，"
                        "并保持一种主色和一种强调色。"
                    ),
                ),
                subject_expression=_assessment(
                    rating=3,
                    summary="主体清楚，但最值得观看的细节还不够突出。",
                    evidence="主体占据适中面积，但动作或表情信息较弱。",
                    strength="观众能够快速确认照片的主要对象。",
                    issue="主体缺少一个能表达状态的关键瞬间。",
                    suggestion=(
                        "连续观察主体动作，"
                        "在姿态、视线或手势最明确时按下快门。"
                    ),
                ),
                visual_storytelling=_assessment(
                    rating=3,
                    summary="照片建立了场景，但故事线索仍然有限。",
                    evidence="环境空间存在，但没有明显说明主体正在做什么。",
                    strength="留白为环境信息和后续叙事保留了空间。",
                    issue="主体与环境之间缺少可读的互动关系。",
                    suggestion="下一次加入一个与主体行为直接相关的环境细节。",
                ),
            ),
            priority_actions=[
                PriorityAction(
                    priority=1,
                    action="拍摄前检查四条画面边缘，排除最亮的干扰物。",
                    reason="边缘高光会直接削弱主体的视觉优先级。",
                ),
                PriorityAction(
                    priority=2,
                    action="围绕主体左右各移动一步，比较背景亮度和形状。",
                    reason="小幅改变机位通常就能获得更干净的背景。",
                ),
                PriorityAction(
                    priority=3,
                    action="等待主体出现一个明确动作后再拍摄。",
                    reason="具体动作能同时加强主体表达和视觉叙事。",
                ),
            ],
            next_shooting_exercise=ShootingExercise(
                title="三机位干净背景练习",
                objective="练习在按快门前主动观察背景和画面边缘。",
                steps=[
                    "选择一个固定主体。",
                    "分别从左、中、右三个机位拍摄。",
                    "每次拍摄前检查画面四边是否出现高亮干扰物。",
                ],
                success_criteria=[
                    "三张照片都没有高亮物体贴近画面边缘。",
                    "能够说明哪一个机位最突出主体以及原因。",
                ],
            ),
        )
        return ProviderResult(report=report)


def _assessment(
    *,
    rating: int,
    summary: str,
    evidence: str,
    strength: str,
    issue: str,
    suggestion: str,
) -> DimensionAssessment:
    return DimensionAssessment(
        rating=rating,
        summary=summary,
        visual_evidence=[evidence],
        strengths=[strength],
        main_issue=issue,
        improvement_suggestions=[suggestion],
    )
