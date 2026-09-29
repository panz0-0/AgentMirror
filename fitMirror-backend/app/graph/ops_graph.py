"""运营流水线图执行器：封装 Stage1→Stage2→Stage3→出图 的分段调用。"""
import asyncio

from app.graph.state import FitMirrorState


class OpsGraphRunner:
    """运营流水线：stage1 → stage2 → (confirm) → stage3 → (confirm) → images"""

    async def run_until_pause(
        self,
        state: FitMirrorState,
        sku_record,
        workspace,
        stop_at: str = "campaign",
    ) -> FitMirrorState:
        from app.graph.nodes.pipeline_nodes import load_sku_node, stage1_node, stage2_node

        out = load_sku_node(state, sku_record, workspace)
        state = {**state, **out}

        if stop_at in ("stage1", "campaign", "stage2", "prompts", "stage3", "images"):
            if not state.get("product_json"):
                out = await asyncio.to_thread(stage1_node, state, sku_record, workspace)
                state = {**state, **out}

        if stop_at in ("campaign", "stage2", "prompts", "stage3", "images"):
            if not state.get("campaign_json"):
                out = await asyncio.to_thread(stage2_node, state, sku_record, workspace)
                state = {**state, **out}
            else:
                state["awaiting_confirm"] = "campaign"

        return state

    async def resume_stage3(self, state: FitMirrorState, sku_record, workspace) -> FitMirrorState:
        from app.graph.nodes.pipeline_nodes import stage3_node

        out = await asyncio.to_thread(stage3_node, state, sku_record, workspace)
        return {**state, **out}

    async def resume_images(
        self, state: FitMirrorState, sku_record, workspace, output_dir
    ) -> FitMirrorState:
        from app.graph.nodes.pipeline_nodes import generate_images_node

        out = await asyncio.to_thread(generate_images_node, state, sku_record, workspace, output_dir)
        return {**state, **out}


ops_runner = OpsGraphRunner()
