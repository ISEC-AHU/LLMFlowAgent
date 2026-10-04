import type { DagData, TaskLink, TaskNode } from './types';

export function tryParseJson(value: any) {
  // Accept backend values as objects, JSON strings, or empty values.
  if (!value) return null;
  if (typeof value === 'object') return value;
  if (typeof value === 'string') {
    try {
      return JSON.parse(value);
    } catch {
      return null;
    }
  }
  return null;
}

export function prettyJson(value: any) {
  // Pretty-print values for textarea/pre elements when possible; otherwise preserve the source string.
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  return JSON.stringify(value, null, 2);
}

export function extractTaskInfo(rawTask: any): {
  parsedTask: any;
  userRequest: string;
  dagData: DagData | null;
  workflowId: string;
} {
  // Normalize uploaded or API-returned task JSON into the task, user request, DAG data, and workflow_id.
  const parsed = typeof rawTask === 'string' ? tryParseJson(rawTask) : rawTask;

  if (!parsed || typeof parsed !== 'object') {
    return {
      parsedTask: rawTask,
      userRequest: '',
      dagData: null,
      workflowId: '',
    };
  }

  const userRequest = parsed.user_request || '';
  const workflowId = parsed.id ? String(parsed.id) : '';

  const rawTaskNodes = Array.isArray(parsed.task_nodes) ? parsed.task_nodes : [];
  const rawTaskLinks = Array.isArray(parsed.task_links) ? parsed.task_links : [];

  // FlowChart requires stable id, label, and name fields. Fill only missing fields.
  const normalizedNodes: TaskNode[] = rawTaskNodes.map((node: any, index: number) => {
    const taskName = node.task || node.name || node.label || `Node-${index}`;
    return {
      id: taskName,
      label: taskName,
      name: taskName,
      task: taskName,
      arguments: node.arguments || [],
      ...node,
    };
  });

  const normalizedLinks: TaskLink[] = rawTaskLinks
    .filter((link: any) => link?.source && link?.target)
    .map((link: any) => ({
      source: link.source,
      target: link.target,
      ...link,
    }));

  const dagData =
    normalizedNodes.length > 0
      ? {
          task_nodes: normalizedNodes,
          task_links: normalizedLinks,
        }
      : null;

  return {
    parsedTask: parsed,
    userRequest,
    dagData,
    workflowId,
  };
}
