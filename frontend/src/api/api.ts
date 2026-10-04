import {
  CollectionType,
  PromptInfo,
  PromptParamsResponse,
  RequestData,
  RetrievedDocs,
  WorkflowInfoPayload,
  WorkflowType,
  WorkflowRunRecord,
} from './schema';

import ApiService from './apiService';
import { RemoteRunnable } from '@langchain/core/runnables/remote';
import { Runnable } from '@langchain/core/runnables';
import { apiBaseUrl_rubic } from '@/utils/constants';

// The rubric service handles workflow generation, evaluation, and knowledge-base APIs.
// Keep the existing variable spelling to avoid breaking imports.
const apiService_rubic = new ApiService({
  baseURL: apiBaseUrl_rubic,
});

const runnableConfigs = {
  options: {
    // Backend model chains can take more than 60 seconds. Match ApiService's long timeout
    // so the frontend does not terminate the request first.
    timeout: 3000000,
  },
};

// LangChain RemoteRunnable endpoints for each workflow-generation stage.
export const create_game_chain = new RemoteRunnable({
  url: `${apiBaseUrl_rubic}/workflow/create_game`,
  ...runnableConfigs,
});

export const modify_extraction_chain: Runnable = new RemoteRunnable({
  url: `${apiBaseUrl_rubic}/workflow/modify_extraction`,
  ...runnableConfigs,
});

export const custom_api_chain: Runnable = new RemoteRunnable({
  url: `${apiBaseUrl_rubic}/workflow/api/custom`,
  ...runnableConfigs,
});

export const write_dag_chain: Runnable = new RemoteRunnable({
  url: `${apiBaseUrl_rubic}/workflow/write_dag`,
  ...runnableConfigs,
});

export const write_xml_chain: Runnable = new RemoteRunnable({
  url: `${apiBaseUrl_rubic}/workflow/write_xml`,
  ...runnableConfigs,
});

// ========================================== workflow ==========================================
// Workflow-generation CRUD and detail endpoints.
export const addWorkflow = async (
  session_id: string
): Promise<RequestData<{ id: number }>> => {
  return apiService_rubic.get(`/workflow/add`, { params: { session_id } });
};

export const updateWorkflow = async (
  data: WorkflowInfoPayload
): Promise<RequestData<WorkflowInfoPayload>> => {
  return apiService_rubic.post(`/workflow/update`, data);
};

export const deleteWorkflow = async (
  id: string
): Promise<RequestData<unknown>> => {
  return apiService_rubic.delete(`/workflow/delete`, {
    params: { id },
  });
};

export const getWorkflowList = async (): Promise<
  RequestData<WorkflowType[]>
> => {
  return apiService_rubic.get(`/workflow/list`);
};

export const getWorkflowInfoById = async (
  id: string
): Promise<RequestData<WorkflowInfoPayload>> => {
  return apiService_rubic.get(`/workflow/info/${id}`);
};

// Stage 3: rewrite the query with the backend QueryRewriter instead of RemoteRunnable.
export const rewriteQueries = async (data: {
  text: string;
  k?: number;
}): Promise<RequestData<string[]>> => {
  return apiService_rubic.post(`/workflow/rewrite`, data);
};

export const getRetrieveDocs = async (data: {
  queries: string[];
  task_steps?: string[];
}): Promise<RequestData<RetrievedDocs>> => {
  return apiService_rubic.post(`/workflow/retrieve/docs`, data);
};
// ========================================== workflowrubic ==========================================
// Workflow-evaluation task, rubric, report, and regeneration endpoints.
// Preserve the backend's existing endpoint names.


export const generateUniversalRubric = async (data: {
  workflow_id: string;
  task: any;
}) => {
  return apiService_rubic.post('/workflow/rubric/universal', data);
};

export const generateSimulationResults = async (data: {
  workflow_id: string;
  task: any;
}) => {
  console.log('simulation request ->', apiBaseUrl_rubic + '/workflow/rubric/simulation');
  return apiService_rubic.post('/workflow/rubric/simulation', data);
};

export const generateFinalRubric = async (data: {
  workflow_id: string;
  task: any;
  sim_results: any;
}) => {
  console.log('final rubric request ->', apiBaseUrl_rubic + '/workflow/rubric/final');
  return apiService_rubic.post('/workflow/rubric/final', data);
};

