import {
  ApiOutlined,
  BarChartOutlined,
  CheckCircleFilled,
  CloudUploadOutlined,
  CodeOutlined,
  DownOutlined,
  FileTextOutlined,
  InboxOutlined,
  LoadingOutlined,
  RedoOutlined,
  SearchOutlined,
  SafetyCertificateOutlined,
  StopOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import {
  Button,
  Empty,
  Modal,
  Radio,
  Select,
  Space,
  Statistic,
  Tag,
  Timeline,
  Typography,
  Upload,
} from 'antd';
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import type {
  WorkflowRunEvent,
  WorkflowRunRecord,
  WorkflowVersionRecord,
} from '@/api/schema';

const { Text } = Typography;

export type ReviewLink = {
  source: string;
  target: string;
  status: 'pass' | 'warn';
  logStatus?: 'pass' | 'warn';
  [key: string]: any;
};

interface Props {
  run: WorkflowRunRecord | null;
  workflow: any;
  versions: WorkflowVersionRecord[];
  activeVersion?: WorkflowVersionRecord;
  onValidateLog: (file: File, versionNo?: number) => Promise<boolean>;
  logValidating: boolean;
  onConfirmDependencies: (links: ReviewLink[]) => Promise<boolean>;
  reviewSubmitting: boolean;
  runStatus: string;
  selectedVersion: number;
  onSelectVersion: (versionNo: number) => void;
  onStop: () => void;
  onRetry: () => void;
  onAccept: (versionNo: number) => Promise<boolean>;
}

function asArray(value: any): any[] {
  if (Array.isArray(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return value
      .split(/\r?\n/)
      .map((item) => item.replace(/^\s*(?:[-*]|\d+[.)])\s*/, '').trim())
      .filter(Boolean);
  }
}

function repairOperationRoute(operation: any): string {
  if (String(operation?.operation || '').toLowerCase() === 'insert_node_between') {
    const nodeName = operation?.node?.task || operation?.node?.name || operation?.node_name;
    return [
      ...(Array.isArray(operation?.predecessors) ? operation.predecessors : []),
      nodeName,
      ...(Array.isArray(operation?.successors) ? operation.successors : []),
    ]
      .filter(Boolean)
      .join(' → ');
  }
  return [operation?.source, operation?.target].filter(Boolean).join(' → ');
}

function taskItems(value: any): string[] {
  if (!value) return [];
  const array = asArray(value);
  if (array.length) {
    return array.map((item) =>
      typeof item === 'string'
        ? item
        : String(item.task || item.description || item.name || JSON.stringify(item))
    );
  }
  return String(value)
    .split(/\r?\n/)
    .map((item) => item.replace(/^\s*(?:[-*]|\d+[.)])\s*/, '').trim())
    .filter(Boolean);
}

function apiItems(value: any): Array<{ name: string; detail?: string }> {
  return asArray(value).flatMap((item: any) => {
    const doc = item?.doc || item;
    const content = doc?.page_content || doc?.content || doc;
    if (typeof content === 'string') {
      try {
        const parsed = JSON.parse(content);
        return [{
          name: String(parsed.name || parsed.id || parsed.api_name || 'Retrieved API'),
          detail: parsed.description || parsed.summary,
        }];
      } catch {
        return [{ name: content.split(/\r?\n/)[0].slice(0, 90) }];
      }
    }
    return [{
      name: String(content?.name || content?.id || content?.api_name || 'Retrieved API'),
      detail: content?.description || content?.summary,
    }];
  });
}

function eventColor(event: WorkflowRunEvent) {
  if (event.event_type.includes('failed')) return 'red';
  if (
    event.event_type.includes('interrupted') ||
    event.event_type.includes('timeout') ||
    event.event_type.includes('stopped')
  ) return 'orange';
  if (event.event_type.includes('review')) return 'orange';
  if (event.event_type.includes('completed')) return 'green';
  return 'blue';
}

function eventPayloadDetails(event: WorkflowRunEvent): string[] {
  const payload = event.payload;
  if (!payload || typeof payload !== 'object') return [];
  const details: string[] = [];
  if (payload.decision) {
    details.push(`Decision: ${String(payload.decision).split('_').join(' ')}`);
  }
  if (payload.target_agent) {
    details.push(`Target: ${String(payload.target_agent)} agent`);
  }
  if (payload.generation_attempt) {
    details.push(`Generation attempt: ${payload.generation_attempt}`);
  }
  if (typeof payload.passed === 'boolean') {
    details.push(`Structural gate: ${payload.passed ? 'passed' : 'failed'}`);
  }
  if (typeof payload.component_count === 'number') {
    details.push(`Connected components: ${payload.component_count}`);
  }
  if (Array.isArray(payload.reason) && payload.reason.length) {
    details.push(`Reason: ${payload.reason.join(', ')}`);
  }
  return details;
}

function AgentBadge({
  agent,
}: {
  agent: 'coordinator' | 'generation' | 'evaluation' | 'repair';
}) {
  const label = {
    coordinator: 'Coordinator Agent',
    generation: 'Generation agent',
    evaluation: 'Evaluation agent',
    repair: 'Repair agent',
  }[agent];
  return (
    <span className={`activity-agent-badge is-${agent}`}>
      {label}
    </span>
  );
}

