export interface TaskNode {
  id?: string;
  name?: string;
  label?: string;
  task?: string;
  description?: string;
  arguments?: any[];
  [key: string]: any;
}

export interface TaskLink {
  source: string;
  target: string;
  [key: string]: any;
}

export interface DagData {
  task_nodes: TaskNode[];
  task_links: TaskLink[];
  [key: string]: any;
}

export interface EvaluateRecord {
  id?: string;
  uid?: string;
  workflow_id?: string;
  task?: any;
  universal_rubric?: any;
  univeral_rubric?: any;
  draft_rubric?: any;
  sim_results?: any;
  report?: any;
  final_rubric?: any;
  create_time?: string;
  update_time?: string;
  [key: string]: any;
}

export type StatusType = 'pass' | 'warn' | string;

export interface TaskLinkDifferenceItem {
  source: string;
  target: string;
  status: StatusType;
  log_support_rate?: number;
  log_trace_count?: number;
  log_edge_type?: 'direct' | 'transitive' | 'unsupported' | string;
}

export interface SimulationResults {
  task_links?: TaskLinkDifferenceItem[];
}