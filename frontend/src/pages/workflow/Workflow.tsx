import {
  ArrowLeftOutlined,
  DatabaseOutlined,
  PlayCircleFilled,
  ReloadOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Collapse,
  Input,
  InputNumber,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd';
import { FC, useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import type { EventEmitter } from 'ahooks/lib/useEventEmitter';
import {
  getCollectionList,
  getWorkflowEvaluateDetail,
  getWorkflowInfoById,
  validateEdgesWithLog,
  validateWorkflowRunVersionLog,
} from '@/api/api';
import type { WorkflowVersionRecord } from '@/api/schema';
import AgentActivityPanel from './AgentActivityPanel';
import AgentProgress from './AgentProgress';
import WorkflowWorkspace from './WorkflowWorkspace';
import {
  buildIssues,
  parseDag,
} from './workflowModel';
import {
  ACTIVE_RUN_STATUSES,
  useWorkflowRun,
} from './useWorkflowRun';
import './workflow.css';

const { Paragraph, Text, Title } = Typography;

const getErrorMessage = (error: any) =>
  error?.response?.data?.detail ||
  error?.response?.data?.msg ||
  error?.message ||
  'The request failed. Please check the backend service and try again.';

const statusColors: Record<string, string> = {
  pending: 'processing',
  generating: 'processing',
  evaluating: 'cyan',
  repairing: 'purple',
  verifying: 'geekblue',
  awaiting_review: 'warning',
  completed: 'success',
  needs_review: 'warning',
  failed: 'error',
  stopped: 'default',
};

const terminalStatusCopy: Record<
  string,
  { title: string; description: string; type: 'error' | 'warning' }
> = {
  needs_review: {
    title: 'The best available version needs review',
    description: 'Review the current version, then continue optimization or accept it.',
    type: 'warning',
  },
  failed: {
    title: 'The workflow run failed',
    description: 'Retry from the latest checkpoint or start a new optimization run.',
    type: 'error',
  },
  stopped: {
    title: 'The workflow run was stopped',
    description: 'You can retry from the latest checkpoint when you are ready.',
    type: 'warning',
  },
};

function makeLegacyVersions(workflow: any, evaluation: any) {
  const versions: any[] = [];
  const initialDag = parseDag(workflow?.dag);
  if (initialDag) {
    versions.push({
      id: -1,
      run_id: 'legacy',
      workflow_id: Number(workflow.id),
      version_no: 1,
      dag: initialDag,
      xml: workflow.xml,
      simulation_results:
        evaluation?.conformance_results || evaluation?.sim_results,
      universal_rubric: evaluation?.universal_rubric || [],
      final_rubric: evaluation?.final_rubric || [],
      evaluation_report: evaluation?.report,
      issues: buildIssues(
        evaluation?.conformance_results || evaluation?.sim_results,
        evaluation?.report
      ),
      hard_constraints_passed: true,
      fingerprint: 'legacy-v1',
      status: evaluation?.report ? 'evaluated' : 'created',
      created_at: 0,
    });
  }
  const optimizedDag = parseDag(evaluation?.optimized_workflow);
  if (optimizedDag) {
    versions.push({
      ...versions[0],
      id: -2,
      version_no: 2,
      parent_version_no: 1,
      dag: optimizedDag,
      xml: evaluation?.xmlresult,
      fingerprint: 'legacy-v2',
      status: 'created',
    });
  }
  return versions as WorkflowVersionRecord[];
}

const Workflow: FC<{ refresh$: EventEmitter<void> }> = ({ refresh$ }) => {
  const { workflowId } = useParams();
  const navigate = useNavigate();
  const runManager = useWorkflowRun();

  const [description, setDescription] = useState('');
  const [workflow, setWorkflow] = useState<any>(null);
  const [legacyVersions, setLegacyVersions] = useState<WorkflowVersionRecord[]>(
    []
  );
  const [selectedVersion, setSelectedVersion] = useState(1);
  const versionSelectedByUser = useRef(false);
  const [knowledgeBase, setKnowledgeBase] = useState('Current tool knowledge base');
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);
  const [logValidating, setLogValidating] = useState(false);
  const [reviewSubmitting, setReviewSubmitting] = useState(false);

  const [maxIterations, setMaxIterations] = useState(3);
  const [acceptanceThreshold, setAcceptanceThreshold] = useState(4);
  const [autoRepair, setAutoRepair] = useState(true);

  const loadWorkspace = useCallback(
    async (id: string) => {
      versionSelectedByUser.current = false;
      setLoadingWorkspace(true);
      try {
        const [workflowResponse, evaluationResponse] = await Promise.all([
          getWorkflowInfoById(id),
          getWorkflowEvaluateDetail({ workflow_id: id }),
        ]);
        if (workflowResponse.code !== 200 || !workflowResponse.data) {
          throw new Error(workflowResponse.msg || 'Workflow not found.');
        }
        const workflowData = workflowResponse.data;
        setWorkflow(workflowData);
        setDescription((current) => workflowData.describe || current);

        const latest = await runManager.loadLatest(id);
        if (!latest) {
          const evaluationData = (evaluationResponse as any)?.data || null;
          const legacy = makeLegacyVersions(workflowData, evaluationData);
          setLegacyVersions(legacy);
          if (legacy.length) {
            setSelectedVersion(legacy[legacy.length - 1].version_no);
          }
        } else {
          setLegacyVersions([]);
          setMaxIterations(Math.min(10, latest.max_iterations || 3));
          setAcceptanceThreshold(latest.acceptance_threshold || 4);
          setAutoRepair(latest.auto_repair);
          setSelectedVersion(
            latest.final_version ||
              latest.current_version ||
              latest.versions?.[0]?.version_no ||
              1
          );
        }
      } catch (error) {
        message.error(getErrorMessage(error));
      } finally {
        setLoadingWorkspace(false);
      }
    },
    [runManager.loadLatest]
  );

  useEffect(() => {
    if (workflowId) void loadWorkspace(workflowId);
  }, [workflowId, loadWorkspace]);

  useEffect(() => {
    getCollectionList()
      .then((response) => {
        const selected = (response.data || []).find(
          (item: any) => item.is_selected
        );
        if (selected?.collection_name) {
          setKnowledgeBase(selected.collection_name);
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const current = runManager.run?.current_version;
    if (current && !versionSelectedByUser.current) setSelectedVersion(current);
  }, [runManager.run?.current_version]);

  useEffect(() => {
    const currentRun = runManager.run;
    if (
      currentRun?.final_version &&
      !ACTIVE_RUN_STATUSES.has(currentRun.status) &&
      !versionSelectedByUser.current
    ) {
      setSelectedVersion(currentRun.final_version);
    }
  }, [runManager.run?.final_version, runManager.run?.status]);

  useEffect(() => {
    if (!workflowId || !runManager.run?.versions?.length) return;
    const firstVersionReady = runManager.run.versions.some(
      (version) => version.version_no === 1
    );
    if (firstVersionReady && !workflow?.extracted_task) {
      getWorkflowInfoById(workflowId)
        .then((response) => {
          if (response.code === 200 && response.data) {
            setWorkflow(response.data);
            setDescription((current) => response.data.describe || current);
          }
        })
        .catch(() => undefined);
    }
  }, [
    workflowId,
    runManager.run?.versions?.length,
    workflow?.extracted_task,
  ]);

  useEffect(() => {
    if (!workflowId || runManager.run?.status !== 'generating') return;
    getWorkflowInfoById(workflowId)
      .then((response) => {
        if (response.code === 200 && response.data) {
          setWorkflow(response.data);
        }
      })
      .catch(() => undefined);
  }, [
    workflowId,
    runManager.run?.status,
    runManager.run?.active_step,
    runManager.run?.events?.length,
  ]);

  const handleStart = async () => {
    if (!description.trim()) {
      message.warning('Please describe the workflow you want to generate.');
      return;
    }
    try {
      setLegacyVersions([]);
      versionSelectedByUser.current = false;
      setSelectedVersion(1);
      const result = await runManager.start({
        workflowId,
        description: description.trim(),
        maxIterations,
        regenerationThreshold: 1,
        acceptanceThreshold,
        autoRepair,
      });
      setWorkflow((current: any) => ({
        ...(current || {}),
        id: result.workflowId,
        describe: description.trim(),
      }));
      if (!workflowId) {
        navigate(`/workflow/${result.workflowId}`, { replace: true });
      }
      refresh$.emit();
      message.success('Automatic workflow design and optimization started.');
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const handleStop = async () => {
    try {
      await runManager.stop();
      message.info('Stop requested. The current model call will finish safely.');
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const handleRetry = async () => {
    try {
      await runManager.retry();
      message.success('Workflow optimization resumed from its last checkpoint.');
    } catch (error) {
      message.error(getErrorMessage(error));
    }
  };

  const handleAccept = async (versionNo: number) => {
    const availableVersions = runManager.run
      ? runManager.run.versions || []
      : legacyVersions;
    if (
      !availableVersions.some(
        (version) => version.version_no === versionNo
      )
    ) {
      message.warning('There is no workflow version available to accept.');
      return false;
    }
    try {
      await runManager.accept(versionNo);
      message.success(`Workflow version v${versionNo} is now final.`);
      return true;
    } catch (error) {
      message.error(getErrorMessage(error));
      return false;
    }
  };

  const handleSelectVersion = useCallback((versionNo: number) => {
    versionSelectedByUser.current = true;
    setSelectedVersion(versionNo);
  }, []);

  const versionRecords = runManager.run
    ? runManager.run.versions || []
    : legacyVersions;
  const selectedRecord =
    versionRecords.find((version) => version.version_no === selectedVersion) ||
    versionRecords[versionRecords.length - 1];
  const initialRecord = versionRecords[0];
  const initialDag = parseDag(initialRecord?.dag);
  const selectedDag = parseDag(selectedRecord?.dag);

  const report = selectedRecord?.evaluation_report || null;
  const runStatus =
    runManager.run?.status || (versionRecords.length ? 'completed' : 'idle');
  const isActive = ACTIVE_RUN_STATUSES.has(runStatus);
  const isGenerating = ['pending', 'generating'].includes(runStatus);
  const terminalCopy =
    runStatus === 'needs_review' && versionRecords.length === 0
      ? {
          title: 'Workflow run was interrupted',
          description:
            'No workflow version was produced. Continue optimization to retry from the generation checkpoint.',
          type: 'warning' as const,
        }
      : terminalStatusCopy[runStatus];
  const latestEvent =
    runManager.run?.events?.[runManager.run.events.length - 1];
  const stageText =
    latestEvent?.message ||
    (runManager.run?.active_step
      ? runManager.run.active_step.split('_').join(' ')
      : '');

  const handleValidateLog = async (file: File, versionNo?: number) => {
    const targetRecord =
      versionRecords.find((version) => version.version_no === versionNo) ||
      selectedRecord;
    const targetSimulation = targetRecord?.simulation_results;
    if (!targetSimulation) return false;
    if (!file.name.endsWith('.xes') && !file.name.endsWith('.xes.gz')) {
      message.warning('Please select a .xes or .xes.gz execution log.');
      return false;
    }
    setLogValidating(true);
    try {
      if (runManager.run?.id && targetRecord) {
        const response = await validateWorkflowRunVersionLog(
          runManager.run.id,
          targetRecord.version_no,
          file
        );
        if (response.code !== 200 || !response.data) {
          throw new Error(response.msg || 'Log validation failed.');
        }
        runManager.setRun(response.data);
      } else if (workflowId) {
        const formData = new FormData();
        formData.append('workflow_id', workflowId);
        formData.append('sim_results', JSON.stringify(targetSimulation));
        formData.append('file', file);
        const response = await validateEdgesWithLog(formData);
        if (response.code !== 200) {
          throw new Error(response.msg || 'Log validation failed.');
        }
      }
      message.success('Execution-log validation completed.');
      return true;
    } catch (error) {
      message.error(getErrorMessage(error));
      return false;
    } finally {
      setLogValidating(false);
    }
  };

  const handleConfirmDependencies = async (links: any[]) => {
    const currentVersion = runManager.run?.current_version;
    if (!currentVersion) return false;
    setReviewSubmitting(true);
    try {
      await runManager.confirmDependencies(
        currentVersion,
        links.map((link) => ({
          source: link.source,
          target: link.target,
          status: link.status,
        }))
      );
      message.success('Dependency decisions confirmed. Evaluation resumed.');
      return true;
    } catch (error) {
      message.error(getErrorMessage(error));
      return false;
    } finally {
      setReviewSubmitting(false);
    }
  };

  return (
    <div className="workflow-page">
      <header className="workflow-page-header">
        <div>
          <div className="section-eyebrow">SCIENTIFIC WORKFLOW STUDIO</div>
          <Title level={1} className="!mb-1 !text-[34px] !leading-tight">
            Workflow Design
          </Title>
          <Text type="secondary">
            Generate, evaluate and iteratively repair a scientific workflow from one request.
          </Text>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {workflowId && <Tag color="blue">Workflow {workflowId}</Tag>}
          {runManager.run && (
            <Tag color={statusColors[runStatus] || 'default'}>
              {runStatus.split('_').join(' ').toUpperCase()}
            </Tag>
          )}
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => navigate('/workflow-manage')}
          >
            All workflows
          </Button>
        </div>
      </header>

      <Card className="workflow-command-card" bordered={false}>
        <div className="command-card-grid">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <PlayCircleFilled className="text-blue-600" />
              <Text strong>Describe the workflow you want to build</Text>
            </div>
            <Input.TextArea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              disabled={isActive}
              autoSize={{ minRows: 3, maxRows: 7 }}
              placeholder="For example: extract audio from a video, transcribe the speech, translate it into English, generate subtitles and merge them back into the video."
            />
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <Tag icon={<DatabaseOutlined />} color="geekblue">
                {knowledgeBase}
              </Tag>
              <label className="flex items-center gap-2 text-sm text-slate-500">
                <Switch
                  size="small"
                  checked={autoRepair}
                  onChange={setAutoRepair}
                  disabled={isActive}
                />
                Repair automatically until accepted
              </label>
            </div>
            <Collapse
              ghost
              className="run-settings-collapse"
              items={[
                {
                  key: 'settings',
                  label: (
                    <span className="flex items-center gap-2 text-sm text-slate-500">
                      <SettingOutlined /> Acceptance and iteration settings
                    </span>
                  ),
                  children: (
                    <>
                      <div className="run-settings-grid">
                        <label>
                          <span>Maximum versions</span>
                          <InputNumber
                            min={1}
                            max={10}
                            precision={0}
                            value={maxIterations}
                            onChange={(value) => {
                              if (value !== null) setMaxIterations(value);
                            }}
                            disabled={isActive}
                          />
                        </label>
                        <label>
                          <span>Composite acceptance score</span>
                          <InputNumber
                            min={1.1}
                            max={5}
                            step={0.1}
                            value={acceptanceThreshold}
                            onChange={(value) => {
                              if (value !== null) setAcceptanceThreshold(value);
                            }}
                            disabled={isActive}
                          />
                        </label>
                      </div>
                      <Text type="secondary" className="text-xs">
                        Composite score below 1 triggers regeneration; otherwise the
                        workflow is repaired until it reaches the acceptance score.
                      </Text>
                    </>
                  ),
                },
              ]}
            />
          </div>
          <Button
            type="primary"
            size="large"
            icon={versionRecords.length ? <ReloadOutlined /> : <PlayCircleFilled />}
            loading={runManager.loading || loadingWorkspace}
            disabled={isActive || !description.trim()}
            onClick={handleStart}
          >
            {versionRecords.length
              ? 'Start a new optimization run'
              : 'Generate and optimize'}
          </Button>
        </div>
      </Card>

      <AgentProgress
        events={runManager.run?.events || []}
        activeAgent={runManager.run?.active_agent}
        activeStep={runManager.run?.active_step}
        runStatus={runStatus}
        errorMessage={runManager.run?.error_message}
      />

      {runManager.pollingError && (
        <Alert
          className="mb-5"
          type="warning"
          showIcon
          message="Live status temporarily unavailable"
          description={`${runManager.pollingError} The page will keep trying automatically.`}
        />
      )}

        <AgentActivityPanel
          run={runManager.run}
          workflow={workflow}
          versions={versionRecords}
          activeVersion={
          versionRecords.find(
            (version) => version.version_no === runManager.run?.current_version
          ) || selectedRecord
        }
        onValidateLog={handleValidateLog}
        logValidating={logValidating}
        onConfirmDependencies={handleConfirmDependencies}
        reviewSubmitting={reviewSubmitting}
        runStatus={runStatus}
        selectedVersion={selectedRecord?.version_no || selectedVersion}
        onSelectVersion={handleSelectVersion}
        onStop={handleStop}
        onRetry={handleRetry}
        onAccept={handleAccept}
      />

      {isGenerating && !initialDag && (
        <Alert
          className="mb-5"
          type="info"
          showIcon
          message="Generation agent is working"
          description={stageText || 'Preparing the initial workflow model.'}
        />
      )}

      {terminalCopy && (
          <Alert
            className="mb-5"
            type={terminalCopy.type}
            showIcon
            message={terminalCopy.title}
            description={runManager.run?.error_message || terminalCopy.description}
          />
        )}

      {initialDag && selectedDag ? (
        <WorkflowWorkspace
          dag={selectedDag}
          version={selectedRecord}
          report={report}
          versions={versionRecords}
          selectedVersion={selectedRecord?.version_no || selectedVersion}
          onSelectVersion={handleSelectVersion}
          bestVersion={runManager.run?.best_version}
        />
      ) : (
        !isActive && (
          <div className="empty-workspace">
            <div className="empty-workspace-orbit">
              <PlayCircleFilled />
            </div>
            <Title level={3}>Your workflow versions will appear here</Title>
            <Paragraph type="secondary" className="max-w-xl text-center">
              Enter one natural-language request. The system will generate v1,
              evaluate it, apply repair plans and retain the best verified version.
            </Paragraph>
          </div>
        )
      )}
    </div>
  );
};

export default Workflow;
