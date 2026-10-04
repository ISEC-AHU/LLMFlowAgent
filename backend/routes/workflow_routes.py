





import json

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from schema import RestfulModel, TaskInfo, PromptInfo, QueryData, RewriteRequest
from deps import db, get_uid
from knowledge_service import retrieve_tools, tools_to_retrieved_docs, rewrite_queries

router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.get("/list")
async def list_workflow(uid: int = Depends(get_uid)):
    try:
        query = """
            SELECT
                w.id,
                w.describe,
                latest_run.id AS run_id,
                latest_run.status AS run_status,
                latest_run.current_version,
                latest_run.best_version,
                latest_run.final_version,
                latest_run.updated_at,
                selected_version.composite_score AS final_score
            FROM workflow w
            LEFT JOIN LATERAL (
                SELECT
                    id, status, current_version, best_version,
                    final_version, updated_at
                FROM workflow_run
                WHERE workflow_id = w.id
                ORDER BY updated_at DESC
                LIMIT 1
            ) latest_run ON TRUE
            LEFT JOIN workflow_version selected_version
                ON selected_version.run_id = latest_run.id
               AND selected_version.version_no = COALESCE(
                   latest_run.final_version,
                   latest_run.best_version,
                   latest_run.current_version
               )
            WHERE w.uid = %s
            ORDER BY w.id DESC;
        """
        workflow_records = db.fetch_query(query, (uid,))
        converted_data = [
            {
                "id": item["id"],
                "describe": item["describe"],
                "run_id": item["run_id"],
                "run_status": item["run_status"],
                "current_version": item["current_version"],
                "best_version": item["best_version"],
                "final_version": item["final_version"],
                "updated_at": item["updated_at"],
                "final_score": item["final_score"],
            }
            for item in workflow_records
        ]
        return RestfulModel(data=converted_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@router.get("/add")
async def add_workflow(
    uid: int = Depends(get_uid),
    session_id: str = Query(..., description="Session ID for create workflow message store"),
):
    try:
        query = """
              INSERT INTO workflow (uid, create_game_session_id)
              VALUES (%s, %s)
              """
        params = (uid, session_id,)
        db.execute_query(query, params)
        res = db.fetch_query(
            """
            SELECT id from workflow where uid = %s and create_game_session_id = %s ORDER BY id DESC LIMIT 1""",
            (uid, session_id,),
        )
        if res:
            return RestfulModel(data={"id": res[0]['id']}, msg="Workflow created successfully")
        else:
            return RestfulModel(code=-1, msg="No workflow found")
    except Exception as e:
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}")


@router.delete("/delete")
async def delete_workflow(
    uid: int = Depends(get_uid),
    id: int = Query(..., description="Workflow ID to delete"),
):
    try:
        
        res = db.fetch_query(
            """
            SELECT id 
            FROM workflow 
            WHERE id = %s AND uid = %s
            LIMIT 1
            """,
            (id, uid),
        )

        if not res:
            return RestfulModel(
                code=-1,
                msg="Workflow not found or you do not have permission to delete it",
            )

        
        db.execute_query(
            "DELETE FROM workflow_run WHERE workflow_id = %s",
            (id,),
        )

        
        db.execute_query(
            """
            DELETE FROM workflow 
            WHERE id = %s AND uid = %s
            """,
            (id, uid),
        )

        return RestfulModel(data={"id": id}, msg="Workflow deleted successfully")

    except Exception as e:
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}")


@router.post("/update")
async def update_workflow(update_data=Body(...)):
    # TODO: validate params
    if not update_data:
        raise HTTPException(status_code=400, detail="No update data provided")
    update_fields = update_data
    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    if 'api_list' in update_fields:
        update_fields['api_list'] = json.dumps((update_fields['api_list']))

    set_clause = ", ".join([f"{field} = %({field})s" for field in update_fields])
    query = f"UPDATE workflow SET {set_clause} WHERE id = %(id)s"

    db.execute_query(query, update_fields)
    return {"msg": "Workflow updated successfully"}


@router.get("/info/{workflow_id}")
async def get_workflow_info(workflow_id: int = Path(..., title="The ID of the workflow")):
    try:
        query = """
               SELECT * FROM workflow w WHERE id = %s;
           """
        record = db.fetch_query(query, (workflow_id,))
        if record[0]:
            data = {
                'id': record[0]['id'],
                'session_id': record[0]['create_game_session_id'],
                'describe': record[0]['describe'],
                'extracted_task': record[0]['extracted_task'],
                'rewrite_queries': record[0]['rewrite_queries'],
                'api_list': record[0]['api_list'],
                'dag': record[0]['dag'],
                'xml': record[0]['xml'],
            }
            return RestfulModel(data=data)
        else:
            return RestfulModel(code=-1, msg="No workflow found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@router.get("/retrieve/params/{workflow_id}")
async def get_workflow_describe(workflow_id: int = Path(..., title="The ID of the workflow")):
    try:
        query = """
        SELECT extracted_task, rewrite_queries from workflow where id=%s
        """
        res = db.fetch_query(query, (workflow_id,))
        text = res[0]['extracted_task']
        if res[0]['rewrite_queries']:
            k = len(res[0]['rewrite_queries'])
        else:
            k = len(text.split('\n'))
        if text:
            return RestfulModel[TaskInfo](data={'text': text, 'k': k})
        else:
            return RestfulModel(code=-1, msg="No workflow found")
    except Exception as e:
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}")


@router.post("/rewrite")
async def rewrite_workflow_queries(req: RewriteRequest = Body()):




    try:
        queries = rewrite_queries(req.text)
        if not queries:
            return RestfulModel(code=-1, msg="No valid steps found in text")
        return RestfulModel(data=queries)
    except Exception as e:
        return RestfulModel(code=-1, msg=f"Rewrite failed: {str(e)}")


@router.post("/retrieve/docs")
async def get_relevant_docs(uid: int = Depends(get_uid), requestData: QueryData = Body()):
    try:
        # print("requestData.queries", requestData.queries)
        # print("requestData.task_steps", requestData.task_steps)

        
        rewritten_queries = [q.strip() for q in (requestData.queries or []) if q and q.strip()]
        
        original_steps = [s.strip() for s in (requestData.task_steps or []) if s and s.strip()]

        if not rewritten_queries:
            return RestfulModel(code=-1, msg="queries cannot be empty")

        retrieved_tools = retrieve_tools(
            original_steps=original_steps,
            rewritten_queries=rewritten_queries,
            top_k=len(rewritten_queries) + 5,
            rerank_n=len(rewritten_queries) + 2,
        )
        docs = tools_to_retrieved_docs(retrieved_tools)
        # print("generation retriever docs", docs)
        return RestfulModel(data=docs)
    except Exception as e:
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}")
