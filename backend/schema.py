
from pydantic import BaseModel
from typing import Any, List, Optional,Generic,TypeVar,Dict
from pydantic.generics import GenericModel
T = TypeVar('T')


class UniversalRubricRequest(BaseModel):
    workflow_id: str
    task: Any

class DraftRubricRequest(BaseModel):
    workflow_id: str
    task: Any


class RestfulModel(GenericModel, Generic[T]):
    code: int = 200
    msg: Optional[str] = "OK"
    data: Optional[T]= None


class SimulationRequest(BaseModel):
    workflow_id: str
    task: Dict[str, Any]


class SimulationResponse(BaseModel):
    success: bool
    workflow_id: str
    sim_results: Dict[str, Any]




class FinalRubricRequest(BaseModel):
    workflow_id: str
    task: Dict[str, Any]
    sim_results: Dict[str, Any]


class FinalRubricResponse(BaseModel):
    code: int
    msg: str
    data: Dict[str, Any]

class ReportRequest(BaseModel):
    workflow_id: str
    task: Any
    universal_rubric: Optional[List[Any]] = None
    final_rubric: Optional[List[Any]] = None
    # Edge-level log validation produced by validate-edges. This was formerly stored
    # in the removed legacy rubic table and is now supplied by the caller; None means
    # no log-validation result was provided.
    conformance_results: Optional[Any] = None

class WorkflowRegenerationRequest(BaseModel):
    workflow_id: int | str
    task: Any
    sim_results: Optional[Any] = None
    original_workflow: Optional[Any] = None


class WorkflowRunStartRequest(BaseModel):
    description: str
    max_iterations: int = 3
    regeneration_threshold: float = 1.0
    acceptance_threshold: float = 4.0
    auto_repair: bool = True


class DependencyReviewRequest(BaseModel):
    task_links: List[Dict[str, Any]]


class WorkflowRubicSaveRequest(BaseModel):
    workflow_id: int

class WorkflowRubricDetailRequest(BaseModel):
    workflow_id: str
    task: Optional[Any] = None

class CollectionData(BaseModel):
    collection_name: str
    collection_describe: Optional[str] = None


# ------------------------------------------------------------------
# The models below were consolidated from src/model_generator/schema.py.
# ------------------------------------------------------------------

class PromptInfo(BaseModel):
    create_game_prompt: str
    rewrite_query_prompt: str
    write_dag_prompt: str
    write_xml_prompt: str


class TaskInfo(BaseModel):
    text: str
    k: int


class QueryData(BaseModel):
    queries: List[str]
    task_steps: Optional[List[str]] = None


class RewriteRequest(BaseModel):
    """Query rewrite request replacing the LangChain rewrite_query endpoint."""
    text: str
    k: Optional[int] = None


class UpdateWorkflow(BaseModel):
    id: int
    session_id: Optional[str] = None
    describe: Optional[str] = None
    extracted_task: Optional[str] = None
    rewrite_queries: Optional[list] = None
    api_list: Optional[list] = None
    dag: Optional[str] = None
    xml: Optional[str] = None