function DependencyReviewTable({
  links,
  onChange,
}: {
  links: ReviewLink[];
  onChange: (index: number, status: 'pass' | 'warn') => void;
}) {
  return (
    <div className="dependency-table">
      {links.map((link, index) => (
        <div className="dependency-row" key={`${link.source}-${link.target}`}>
          <div className="dependency-name">
            <span>{link.source}</span><b>→</b><span>{link.target}</span>
          </div>
          <Select
            aria-label={`Final decision for ${link.source} to ${link.target}`}
            value={link.status}
            options={[
              { value: 'pass', label: 'PASS' },
              { value: 'warn', label: 'WARN' },
            ]}
            onChange={(status: 'pass' | 'warn') => onChange(index, status)}
          />
        </div>
      ))}
    </div>
  );
}

export default function AgentActivityPanel({
  run,
  workflow,
  versions,
  activeVersion,
  onValidateLog,
  logValidating,
  onConfirmDependencies,
  reviewSubmitting,
  runStatus,
  selectedVersion,
  onSelectVersion,
  onStop,
  onRetry,
  onAccept,
}: Props) {
  const orderedVersions = useMemo(
    () => [...versions].sort((left, right) => left.version_no - right.version_no),
    [versions]
  );
  const baselineVersion =
    orderedVersions.find((record) => record.version_no === 1) || activeVersion;
  const laterVersions = orderedVersions.filter((record) => record.version_no > 1);
  const tasks = useMemo(
    () => taskItems(workflow?.extracted_task),
    [workflow?.extracted_task]
  );
  const queries = useMemo(
    () => asArray(workflow?.rewrite_queries).map(String),
    [workflow?.rewrite_queries]
  );
  const apis = useMemo(() => apiItems(workflow?.api_list), [workflow?.api_list]);
  const simulationLinks = baselineVersion?.simulation_results?.task_links || [];
  const analysisSkipped = Boolean(
    baselineVersion?.simulation_results?.analysis_skipped
  );
  const [reviewLinks, setReviewLinks] = useState<ReviewLink[]>([]);
  const [collapsed, setCollapsed] = useState(false);
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [dependencyReviewModalOpen, setDependencyReviewModalOpen] = useState(false);
  const [finalVersionModalOpen, setFinalVersionModalOpen] = useState(false);
  const [acceptingFinalVersion, setAcceptingFinalVersion] = useState(false);
  const lastAutoOpenedReviewKey = useRef<string>();
  const lastAutoOpenedFinalVersionKey = useRef<string>();

  useEffect(() => {
    setReviewLinks(
      simulationLinks.map((link: any) => ({
        ...link,
        source: String(link.source || ''),
        target: String(link.target || ''),
        status: link.status === 'warn' ? 'warn' : 'pass',
        logStatus:
          (link.log_status || link.status) === 'warn' ? 'warn' : 'pass',
      }))
    );
  }, [baselineVersion?.version_no, baselineVersion?.simulation_results]);

  const awaitingReview = run?.status === 'awaiting_review';
  const agentEvents = useMemo(
    () =>
      (run?.events || []).filter((event) =>
        ['coordinator', 'generation', 'evaluation', 'repair'].includes(
          String(event.agent)
        )
      ),
    [run?.events]
  );
  const logAttached = Boolean(
    simulationLinks.length &&
      simulationLinks.every((link: any) => link.log_edge_type)
  );
  const warnCount = reviewLinks.filter((link) => link.status === 'warn').length;
  const logAnalysisLinks = simulationLinks.map((link: any) => ({
    source: String(link.source || ''),
    target: String(link.target || ''),
    status: (link.log_status || link.status) === 'warn' ? 'warn' : 'pass',
  }));
  const logWarnCount = logAnalysisLinks.filter(
    (link: any) => link.status === 'warn'
  ).length;
  const modelAnalysisLinks = simulationLinks.map((link: any) => ({
    source: String(link.source || ''),
    target: String(link.target || ''),
    status: link.model_status
      ? link.model_status === 'warn' ? 'warn' : 'pass'
      : link.log_edge_type
        ? 'unavailable'
        : link.status === 'warn' ? 'warn' : 'pass',
    matchCount: link.model_match_count,
    modelCount: link.model_count,
  }));
  const modelWarnCount = modelAnalysisLinks.filter(
    (link: any) => link.status === 'warn'
  ).length;
  const modelUnavailableCount = modelAnalysisLinks.filter(
    (link: any) => link.status === 'unavailable'
  ).length;

  useEffect(() => {
    if (awaitingReview && !logAttached) {
      setLogModalOpen(true);
    } else if (logAttached) {
      setLogModalOpen(false);
    }
  }, [awaitingReview, activeVersion?.version_no, logAttached]);

  const dependencyReviewEvent = [...(run?.events || [])]
    .reverse()
    .find((event) => event.step === 'request_dependency_review');
  const dependencyReviewReady = Boolean(
    awaitingReview &&
      run?.active_step === 'request_dependency_review' &&
      run?.current_version === baselineVersion?.version_no &&
      baselineVersion?.status === 'awaiting_review' &&
      reviewLinks.length &&
      logAttached
  );
  const dependencyReviewKey = dependencyReviewReady
    ? `${run?.id}:v${run?.current_version}:${dependencyReviewEvent?.id || 'review'}`
    : undefined;

  useEffect(() => {
    if (!dependencyReviewReady || !dependencyReviewKey) {
      if (!awaitingReview) setDependencyReviewModalOpen(false);
      return;
    }
    if (lastAutoOpenedReviewKey.current !== dependencyReviewKey) {
      lastAutoOpenedReviewKey.current = dependencyReviewKey;
      setDependencyReviewModalOpen(true);
    }
  }, [awaitingReview, dependencyReviewKey, dependencyReviewReady]);

  const updateReviewLink = (index: number, status: 'pass' | 'warn') => {
    setReviewLinks((current) =>
      current.map((item, itemIndex) =>
        itemIndex === index ? { ...item, status } : item
      )
    );
  };

  const submitDependencyReview = async () => {
    const confirmed = await onConfirmDependencies(reviewLinks);
    if (confirmed) setDependencyReviewModalOpen(false);
  };

  const finalVersionSelectionReady = Boolean(
    runStatus === 'needs_review' && orderedVersions.length
  );
  const finalVersionReviewEvent = [...(run?.events || [])]
    .reverse()
    .find(
      (event) =>
        event.event_type === 'coordinator_needs_review' ||
        event.step === 'needs_review'
    );
  const finalVersionSelectionKey = finalVersionSelectionReady
    ? `${run?.id}:${finalVersionReviewEvent?.id || 'needs-review'}:${orderedVersions
        .map((version) => version.version_no)
        .join('-')}`
    : undefined;

  useEffect(() => {
    if (!finalVersionSelectionReady || !finalVersionSelectionKey) {
      setFinalVersionModalOpen(false);
      return;
    }
    if (lastAutoOpenedFinalVersionKey.current !== finalVersionSelectionKey) {
      lastAutoOpenedFinalVersionKey.current = finalVersionSelectionKey;
      setFinalVersionModalOpen(true);
    }
  }, [finalVersionSelectionKey, finalVersionSelectionReady]);

  const submitFinalVersion = async () => {
    setAcceptingFinalVersion(true);
    try {
      const accepted = await onAccept(selectedVersion);
      if (accepted) setFinalVersionModalOpen(false);
    } finally {
      setAcceptingFinalVersion(false);
    }
  };

  const working = Boolean(
    run && !['completed', 'failed', 'stopped', 'needs_review'].includes(run.status)
  );
  const terminalStateMessage = run
    ? ({
        completed: 'Workflow run completed.',
        needs_review: versions.length
          ? 'Workflow run paused for review.'
          : 'Workflow run was interrupted before a version was generated.',
        failed: 'Workflow run failed.',
        stopped: 'Workflow run stopped.',
      } as Record<string, string>)[run.status]
    : undefined;
  const liveStateMessage = terminalStateMessage
    ? run?.error_message || terminalStateMessage
    : run?.events?.[run.events.length - 1]?.message ||
      'Waiting for a workflow request.';
  const hasArtifacts =
    agentEvents.length > 0 ||
    tasks.length > 0 ||
    queries.length > 0 ||
    apis.length > 0 ||
    Boolean(baselineVersion?.dag);
  const canAcceptSelectedVersion = versions.some(
    (version) => version.version_no === selectedVersion
  );
  const repairOperations = baselineVersion?.repair_plan?.operations || [];
  const evaluationReady = Boolean(baselineVersion?.evaluation_report);
  const evaluationReport = baselineVersion?.evaluation_report || {};
  const evaluationFindings = [
    ...((evaluationReport.task_specific_report?.dimension_scores || []).map(
      (item: any) => ({ ...item, rubricType: 'Task-specific' })
    )),
    ...((evaluationReport.generic_report?.dimension_scores || []).map(
      (item: any) => ({ ...item, rubricType: 'Universal' })
    )),
  ];
  const universalRubric = baselineVersion?.universal_rubric || [];
  const taskSpecificRubric = baselineVersion?.final_rubric || [];
  const rubricDimensions = [
    ...universalRubric.map((item: any) => ({ ...item, rubricType: 'Universal' })),
    ...taskSpecificRubric.map((item: any) => ({
      ...item,
      rubricType: 'Task-specific',
    })),
  ];
  return (
    <section className="agent-activity-panel">
      <button
        type="button"
        className="activity-header"
        aria-expanded={!collapsed}
        onClick={() => setCollapsed((current) => !current)}
      >
        <div>
          <div className="section-eyebrow">LIVE AGENT WORK</div>
          <h2 className="section-title">Work content</h2>
        </div>
        <div className="activity-live-state">
          {working ? <LoadingOutlined spin /> : <CheckCircleFilled />}
          <span>{liveStateMessage}</span>
          <DownOutlined className={collapsed ? '' : 'is-expanded'} />
        </div>
      </button>

      {!collapsed && (
        <div className="activity-sequence">
          {agentEvents.length > 0 && (
            <article className="activity-sequence-item activity-event-item">
              <div className="activity-sequence-marker is-log" />
              <div className="activity-block">
                <div className="activity-block-title">
                  Agent coordination history
                </div>
                <Timeline
                  className="activity-timeline is-complete"
                  items={agentEvents.map((event) => {
                    const details = eventPayloadDetails(event);
                    return {
                      color: eventColor(event),
                      children: (
                        <div className="activity-event-content">
                          <Text strong>{event.message}</Text>
                          <div className="activity-event-meta">
                            <AgentBadge
                              agent={
                                event.agent as
                                  | 'coordinator'
                                  | 'generation'
                                  | 'evaluation'
                                  | 'repair'
                              }
                            />
                            {event.step && (
                              <Tag>{event.step.split('_').join(' ')}</Tag>
                            )}
                            {event.version_no && <span>v{event.version_no}</span>}
                          </div>
                          {details.length > 0 && (
                            <div className="activity-event-details">
                              {details.map((detail) => (
                                <span key={detail}>{detail}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      ),
                    };
                  })}
                />
              </div>
            </article>
          )}

          {tasks.length > 0 && (
            <article className="activity-sequence-item">
              <div className="activity-sequence-marker">
                <CheckCircleFilled />
              </div>
              <div className="activity-block">
            <div className="activity-block-title">
              <CodeOutlined /> Task decomposition
              <AgentBadge agent="generation" />
              <Tag>{tasks.length}</Tag>
            </div>
                <ol className="artifact-list">
                  {tasks.map((task, index) => (
                    <li key={`${task}-${index}`}>{task}</li>
                  ))}
                </ol>
              </div>
            </article>
          )}

          {queries.length > 0 && (
            <article className="activity-sequence-item">
              <div className="activity-sequence-marker">
                <CheckCircleFilled />
              </div>
              <div className="activity-block">
                <div className="activity-block-title">
                  <SearchOutlined /> Retrieval queries
                  <AgentBadge agent="generation" />
                  <Tag>{queries.length}</Tag>
                </div>
                <div className="artifact-tags">
                  {queries.map((query, index) => (
                    <Tag color="blue" key={`${query}-${index}`}>{query}</Tag>
                  ))}
                </div>
              </div>
            </article>
          )}

          {apis.length > 0 && (
            <article className="activity-sequence-item">
              <div className="activity-sequence-marker">
                <CheckCircleFilled />
              </div>
              <div className="activity-block">
                <div className="activity-block-title">
                  <ApiOutlined /> Retrieved APIs
                  <AgentBadge agent="generation" />
                  <Tag>{apis.length}</Tag>
                </div>
                <div className="api-result-grid">
                  {apis.map((api, index) => (
                    <div className="api-result" key={`${api.name}-${index}`}>
                      <ApiOutlined />
                      <div>
                        <strong>{api.name}</strong>
                        {api.detail && <small>{api.detail}</small>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          )}

          {baselineVersion?.dag && (
            <article className="activity-sequence-item">
              <div className="activity-sequence-marker">
                <CheckCircleFilled />
              </div>
              <div className="activity-block activity-result-summary">
                <div className="activity-block-title">
                  <><CodeOutlined /> Initial DAG generated</>
                  <AgentBadge agent="generation" />
                  <Tag color="green">v{baselineVersion.version_no}</Tag>
                </div>
                <Text type="secondary">
                  {(baselineVersion.dag?.task_nodes || []).length} task nodes and{' '}
                  {(baselineVersion.dag?.task_links || []).length} dependencies generated.
                </Text>
              </div>
            </article>
          )}

          {modelAnalysisLinks.length > 0 && (
            <article className="activity-sequence-item">
              <div className="activity-sequence-marker">
                <CheckCircleFilled />
              </div>
              <div className="activity-block">
                <div className="activity-block-title">
                  <SafetyCertificateOutlined /> Multi-model dependency analysis
                  <AgentBadge agent="evaluation" />
                  <Tag color="cyan">v{baselineVersion?.version_no}</Tag>
                  <Tag
                    color={
                      modelUnavailableCount
                        ? 'default'
                        : modelWarnCount ? 'orange' : 'green'
                    }
                  >
                    {modelAnalysisLinks.length - modelWarnCount - modelUnavailableCount} PASS
                    {' / '}{modelWarnCount} WARN
                    {modelUnavailableCount ? ` / ${modelUnavailableCount} NOT RECORDED` : ''}
                  </Tag>
                </div>
                <div className="log-analysis-list">
                  {modelAnalysisLinks.map((link: any, index: number) => (
                    <div
                      className="log-analysis-row"
                      key={`model-${link.source}-${link.target}-${index}`}
                    >
                      <div className="log-analysis-edge">
                        <span>{link.source}</span>
                        <b>→</b>
                        <span>{link.target}</span>
                      </div>
                      {typeof link.matchCount === 'number' &&
                        typeof link.modelCount === 'number' && (
                          <span className="model-support-count">
                            {link.matchCount}/{link.modelCount} models
                          </span>
                        )}
                      <Tag
                        color={
                          link.status === 'pass'
                            ? 'success'
                            : link.status === 'warn'
                              ? 'warning'
                              : 'default'
                        }
                      >
                        {link.status === 'unavailable'
                          ? 'NOT RECORDED'
                          : link.status.toUpperCase()}
                      </Tag>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          )}

          {logAttached && (
            <article className="activity-sequence-item">
              <div className="activity-sequence-marker">
                <CheckCircleFilled />
              </div>
              <div className="activity-block">
                <div className="activity-block-title">
                  <FileTextOutlined /> Execution log analysis
                  <AgentBadge agent="evaluation" />
                  <Tag color="cyan">v{baselineVersion?.version_no}</Tag>
                  <Tag color={logWarnCount ? 'orange' : 'green'}>
                    {logAnalysisLinks.length - logWarnCount} PASS / {logWarnCount} WARN
                  </Tag>
                </div>
                <div className="log-analysis-list">
                  {logAnalysisLinks.map((link: any, index: number) => (
                    <div
                      className="log-analysis-row"
                      key={`${link.source}-${link.target}-${index}`}
                    >
                      <div className="log-analysis-edge">
                        <span>{link.source}</span>
                        <b>→</b>
                        <span>{link.target}</span>
                      </div>
                      <Tag color={link.status === 'pass' ? 'success' : 'warning'}>
                        {link.status.toUpperCase()}
                      </Tag>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          )}

          {(logAttached || analysisSkipped || evaluationReady) &&
            rubricDimensions.length > 0 && (
            <article className="activity-sequence-item">
              <div className="activity-sequence-marker">
                <CheckCircleFilled />
              </div>
              <div className="activity-block">
                <div className="activity-block-title">
                  <SafetyCertificateOutlined /> Evaluation rubric
                  <AgentBadge agent="evaluation" />
                  <Tag color="cyan">v{baselineVersion?.version_no}</Tag>
                  <Tag color="blue">{universalRubric.length} Universal</Tag>
                  <Tag color="purple">{taskSpecificRubric.length} Task-specific</Tag>
                  {analysisSkipped && <Tag>reused from v1</Tag>}
                </div>
                <div className="rubric-dimension-list">
                  {rubricDimensions.map((dimension: any, index: number) => (
                    <div
                      className="rubric-dimension-row"
                      key={`${dimension.rubricType}-${dimension.theme}-${index}`}
                    >
                      <div>
                        <strong>
                          {dimension.theme || dimension.name || `Dimension ${index + 1}`}
                        </strong>
                        {dimension.description && <small>{dimension.description}</small>}
                      </div>
                      <div className="rubric-dimension-meta">
                        <Tag
                          color={
                            dimension.rubricType === 'Universal' ? 'blue' : 'purple'
                          }
                        >
                          {dimension.rubricType}
                        </Tag>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          )}

          {evaluationReady && (
            <article className="activity-sequence-item">
              <div className="activity-sequence-marker">
                <CheckCircleFilled />
              </div>
              <div className="activity-block">
                <div className="activity-block-title">
                  <BarChartOutlined /> Evaluation result
                  <AgentBadge agent="evaluation" />
                  <Tag color="cyan">v{baselineVersion?.version_no}</Tag>
                  <Tag color="geekblue">DAG Evidence Tool</Tag>
                </div>
                <div className="activity-score-summary">
                  <Statistic
                    title="Composite"
                    value={baselineVersion?.composite_score ?? 0}
                    precision={1}
                    suffix="/ 5"
                  />
                  <Statistic
                    title="Generic"
                    value={baselineVersion?.generic_score ?? 0}
                    precision={1}
                    suffix="/ 5"
                  />
                  <Statistic
                    title="Task-specific"
                    value={baselineVersion?.task_specific_score ?? 0}
                    precision={1}
                    suffix="/ 5"
                  />
                  <div className="activity-issue-count">
                    <strong>{(baselineVersion?.issues || []).length}</strong>
                    <span>issues found</span>
                  </div>
                </div>
                {evaluationFindings.length > 0 && (
                  <div className="evaluation-finding-list">
                    {evaluationFindings.map((finding: any, index: number) => (
                      <div
                        className="evaluation-finding-row"
                        key={`${finding.rubricType}-${finding.dimension_name}-${index}`}
                      >
                        <div className="evaluation-finding-heading">
                          <strong>{finding.dimension_name || `Finding ${index + 1}`}</strong>
                          <div>
                            <Tag color={finding.rubricType === 'Task-specific' ? 'purple' : 'blue'}>
                              {finding.rubricType}
                            </Tag>
                            <Tag color={Number(finding.score) < 3.5 ? 'error' : 'success'}>
                              {Number(finding.score || 0).toFixed(1)} / 5
                            </Tag>
                          </div>
                        </div>
                        <p>{finding.reasoning || 'No detailed evaluation explanation was returned.'}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </article>
          )}

          {repairOperations.length > 0 && (
            <article className="activity-sequence-item">
              <div className="activity-sequence-marker">
                <CheckCircleFilled />
              </div>
              <div className="activity-block">
                <div className="activity-block-title">
                  <FileTextOutlined /> Repair plan
                  <AgentBadge agent="evaluation" />
                  <Tag color="cyan">v{baselineVersion?.version_no}</Tag>
                  <Tag color="orange">{repairOperations.length} operations</Tag>
                </div>
                <div className="repair-operation-list">
                  {repairOperations.slice(0, 8).map((operation: any, index: number) => (
                    <div className="repair-operation-row" key={`${operation.issue_id}-${index}`}>
                      <span>{index + 1}</span>
                      <div>
                        <strong>
                          {String(operation.operation || 'review').split('_').join(' ')}
                        </strong>
                        {repairOperationRoute(operation) && (
                          <small>{repairOperationRoute(operation)}</small>
                        )}
                        {operation.reason && <p>{operation.reason}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </article>
          )}

          {laterVersions.map((record) => {
            const summary = record.repair_summary || {};
            const revisionLog = summary.revision_log || {};
            const revisionOperations = Array.isArray(revisionLog.operations)
              ? revisionLog.operations
              : [];
            const producer =
              summary.producer === 'generation' ? 'generation' : 'repair';
            const report = record.evaluation_report || {};
            const findings = [
              ...((report.task_specific_report?.dimension_scores || []).map(
                (item: any) => ({ ...item, rubricType: 'Task-specific' })
              )),
              ...((report.generic_report?.dimension_scores || []).map(
                (item: any) => ({ ...item, rubricType: 'Universal' })
              )),
            ];
            const operations = record.repair_plan?.operations || [];
            return (
              <Fragment key={record.version_no}>
                <article className="activity-sequence-item">
                  <div className="activity-sequence-marker">
                    <CheckCircleFilled />
                  </div>
                  <div className="activity-block activity-result-summary">
                    <div className="activity-block-title">
                      <ToolOutlined />{' '}
                      {producer === 'generation'
                        ? 'Regenerated DAG'
                        : 'DAG Modification Tool'}
                      <AgentBadge agent={producer} />
                      <Tag color="purple">v{record.version_no}</Tag>
                    </div>
                    <Text type="secondary">
                      {(record.dag?.task_nodes || []).length} task nodes and{' '}
                      {(record.dag?.task_links || []).length} dependencies generated.
                    </Text>
                    <div className="repair-result-summary">
                      {(summary.added_nodes || []).length > 0 && (
                        <span>+{summary.added_nodes.length} nodes</span>
                      )}
                      <span>+{(summary.added_edges || []).length} edges</span>
                      <span>−{(summary.removed_edges || []).length} edges</span>
                      <span>{summary.unchanged_edge_count || 0} unchanged</span>
                    </div>
                  </div>
                </article>

                {producer === 'repair' && revisionOperations.length > 0 && (
                  <article className="activity-sequence-item">
                    <div className="activity-sequence-marker">
                      <CheckCircleFilled />
                    </div>
                    <div className="activity-block">
                      <div className="activity-block-title">
                        <FileTextOutlined /> Revision log
                        <AgentBadge agent="repair" />
                        <Tag color="purple">v{record.version_no}</Tag>
                        <Tag color="blue">
                          {revisionOperations.length} operations
                        </Tag>
                      </div>
                      <div className="repair-operation-list">
                        {revisionOperations.map((operation: any, index: number) => (
                          <div
                            className="repair-operation-row"
                            key={`${operation.operation}-${operation.source}-${operation.target}-${index}`}
                          >
                            <span>{index + 1}</span>
                            <div>
                              <Tag
                                style={{ float: 'right', marginInlineEnd: 0 }}
                                color={
                                  operation.status === 'applied'
                                    ? 'green'
                                    : operation.status === 'already_satisfied'
                                      ? 'blue'
                                      : 'red'
                                }
                              >
                                {String(operation.status || 'unknown')
                                  .split('_')
                                  .join(' ')}
                              </Tag>
                              <strong>
                                {String(operation.operation || 'review')
                                  .split('_')
                                  .join(' ')}
                              </strong>
                              {repairOperationRoute(operation) && (
                                <small>{repairOperationRoute(operation)}</small>
                              )}
                              {operation.reason && <p>{operation.reason}</p>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </article>
                )}

                {record.evaluation_report && (
                  <article className="activity-sequence-item">
                    <div className="activity-sequence-marker">
                      <CheckCircleFilled />
                    </div>
                    <div className="activity-block">
                      <div className="activity-block-title">
                        <BarChartOutlined /> Evaluation result
                        <AgentBadge agent="evaluation" />
                        <Tag color="cyan">v{record.version_no}</Tag>
                        <Tag color="geekblue">DAG Evidence Tool</Tag>
                      </div>
                      <div className="activity-score-summary">
                        <Statistic title="Composite" value={record.composite_score ?? 0} precision={1} suffix="/ 5" />
                        <Statistic title="Generic" value={record.generic_score ?? 0} precision={1} suffix="/ 5" />
                        <Statistic title="Task-specific" value={record.task_specific_score ?? 0} precision={1} suffix="/ 5" />
                        <div className="activity-issue-count">
                          <strong>{(record.issues || []).length}</strong>
                          <span>issues found</span>
                        </div>
                      </div>
                      {findings.length > 0 && (
                        <div className="evaluation-finding-list">
                          {findings.map((finding: any, index: number) => (
                            <div
                              className="evaluation-finding-row"
                              key={`${record.version_no}-${finding.rubricType}-${finding.dimension_name}-${index}`}
                            >
                              <div className="evaluation-finding-heading">
                                <strong>{finding.dimension_name || `Finding ${index + 1}`}</strong>
                                <div>
                                  <Tag color={finding.rubricType === 'Task-specific' ? 'purple' : 'blue'}>
                                    {finding.rubricType}
                                  </Tag>
                                  <Tag color={Number(finding.score) < 3.5 ? 'error' : 'success'}>
                                    {Number(finding.score || 0).toFixed(1)} / 5
                                  </Tag>
                                </div>
                              </div>
                              <p>{finding.reasoning || 'No detailed evaluation explanation was returned.'}</p>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </article>
                )}

                {operations.length > 0 && (
                  <article className="activity-sequence-item">
                    <div className="activity-sequence-marker">
                      <CheckCircleFilled />
                    </div>
                    <div className="activity-block">
                      <div className="activity-block-title">
                        <FileTextOutlined /> Repair plan
                        <AgentBadge agent="evaluation" />
                        <Tag color="cyan">v{record.version_no}</Tag>
                        <Tag color="orange">{operations.length} operations</Tag>
                      </div>
                      <div className="repair-operation-list">
                        {operations.slice(0, 8).map((operation: any, index: number) => (
                          <div
                            className="repair-operation-row"
                            key={`${record.version_no}-${operation.issue_id}-${index}`}
                          >
                            <span>{index + 1}</span>
                            <div>
                              <strong>{String(operation.operation || 'review').split('_').join(' ')}</strong>
                              {repairOperationRoute(operation) && (
                                <small>{repairOperationRoute(operation)}</small>
                              )}
                              {operation.reason && <p>{operation.reason}</p>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </article>
                )}
              </Fragment>
            );
          })}

          {awaitingReview && (
            <article className="activity-sequence-item is-current">
              <div className="activity-sequence-marker">
                <LoadingOutlined spin />
              </div>
              <div className="activity-block dependency-review">
                <div className="dependency-review-heading">
                  <div>
                    <div className="activity-block-title">
                      <SafetyCertificateOutlined /> Dependency review
                      <AgentBadge agent="evaluation" />
                    </div>
                    <Text type="secondary">
                      {logAttached
                        ? 'The original XES log has been applied. Review and confirm every dependency.'
                        : 'Select an XES execution log, then confirm every dependency.'}
                    </Text>
                  </div>
                  <Tag color={warnCount ? 'orange' : 'green'}>
                    {logAttached ? 'Log: ' : ''}
                    {reviewLinks.length - warnCount} PASS / {warnCount} WARN
                  </Tag>
                </div>

                <DependencyReviewTable
                  links={reviewLinks}
                  onChange={updateReviewLink}
                />

                <div className="dependency-actions">
                  {logAttached ? (
                    <Tag color="success">Original XES log applied</Tag>
                  ) : (
                    <Button
                      icon={<CloudUploadOutlined />}
                      loading={logValidating}
                      onClick={() => setLogModalOpen(true)}
                    >
                      Select XES log
                    </Button>
                  )}
                  <Button
                    type="primary"
                    disabled={!reviewLinks.length || !logAttached}
                    onClick={() => setDependencyReviewModalOpen(true)}
                  >
                    Open dependency review
                  </Button>
                </div>
                {!logAttached && (
                  <div className="dependency-log-hint">
                    An XES log is required before evaluation can continue.
                  </div>
                )}
              </div>
            </article>
          )}

          {!hasArtifacts && !awaitingReview && (
            <div className="activity-sequence-empty">
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  working
                    ? 'The first tool result will appear here when it is ready.'
                    : 'Agent work results will appear here.'
                }
              />
            </div>
          )}

          <div className="activity-run-controls">
            {[
              'pending',
              'generating',
              'evaluating',
              'repairing',
              'verifying',
              'awaiting_review',
            ].includes(runStatus) ? (
              <Button danger icon={<StopOutlined />} onClick={onStop}>
                Stop optimization
              </Button>
            ) : runStatus === 'needs_review' ? (
              canAcceptSelectedVersion ? (
                <Space.Compact>
                  <Button icon={<RedoOutlined />} onClick={onRetry}>
                    Continue optimization
                  </Button>
                  <Button
                    type="primary"
                    onClick={() => setFinalVersionModalOpen(true)}
                  >
                    Choose final version
                  </Button>
                </Space.Compact>
              ) : (
                <Button type="primary" icon={<RedoOutlined />} onClick={onRetry}>
                  Continue optimization
                </Button>
              )
            ) : ['failed', 'stopped'].includes(runStatus) ? (
              <Button type="primary" icon={<RedoOutlined />} onClick={onRetry}>
                Retry from checkpoint
              </Button>
            ) : runStatus === 'completed' ? (
              <Tag color="success">Workflow run completed</Tag>
            ) : null}
          </div>
        </div>
      )}

      <Modal
        title="Coordinator Agent requests an XES execution log"
        open={logModalOpen}
        footer={null}
        destroyOnClose
        onCancel={() => !logValidating && setLogModalOpen(false)}
      >
        <Text type="secondary">
          Choose a .xes or .xes.gz event log. Coordinator Agent will pass it to
          Evaluation Agent to validate the proposed workflow dependencies.
        </Text>
        <Upload.Dragger
          className="log-upload-dragger"
          accept=".xes,.xes.gz"
          maxCount={1}
          showUploadList={false}
          disabled={logValidating}
          beforeUpload={(file) => {
            void onValidateLog(file, activeVersion?.version_no).then(
              (validated) => {
                if (validated) setLogModalOpen(false);
              }
            );
            return false;
          }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">Click or drag an XES file here</p>
          <p className="ant-upload-hint">Only .xes and .xes.gz files are accepted.</p>
        </Upload.Dragger>
      </Modal>

      <Modal
        className="dependency-review-modal"
        title="Dependency review required"
        open={dependencyReviewModalOpen}
        width={820}
        maskClosable={false}
        closable={!reviewSubmitting}
        keyboard={!reviewSubmitting}
        onCancel={() => !reviewSubmitting && setDependencyReviewModalOpen(false)}
        footer={[
          <Button
            key="later"
            disabled={reviewSubmitting}
            onClick={() => setDependencyReviewModalOpen(false)}
          >
            Review later
          </Button>,
          <Button
            key="confirm"
            type="primary"
            loading={reviewSubmitting}
            disabled={!dependencyReviewReady}
            onClick={() => void submitDependencyReview()}
          >
            Confirm and continue evaluation
          </Button>,
        ]}
      >
        <div className="dependency-review-modal-copy">
          <Text>
            The Coordinator Agent has paused the workflow. Review the
            log-validated dependency decisions before evaluation continues.
          </Text>
          <div className="dependency-review-modal-summary">
            <Tag color="success">{reviewLinks.length - warnCount} PASS</Tag>
            <Tag color={warnCount ? 'orange' : 'default'}>{warnCount} WARN</Tag>
          </div>
        </div>
        <DependencyReviewTable
          links={reviewLinks}
          onChange={updateReviewLink}
        />
        <Text type="secondary">
          PASS keeps a dependency as supported; WARN marks it as uncertain for
          the task-specific evaluation rubric.
        </Text>
      </Modal>

      <Modal
        className="final-version-modal"
        title="Select final workflow version"
        open={finalVersionModalOpen}
        width={760}
        maskClosable={false}
        closable={!acceptingFinalVersion}
        keyboard={!acceptingFinalVersion}
        onCancel={() =>
          !acceptingFinalVersion && setFinalVersionModalOpen(false)
        }
        footer={[
          <Button
            key="later"
            disabled={acceptingFinalVersion}
            onClick={() => setFinalVersionModalOpen(false)}
          >
            Review later
          </Button>,
          <Button
            key="accept"
            type="primary"
            loading={acceptingFinalVersion}
            disabled={!canAcceptSelectedVersion}
            onClick={() => void submitFinalVersion()}
          >
            Accept selected version
          </Button>,
        ]}
      >
        <div className="final-version-modal-copy">
          <Text>
            The Coordinator Agent has paused the workflow. Compare the
            available results and select the version you want to keep.
          </Text>
          {run?.best_version && (
            <Tag color="blue">Recommended: v{run.best_version}</Tag>
          )}
        </div>

        <Radio.Group
          className="final-version-list"
          value={selectedVersion}
          onChange={(event) => onSelectVersion(Number(event.target.value))}
        >
          {orderedVersions.map((version) => {
            const isBest = version.version_no === run?.best_version;
            const nodeCount = version.dag?.task_nodes?.length || 0;
            const edgeCount = version.dag?.task_links?.length || 0;
            const formatScore = (score?: number) =>
              typeof score === 'number' ? score.toFixed(1) : '—';
            return (
              <Radio
                className={[
                  'final-version-option',
                  version.version_no === selectedVersion ? 'is-selected' : '',
                ].join(' ')}
                value={version.version_no}
                key={version.version_no}
              >
                <div className="final-version-option-content">
                  <div className="final-version-option-heading">
                    <strong>Version v{version.version_no}</strong>
                    {isBest && <Tag color="blue">BEST</Tag>}
                  </div>
                  <div className="final-version-score-grid">
                    <span>
                      <small>Composite</small>
                      <b>{formatScore(version.composite_score)}</b>
                    </span>
                    <span>
                      <small>Generic</small>
                      <b>{formatScore(version.generic_score)}</b>
                    </span>
                    <span>
                      <small>Task-specific</small>
                      <b>{formatScore(version.task_specific_score)}</b>
                    </span>
                    <span>
                      <small>Structure</small>
                      <b>{nodeCount} nodes / {edgeCount} edges</b>
                    </span>
                  </div>
                </div>
              </Radio>
            );
          })}
        </Radio.Group>

        <Text type="secondary">
          Selecting a version also switches the Workflow Model workspace to
          the same DAG.
        </Text>
      </Modal>
    </section>
  );
}
