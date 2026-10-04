import { CheckOutlined, CopyOutlined, FileTextOutlined } from '@ant-design/icons';
import { Empty, Progress, Statistic, Tag } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import FlowChart from '@/components/FlowGraph/FlowChart';
import type { WorkflowVersionRecord } from '@/api/schema';
import type { DagData } from '../Evaluation/types';
import { getReportScores } from './workflowModel';

const NORMAL_EDGE_STATES: Record<string, string> = {};

function normalizeXml(value?: string): string {
  if (!value) return '';
  return String(value)
    .trim()
    .replace(/^```(?:xml)?\s*/i, '')
    .replace(/\s*```$/i, '')
    .trim();
}

interface Props {
  dag: DagData;
  version?: WorkflowVersionRecord;
  report: any;
  versions: WorkflowVersionRecord[];
  selectedVersion: number;
  onSelectVersion: (versionNo: number) => void;
  bestVersion?: number;
}

export default function WorkflowWorkspace({
  dag,
  version,
  report,
  versions,
  selectedVersion,
  onSelectVersion,
  bestVersion,
}: Props) {
  const [copied, setCopied] = useState(false);
  // Run polling returns new JSON objects even when the DAG is unchanged. Keeping
  // the graph prop stable prevents G6 from destroying and rebuilding the canvas.
  const dagSignature = JSON.stringify(dag);
  const stableDag = useMemo(() => dag, [dagSignature]);

  const reportScores = getReportScores(report);
  const genericScore = version?.generic_score ?? reportScores.generic;
  const taskScore = version?.task_specific_score ?? reportScores.taskSpecific;
  const availableScores = [genericScore, taskScore].filter(
    (value): value is number => typeof value === 'number'
  );
  const compositeScore =
    version?.composite_score ??
    (availableScores.length
      ? availableScores.reduce((sum, value) => sum + value, 0) /
        availableScores.length
      : undefined);
  const isBest = version?.version_no === bestVersion;
  const orderedVersions = useMemo(
    () => [...versions].sort((left, right) => left.version_no - right.version_no),
    [versions]
  );
  const workflowXml = useMemo(() => normalizeXml(version?.xml), [version?.xml]);

  useEffect(() => {
    setCopied(false);
  }, [version?.version_no, workflowXml]);

  const copyXml = async () => {
    if (!workflowXml) return;
    try {
      await navigator.clipboard.writeText(workflowXml);
    } catch {
      const textarea = document.createElement('textarea');
      textarea.value = workflowXml;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <>
      <div className="workspace-grid">
      <section className="dag-panel">
        <div className="dag-panel-header">
          <div>
            <div className="section-eyebrow">WORKFLOW MODEL</div>
            <h2 className="section-title">Workflow DAG</h2>
          </div>
          <nav className="dag-version-switcher" aria-label="Workflow DAG versions">
            {orderedVersions.map((record) => {
              const active = record.version_no === selectedVersion;
              const best = record.version_no === bestVersion;
              const score =
                typeof record.composite_score === 'number'
                  ? `, score ${record.composite_score.toFixed(1)} out of 5`
                  : '';
              return (
                <button
                  type="button"
                  key={record.version_no}
                  className={[
                    'dag-version-button',
                    active ? 'is-active' : '',
                    best ? 'is-best' : '',
                  ].join(' ')}
                  aria-pressed={active}
                  aria-label={`View workflow version ${record.version_no}${best ? ', best version' : ''}${score}`}
                  onClick={() => onSelectVersion(record.version_no)}
                >
                  <span>v{record.version_no}</span>
                  {best && <small>BEST</small>}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="dag-legend">
          <span><i className="legend-dot is-normal" />Dependency</span>
        </div>

        <div className="dag-canvas">
          <FlowChart
            width="100%"
            height={520}
            taskData={stableDag}
            edgeStates={NORMAL_EDGE_STATES}
          />
        </div>

        <section className="dag-xml-panel" aria-label="Workflow XML">
          <div className="dag-xml-header">
            <div>
              <div className="dag-xml-title">
                <FileTextOutlined /> Workflow XML
                {version && <Tag>v{version.version_no}</Tag>}
              </div>
              <span>ADGA workflow definition for the selected DAG version.</span>
            </div>
            <button
              type="button"
              className={copied ? 'dag-xml-copy is-copied' : 'dag-xml-copy'}
              disabled={!workflowXml}
              onClick={() => void copyXml()}
            >
              {copied ? <CheckOutlined /> : <CopyOutlined />}
              {copied ? 'Copied' : 'Copy XML'}
            </button>
          </div>
          {workflowXml ? (
            <pre className="dag-xml-code"><code>{workflowXml}</code></pre>
          ) : (
            <div className="dag-xml-empty">
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="XML has not been generated for this version yet."
              />
            </div>
          )}
        </section>
      </section>

      <aside className="inspector-panel score-panel">
        <div className="inspector-header">
          <div>
            <div className="section-eyebrow">CURRENT WORKFLOW</div>
            <h2 className="section-title">Workflow score</h2>
          </div>
          {version && <Tag color={isBest ? 'blue' : 'default'}>v{version.version_no}</Tag>}
        </div>

        {typeof compositeScore === 'number' ? (
          <div className="score-panel-content">
            <div className="composite-score">
              <Statistic
                title="Composite score"
                value={compositeScore}
                precision={1}
                suffix="/ 5"
              />
              <Progress
                type="circle"
                size={86}
                percent={Math.round((compositeScore / 5) * 100)}
                format={() => compositeScore.toFixed(1)}
                strokeColor="#2563eb"
              />
            </div>

            <div className="score-metric-grid">
              <div className="metric-card">
                <Statistic
                  title="Generic score"
                  value={genericScore ?? 0}
                  precision={1}
                  suffix="/ 5"
                />
              </div>
              <div className="metric-card">
                <Statistic
                  title="Task-specific"
                  value={taskScore ?? 0}
                  precision={1}
                  suffix="/ 5"
                />
              </div>
            </div>

            <div className="score-status-row">
              <span>Evaluation status</span>
              <Tag
                color={
                  version?.status === 'accepted'
                    ? 'success'
                    : version?.status === 'evaluated'
                      ? 'warning'
                      : 'processing'
                }
              >
                {(version?.status || 'pending').split('_').join(' ').toUpperCase()}
              </Tag>
            </div>
          </div>
        ) : (
          <div className="score-panel-empty">
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="The Evaluation agent has not scored this DAG yet."
            />
          </div>
        )}
      </aside>
      </div>
    </>
  );
}