export const generateReport = async (data: {
  workflow_id: string;
  task: any;
  universal_rubric: any[];
  final_rubric: any[];
}) => {
  return apiService_rubic.post('/workflow/rubric/report', data);
};
export const getWorkflowEvaluateDetail = async (data: { workflow_id: string }) => {
  return apiService_rubic.post('/workflow/rubric/detail', data);
};

export function workflowRegeneration(data: any) {
  return apiService_rubic.post('/workflow/rubric/Regeneration', data);
}

export function generateXmlFromRevisedWorkflow(data: {
  workflow_id: string;
  revised_workflow: any;
}) {
  return apiService_rubic.post('/workflow/rubric/generate_xml', data);
}

export function validateEdgesWithLog(data: FormData) {
  return apiService_rubic.post('/workflow/rubric/validate-edges', data, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
}

// ========================================== workflow runs ==========================================
// V2 deterministic orchestration and version history.
const RUN_READ_TIMEOUT_MS = 12000;

export const startWorkflowRun = async (
  workflowId: string,
  data: {
    description: string;
    max_iterations: number;
    regeneration_threshold: number;
    acceptance_threshold: number;
    auto_repair: boolean;
  }
): Promise<RequestData<WorkflowRunRecord>> => {
  return apiService_rubic.post(`/workflow/${workflowId}/runs`, data);
};

export const getLatestWorkflowRun = async (
  workflowId: string
): Promise<RequestData<WorkflowRunRecord | null>> => {
  return apiService_rubic.get(`/workflow/${workflowId}/runs/latest`, {
    timeout: RUN_READ_TIMEOUT_MS,
  });
};

export const getWorkflowRun = async (
  runId: string
): Promise<RequestData<WorkflowRunRecord>> => {
  return apiService_rubic.get(`/workflow/runs/${runId}`, {
    timeout: RUN_READ_TIMEOUT_MS,
  });
};

export const stopWorkflowRun = async (
  runId: string
): Promise<RequestData<WorkflowRunRecord>> => {
  return apiService_rubic.post(`/workflow/runs/${runId}/stop`);
};

export const retryWorkflowRun = async (
  runId: string
): Promise<RequestData<WorkflowRunRecord>> => {
  return apiService_rubic.post(`/workflow/runs/${runId}/retry`);
};

export const acceptWorkflowVersion = async (
  runId: string,
  versionNo: number
): Promise<RequestData<WorkflowRunRecord>> => {
  return apiService_rubic.post(
    `/workflow/runs/${runId}/versions/${versionNo}/accept`
  );
};

export const validateWorkflowRunVersionLog = async (
  runId: string,
  versionNo: number,
  file: File
): Promise<RequestData<WorkflowRunRecord>> => {
  const data = new FormData();
  data.append('file', file);
  return apiService_rubic.post(
    `/workflow/runs/${runId}/versions/${versionNo}/validate-log`,
    data,
    { headers: { 'Content-Type': 'multipart/form-data' } }
  );
};

export const confirmWorkflowDependencyReview = async (
  runId: string,
  versionNo: number,
  taskLinks: Array<{ source: string; target: string; status: 'pass' | 'warn' }>
): Promise<RequestData<WorkflowRunRecord>> => {
  return apiService_rubic.post(
    `/workflow/runs/${runId}/versions/${versionNo}/dependency-review`,
    { task_links: taskLinks }
  );
};
// ========================================== prompt ==========================================
// Prompt and retrieval-parameter endpoints used to display and invoke backend prompt settings.
export const getPromptInfo = async (): Promise<RequestData<PromptInfo>> => {
  return apiService_rubic.get(`/workflow/prompt/info`);
};

export const getPromptParams = async (
  id: string
): Promise<RequestData<PromptParamsResponse>> => {
  return apiService_rubic.get(`/workflow/retrieve/params/${id}`);
};
// ========================================== collection ==========================================
// Tool knowledge-base collection management endpoints.
export const getCollectionList = async (): Promise<
  RequestData<CollectionType[]>
> => {
  return apiService_rubic.get(`/collection/list`);
};

export const createCollection = async (
  data: FormData
): Promise<RequestData<CollectionType>> => {
  return apiService_rubic.post(`/collection/create`, data, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
};

export const selectCollection = async (data: {
  collection_name: string;
}): Promise<RequestData<unknown>> => {
  return apiService_rubic.post(`/collection/select`, data);
};

export const deleteCollection = async (
  collection_name: string
): Promise<RequestData<unknown>> => {
  return apiService_rubic.delete(`/collection/delete`, {
    params: { collection_name },
  });
};
