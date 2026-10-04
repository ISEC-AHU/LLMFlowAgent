








from fastapi import APIRouter, HTTPException

from pydantic import BaseModel
from typing import Any, Dict, Optional

from schema import RestfulModel, PromptInfo

from src.generation.chains.create_game import init_prompt, create_game_chain_with_history
from src.generation.chains.write_dag import WRITE_DAG_PROMPT, write_dag_chain
from src.generation.chains.write_xml import write_xml_chain, init_prompt
from src.generation.retriever.query_rewriter import REWRITE_QUERY_PROMPT
from utils import get_workflow_id

router = APIRouter(prefix="/workflow", tags=["workflow-chains"])


class InvokeConfigurable(BaseModel):
    session_id: Optional[str] = None


class InvokeConfig(BaseModel):
    configurable: Optional[InvokeConfigurable] = None


class InvokeRequest(BaseModel):
    input: Dict[str, Any]
    config: Optional[InvokeConfig] = None


class CreateGameRequest(BaseModel):
    input: str
    session_id: str


@router.post("/create_game")
async def create_game(req: CreateGameRequest):
    result = create_game_chain_with_history.invoke(
        {"input": req.input},
        config={"configurable": {"session_id": req.session_id}},
    )
    return RestfulModel(data=result)


@router.post("/create_game/invoke")
async def create_game_invoke(req: InvokeRequest):
    result = create_game_chain_with_history.invoke(
        req.input,
        req.config.dict(),
    )
    return {"output": result}


@router.post("/write_dag/invoke")
async def write_dag_invoke(req: InvokeRequest):
    try:
        cfg = req.config.dict() if req.config else None
        data = req.input or {}

        text = data.get("text", "")
        api_list = data.get("api_list", "[]")
        generation_feedback = data.get("generation_feedback", "")

        real_input = {
            "text": text,
            "api_list": api_list,
            "generation_feedback": generation_feedback,
        }

        # print("write_dag real_input =", real_input)
        # print("write_dag config =", cfg)

        result = write_dag_chain.invoke(real_input, config=cfg)
        return {"output": result}
    except Exception as e:
        print("write_dag_invoke error =", repr(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/write_xml/invoke")
async def write_xml_invoke(req: InvokeRequest):
    try:
        cfg = req.config.dict() if req.config else None

        # print("write_xml req.input =", req.input)
        # print("write_xml req.config =", cfg)

        workflow_id = get_workflow_id(req.input, cfg)

        # print("workflow_id =", workflow_id)

        if workflow_id is None:
            raise ValueError("workflow_id is required when generating XML")

        result = write_xml_chain.invoke(
            req.input,
            config=cfg,
        )

        return {"output": result}

    except Exception as e:
        import traceback

        traceback.print_exc()
        print("write_xml_invoke error =", repr(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prompt/info")
async def get_prompts_info():
    return RestfulModel[PromptInfo](
        data={
            'create_game_prompt': init_prompt,
            'rewrite_query_prompt': REWRITE_QUERY_PROMPT,
            'write_dag_prompt': WRITE_DAG_PROMPT,
            'write_xml_prompt': init_prompt,
        }
    )
