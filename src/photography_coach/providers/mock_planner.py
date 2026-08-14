"""Stable retrieval planner for local development without model charges."""

from photography_coach.knowledge.retrieval import (
    PhotoObservation,
    RetrievalPlan,
    RetrievalQuery,
    VisibleEvidence,
)
from photography_coach.providers.planner import PlannerResult


class MockRetrievalPlanner:
    """Return a valid example plan without inspecting or retaining the image."""

    name = "mock"
    model = "mock-photography-retrieval-v1"

    async def create_plan(
        self,
        image_bytes: bytes,
        media_type: str,
        shooting_intent: str | None,
    ) -> PlannerResult:
        del image_bytes, media_type

        observation = PhotoObservation(
            scene_summary="主体位于环境之中，画面同时包含明显亮区和背景元素。",
            evidence=[
                VisibleEvidence(
                    evidence_id="composition-background",
                    dimension="composition",
                    description="主体周围存在具有清晰边缘的背景元素，可能参与注意力分配。",
                    location="主体周围和画面边缘",
                ),
                VisibleEvidence(
                    evidence_id="lighting-bright-area",
                    dimension="lighting",
                    description="画面中的明亮区域与主体之间形成了可以直接观察的亮度差异。",
                    location="主体和画面最明亮区域",
                ),
                VisibleEvidence(
                    evidence_id="color-relationship",
                    dimension="color",
                    description="画面中主体颜色与环境颜色形成了可以直接比较的色彩关系。",
                    location="主体及其周围环境",
                ),
                VisibleEvidence(
                    evidence_id="subject-attention",
                    dimension="subject_expression",
                    description="画面存在可以辨认的注意中心，其形状和环境关系参与主体表达。",
                    location="画面主要注意区域",
                ),
                VisibleEvidence(
                    evidence_id="story-environment",
                    dimension="visual_storytelling",
                    description="主体与周围环境元素同时出现，但两者关系需要通过画面线索建立。",
                    location="主体及其周围环境",
                ),
            ],
            unknowns=[
                "无法仅凭图片确定相机、镜头和曝光参数",
                "无法仅凭图片确定地点、事件经过和主体真实心理",
            ],
        )
        plan = RetrievalPlan(
            user_intent=shooting_intent,
            observation=observation,
            queries=[
                RetrievalQuery(
                    query_id="composition-background-query",
                    dimension="composition",
                    evidence_ids=["composition-background"],
                    query_text="环境中的清晰背景元素与主体争夺注意力时，怎样调整取景和机位？",
                    teaching_goal="简化背景并保持环境信息",
                    top_k=2,
                ),
                RetrievalQuery(
                    query_id="lighting-bright-area-query",
                    dimension="lighting",
                    evidence_ids=["lighting-bright-area"],
                    query_text="画面亮区明显强于主体时，怎样安排主体细节和背景亮度关系？",
                    teaching_goal="控制亮度关系并突出主体",
                    top_k=2,
                ),
                RetrievalQuery(
                    query_id="color-relationship-query",
                    dimension="color",
                    evidence_ids=["color-relationship"],
                    query_text="主体与环境颜色同时出现时，怎样建立清楚的主色和强调色关系？",
                    teaching_goal="用色彩层级支持注意中心",
                    top_k=1,
                ),
                RetrievalQuery(
                    query_id="subject-attention-query",
                    dimension="subject_expression",
                    evidence_ids=["subject-attention"],
                    query_text="主体不是人物时，怎样用形状、纹理和环境关系建立清楚的表达？",
                    teaching_goal="不依赖人物也能明确主体表达",
                    top_k=1,
                ),
                RetrievalQuery(
                    query_id="story-environment-query",
                    dimension="visual_storytelling",
                    evidence_ids=["story-environment"],
                    query_text="单张照片中怎样用主体与环境的可见关系建立清楚的叙事线索？",
                    teaching_goal="用可见证据加强视觉叙事",
                    top_k=1,
                ),
            ],
            max_total_chunks=6,
        )
        return PlannerResult(plan=plan)
