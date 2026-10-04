





import json
import os
import time

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, File, Form

from schema import (
    RestfulModel,
    UniversalRubricRequest,
    DraftRubricRequest,
    SimulationRequest,
    FinalRubricRequest,
    ReportRequest,
    WorkflowRubicSaveRequest,
    WorkflowRubricDetailRequest,
    WorkflowRegenerationRequest,
)
from utils import (
    to_serializable,
    merge_rubrics,
)
from service import (
    generate_draft_rubric,
    generate_universal_rubric,
    generate_dag_report,
    generate_simulation_results,
    generate_task_specific_rubric,
    workflow_regeneration_service,
    validate_edges_with_log_service,
)
from deps import get_uid

router = APIRouter(prefix="/workflow", tags=["workflow-rubric"])


@router.post("/rubic/save")
async def save_rubic(
    uid: int = Depends(get_uid),
    request_data: WorkflowRubicSaveRequest = Body(...),
):
    
    return RestfulModel(code=200, msg="Deprecated; nothing to save", data=None)


@router.get("/rubic/info/{workflow_id}")
async def get_rubic_info(workflow_id: int, uid: int = Depends(get_uid)):
    
    return RestfulModel(code=-1, msg="No workflow rubic found", data=None)


@router.post("/rubic/add")
async def add_rubic(uid: int = Depends(get_uid)):
    try:
        return RestfulModel(code=200, msg="Please create rubric task by custom input")
    except Exception as e:
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}")


@router.get("/rubic/list")
async def list_rubic(uid: int = Depends(get_uid)):
    
    return RestfulModel(code=200, msg="success", data=[])


@router.post("/rubric/detail")
async def get_workflow_rubric_detail(
    uid: int = Depends(get_uid),
    req: WorkflowRubricDetailRequest = Body(...),
):
    
    
    return RestfulModel(
        code=200,
        msg="No workflow rubric record found",
        data=None,
    )


@router.post("/rubric/validate-edges")
async def validate_edges_with_log(
    uid: int = Depends(get_uid),
    workflow_id: int = Form(...),
    sim_results: str = Form(...),
    file: UploadFile = File(...),
):




    try:
        
        backend_dir = os.path.dirname(os.path.dirname(__file__))
        log_dir = os.path.join(backend_dir, "data", "logs", str(workflow_id))
        os.makedirs(log_dir, exist_ok=True)
        safe_filename = f"validate_{workflow_id}_{int(time.time())}.xes"
        log_file_path = os.path.join(log_dir, safe_filename)
        content = await file.read()
        with open(log_file_path, "wb") as f:
            f.write(content)
        print(f"Execution log saved: {log_file_path}")

        
        sim_data = json.loads(sim_results)
        if not isinstance(sim_data, dict) or "task_links" not in sim_data:
            return RestfulModel(
                code=-1,
                msg="sim_results is missing the task_links field",
                data=None,
            )

        
        updated_sim = validate_edges_with_log_service(sim_data, log_file_path)

        
        return RestfulModel(
            code=200,
            msg="Log edge validation completed",
            data={
                "conformance_results": updated_sim,
                "log_file_path": log_file_path,
            },
        )

    except Exception as e:
        print("validate_edges_with_log error =", repr(e))
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}", data=None)


@router.post("/rubic/update")
async def upsert_rubic(req: dict):
    
    return RestfulModel(code=200, msg="success")


@router.delete("/rubic/delete/{id}")
async def delete_rubic(id: int):
    
    return RestfulModel(code=200, msg="workflow evalute delete successfully")


@router.post("/rubric/universal")
async def generate_workflow_universal_rubric(
    uid: int = Depends(get_uid),
    req: UniversalRubricRequest = Body(...),
):
    try:
        workflow_id = int(req.workflow_id)
        task = req.task

        universal_rubric = await generate_universal_rubric(task)
        serializable_rubric = to_serializable(universal_rubric)

        
        record_id = None

        return RestfulModel(
            code=200,
            msg="Universal rubric generated successfully",
            data={
                "id": record_id,
                "workflow_id": workflow_id,
                "task": task,
                "universal_rubric": serializable_rubric,
            },
        )
    except Exception as e:
        print("generate_workflow_universal_rubric error =", repr(e))
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}", data=None)


