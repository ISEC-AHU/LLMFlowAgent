/*
 * @Author: jinglongfang
 * @Date: 2024-05-16 14:40:18
 * @LastEditors: jinglongfang
 * @LastEditTime: 2024-05-21 14:41:52
 * @FilePath: \workflow-frontend\src\api\schema.ts
 * @Description:
 */
export interface RequestData<T> {
  code: number;
  data: T;
  msg?: string;
}

export interface WorkflowInfoPayload {
  id: string;
  uid?: number;
  session_id?: string;
  describe?: string;
  extracted_task?: string;
  rewrite_queries?: string[];
  api_list?: any[];
  dag?: string;
  xml?: string;
}

export interface PromptInfo {
  [key: string]: string;
}

export interface PromptParamsResponse {
  k?: number;
  text: string;
}

export interface EmbeddingType {
  page_content: string;
  metadata: {
    source: string;
    seq_num: number;
  };
  type: string;
}

export interface RetrievedDocs {
  [key: string]: {
    doc: EmbeddingType[];
    score: number;
  }[];
}

export type CollectionType = {
  key?: string;
  collection_name: string;
  collection_describe?: string;
  create_time: string;
  file?: FormData;
};

export type WorkflowType = {
  id: number;
  describe?: string;
  run_id?: string;
  run_status?: string;
  current_version?: number;
  best_version?: number;
  final_version?: number;
  updated_at?: number;
  final_score?: number;
};

export interface WorkflowRunEvent {
  id: number;
  run_id: string;
  event_type: string;
  agent?: string;
  step?: string;
  version_no?: number;
  message: string;
  payload?: any;
  created_at: number;
}

export interface WorkflowVersionRecord {
  id: number;
  run_id: string;
  workflow_id: number;
  version_no: number;
  parent_version_no?: number;
  dag: any;
  xml?: string;
  simulation_results?: any;
  universal_rubric?: any[];
  final_rubric?: any[];
  evaluation_report?: any;
  issues?: any[];
  repair_plan?: any;
  repair_summary?: any;
  generic_score?: number;
  task_specific_score?: number;
  composite_score?: number;
  hard_constraints_passed: boolean;
  validation_results?: any;
  fingerprint: string;
  status: string;
  created_at: number;
}

export interface WorkflowRunRecord {
  id: string;
  workflow_id: number;
  description: string;
  status: string;
  active_agent?: 'coordinator' | 'generation' | 'evaluation' | 'repair';
  active_step?: string;
  current_iteration: number;
  max_iterations: number;
  current_version?: number;
  best_version?: number;
  final_version?: number;
  regeneration_threshold: number;
  acceptance_threshold: number;
  auto_repair: boolean;
  stop_requested: boolean;
  error_message?: string;
  started_at?: number;
  completed_at?: number;
  updated_at: number;
  versions: WorkflowVersionRecord[];
  events: WorkflowRunEvent[];
}
