




from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form

from schema import RestfulModel, CollectionData
from knowledge_service import (
    create_knowledge_base,
    delete_knowledge_base,
    list_builtin_knowledge_bases,
    select_knowledge_base,
)
from deps import get_uid

router = APIRouter(prefix="/collection", tags=["collection"])


@router.get("/list")
async def list_collections():
    return RestfulModel(data=list_builtin_knowledge_bases())


@router.post("/create")
async def add_collection_docs(
    uid: int = Depends(get_uid),
    file: bytes = File(...),
    collection_name: str = Form(...),
    collection_describe: Optional[str] = Form(None),
    create_time: str = Form(...),
):
    try:
        record = create_knowledge_base(
            collection_name=collection_name,
            collection_describe=collection_describe or "",
            create_time=create_time,
            file_bytes=file,
        )
        return RestfulModel(code=200, msg="Knowledge base created successfully", data=record)
    except Exception as e:
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}")


@router.post("/select")
async def select_collection(uid: int = Depends(get_uid), collection_data: CollectionData = Body()):
    try:
        record = select_knowledge_base(collection_data.collection_name)
        return RestfulModel(code=200, msg="Knowledge base selected successfully", data=record)
    except Exception as e:
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}")


@router.delete("/delete")
async def delete_collection(uid: int = Depends(get_uid), collection_name: str = None):
    try:
        delete_knowledge_base(collection_name)
        return RestfulModel(code=200, msg="Knowledge base deleted successfully")
    except Exception as e:
        return RestfulModel(code=-1, msg=f"An error occurred: {str(e)}")