@router.post("/rubric/draft")
async def draft_rubric(req: DraftRubricRequest):
    try:
        result = await generate_draft_rubric(req.task)

        dimensions_json = [
            {
                "theme": d.theme,
                "tips": d.tips,
                "weight": d.weight,
                "description": d.description,
            }
            for d in result.dimensions
        ]
        
        return RestfulModel(
            code=200,
            msg="success",
            data={"dimensions": dimensions_json},
        )
    except Exception as e:
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}", data=None)


@router.post("/rubric/simulation")
async def generate_workflow_simulation_results(req: SimulationRequest):
    try:
        task = req.task

        
        print(f"[DEBUG] /rubric/simulation received task keys: {list(task.keys()) if isinstance(task, dict) else type(task)}")
        if isinstance(task, dict):
            print(f"[DEBUG] task_nodes count: {len(task.get('task_nodes', []))}")
            print(f"[DEBUG] task_links count: {len(task.get('task_links', []))}")
            print(f"[DEBUG] task preview: {str(task)[:500]}")

        sim_results = await generate_simulation_results(task)

        
        return RestfulModel(
            code=200,
            msg="success",
            data={"sim_results": sim_results},
        )
    except Exception as e:
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}", data=None)


@router.post("/rubric/final")
async def generate_final_rubric(req: FinalRubricRequest):
    try:
        task = req.task

        
        
        sim_results = req.sim_results
        print("sim_results (from request) =", sim_results)

        final_rubric = await generate_task_specific_rubric(
            sim_results=sim_results,
            task=task,
        )
        print("final_rubric =", final_rubric)

        return RestfulModel(
            code=200,
            msg="success",
            data={"final_rubric": final_rubric},
        )
    except Exception as e:
        print("generate_final_rubric error =", e)
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}", data=None)


@router.post("/rubric/report")
async def report(req: ReportRequest):
    print("Entered /workflow/rubric/report")
    print("req", req)

    try:
        final_rubric = req.final_rubric or []
        universal_rubric = req.universal_rubric or []
        print("final_rubric (task-specific)", final_rubric)
        print("universal_rubric (generic)", universal_rubric)

        if not final_rubric and not universal_rubric:
            return RestfulModel(
                code=-1,
                msg="No rubric dimensions selected.",
                data=None,
            )

        
        
        conformance_results = req.conformance_results

        
        result_dict = await generate_dag_report(
            task=req.task,
            rubric=final_rubric if final_rubric else None,
            conformance_results=conformance_results,
            universal_rubric=universal_rubric if universal_rubric else None,
        )

        print("result_dict =", result_dict)

        return RestfulModel(code=200, msg="success", data=result_dict)

    except Exception as e:
        import traceback

        print("report error =", repr(e))
        traceback.print_exc()
        return RestfulModel(code=-1, msg=str(e), data=None)


@router.post("/rubric/Regeneration")
async def workflow_regeneration_api(req: WorkflowRegenerationRequest):
    print("req", req)
    try:
        optimized_workflow = await workflow_regeneration_service(
            task=req.task,
            original_workflow=req.original_workflow,
            sim_results=req.sim_results,
        )

        
        return {
            "code": 200,
            "msg": "Workflow regenerated successfully",
            "data": {"optimized_workflow": optimized_workflow},
        }
    except Exception as e:
        return {"code": 500, "msg": str(e), "data": None}


@router.post("/rubric/generate_xml")
async def generate_xml_from_revised_workflow(req: dict):

    try:
        workflow_id = req.get("workflow_id")
        revised_workflow = req.get("revised_workflow")

        if not workflow_id or not revised_workflow:
            return {"code": 400, "msg": "workflow_id and revised_workflow are required", "data": None}

        
        dag_data = revised_workflow

        
        from src.generation.chains.write_xml import write_xml_chain

        xml_result = write_xml_chain.invoke({
            "dag": json.dumps(dag_data, ensure_ascii=False)
        })

        
        return {
            "code": 200,
            "msg": "XML generated successfully",
            "data": {"xml_result": xml_result},
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"code": 500, "msg": str(e), "data": None}
