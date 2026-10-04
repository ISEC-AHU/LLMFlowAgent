import type { DagData, TaskLink } from '../Evaluation/types';

export type AgentName = 'coordinator' | 'generation' | 'evaluation' | 'repair';
export type AgentStatus = 'waiting' | 'running' | 'completed' | 'failed';
export type RunStatus =
  | 'idle'
  | 'generating'
  | 'evaluating'
  | 'repairing'
  | 'completed'
  | 'failed';

export interface AgentStep {
  key: string;
  label: string;
  status: AgentStatus;
  summary?: string;
}

export interface WorkflowIssue {
  id: string;
  category: 'discrepancy' | 'rubric' | 'log';
  severity: 'high' | 'medium' | 'low';
  title: string;
  description: string;
  source?: string;
  target?: string;
  evidence: string[];
  status?: 'open' | 'unresolved' | 'verified' | string;
  foundInVersion?: number;
  resolvedInVersion?: number;
}

export interface DagDiff {
  addedEdges: TaskLink[];
  removedEdges: TaskLink[];
  unchangedEdges: TaskLink[];
  addedNodes: string[];
  removedNodes: string[];
}

const stripCodeFence = (value: string) =>
  value
    .trim()
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/i, '')
    .trim();

export function parseApiList(value: unknown): any[] {
  if (Array.isArray(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return [];
  try {
    const parsed = JSON.parse(stripCodeFence(value));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function parseDag(value: unknown): DagData | null {
  if (!value) return null;

  let parsed: any = value;
  if (typeof value === 'string') {
    try {
      parsed = JSON.parse(stripCodeFence(value));
    } catch {
      return null;
    }
  }

  if (
    !parsed ||
    !Array.isArray(parsed.task_nodes) ||
    !Array.isArray(parsed.task_links)
  ) {
    return null;
  }

  return {
    ...parsed,
    task_nodes: parsed.task_nodes,
    task_links: parsed.task_links.filter(
      (link: any) => link?.source && link?.target
    ),
  };
}

export function makeTask(workflow: any, dag: DagData | null) {
  return {
    id: String(workflow?.id ?? ''),
    user_request: workflow?.describe || '',
    extracted_task: workflow?.extracted_task || '',
    task_steps: String(workflow?.extracted_task || '')
      .split('\n')
      .map((item) => item.trim())
      .filter(Boolean),
    task_nodes: dag?.task_nodes || [],
    task_links: dag?.task_links || [],
    api_list: parseApiList(workflow?.api_list),
  };
}

export function edgeKey(link: Pick<TaskLink, 'source' | 'target'>) {
  return `${String(link.source).trim()}→${String(link.target).trim()}`;
}

export function diffDags(
  original: DagData | null,
  revised: DagData | null
): DagDiff {
  const originalEdges = new Map(
    (original?.task_links || []).map((link) => [edgeKey(link), link])
  );
  const revisedEdges = new Map(
    (revised?.task_links || []).map((link) => [edgeKey(link), link])
  );

  const originalNodes = new Set(
    (original?.task_nodes || []).map((node) =>
      String(node.task || node.name || node.label || node.id || '')
    )
  );
  const revisedNodes = new Set(
    (revised?.task_nodes || []).map((node) =>
      String(node.task || node.name || node.label || node.id || '')
    )
  );

  return {
    addedEdges: [...revisedEdges.entries()]
      .filter(([key]) => !originalEdges.has(key))
      .map(([, link]) => link),
    removedEdges: [...originalEdges.entries()]
      .filter(([key]) => !revisedEdges.has(key))
      .map(([, link]) => link),
    unchangedEdges: [...revisedEdges.entries()]
      .filter(([key]) => originalEdges.has(key))
      .map(([, link]) => link),
    addedNodes: [...revisedNodes].filter((name) => !originalNodes.has(name)),
    removedNodes: [...originalNodes].filter((name) => !revisedNodes.has(name)),
  };
}

function scoreIssues(report: any): WorkflowIssue[] {
  const reports = [
    ['generic', report?.generic_report],
    ['task-specific', report?.task_specific_report],
  ] as const;

  return reports.flatMap(([kind, item]) =>
    (item?.dimension_scores || [])
      .filter((dimension: any) => Number(dimension.score) < 3.5)
      .map((dimension: any, index: number) => ({
        id: `rubric-${kind}-${index}`,
        category: 'rubric' as const,
        severity:
          Number(dimension.score) < 2.5
            ? ('high' as const)
            : ('medium' as const),
        title: dimension.dimension_name || 'Low-scoring evaluation dimension',
        description:
          dimension.reasoning ||
          `The ${kind} evaluation score is below the expected level.`,
        evidence: [
          `${kind === 'generic' ? 'Generic' : 'Task-specific'} score: ${Number(
            dimension.score || 0
          ).toFixed(1)} / 5`,
        ],
      }))
  );
}

export function buildIssues(simulation: any, report: any): WorkflowIssue[] {
  const edgeIssues: WorkflowIssue[] = (simulation?.task_links || [])
    .filter((link: any) => link.status === 'warn')
    .map((link: any, index: number) => {
      const logRate =
        typeof link.log_support_rate === 'number'
          ? `${Math.round(link.log_support_rate * 100)}%`
          : null;
      const logUnsupported =
        link.log_edge_type === 'unsupported' ||
        (typeof link.log_support_rate === 'number' &&
          link.log_support_rate < 0.8);

      return {
        id: `edge-${index}-${edgeKey(link)}`,
        category: logUnsupported ? 'log' : 'discrepancy',
        severity: logUnsupported ? 'high' : 'medium',
        title: `${link.source} → ${link.target}`,
        description: logUnsupported
          ? 'The execution log does not provide enough support for this dependency.'
          : 'The independent workflow models disagree about this dependency.',
        source: link.source,
        target: link.target,
        evidence: [
          logRate
            ? `Execution-log support: ${logRate}`
            : 'Marked as WARN by multi-model dependency comparison.',
          link.log_edge_type
            ? `Log relation: ${link.log_edge_type}`
            : 'This edge should be reviewed before repair.',
        ],
      };
    });

  return [...edgeIssues, ...scoreIssues(report)];
}

export function getReportScores(report: any) {
  return {
    generic:
      typeof report?.generic_report?.normalized_score === 'number'
        ? report.generic_report.normalized_score
        : null,
    taskSpecific:
      typeof report?.task_specific_report?.normalized_score === 'number'
        ? report.task_specific_report.normalized_score
        : null,
  };
}
