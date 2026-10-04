import { Button, Card, Divider, message, Spin, Typography } from 'antd';
import { useEffect, useMemo, useState } from 'react';
import { unwrapApiResponse } from '@/utils/apiHelper';
import type { StatusType, DagData, SimulationResults } from '../Evaluation/types';
import {
  generateFinalRubric,
  generateReport,
  generateSimulationResults,
  generateUniversalRubric,
  getWorkflowEvaluateDetail,
  validateEdgesWithLog,
  workflowRegeneration,
  generateXmlFromRevisedWorkflow,
} from '@/api/api';

import RubricDimensionList from '../Evaluation/components/RubricDimensionList';
import SimulationResultsCard from '../Evaluation/components/SimulationResultsCard';
import ReportCard from '../Evaluation/components/ReportCard';
import WorkflowRegenerationCard from '../Evaluation/components/WorkflowRegenerationCard';
import { parseApiList } from './workflowModel';

const { Text } = Typography;

interface EvaluationSectionProps {
  workflowId: string;
  workflowInfo: any;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export default function EvaluationSection({ workflowId, workflowInfo }: EvaluationSectionProps) {

  // Parse DAG data first because taskInput and currentTask depend on it.
  const dagData = useMemo<DagData | null>(() => {
    if (!workflowInfo?.data?.dag) {
      console.log('[EvaluationSection] dagData: workflowInfo.data.dag is empty');
      return null;
    }
    try {
      let dagStr = workflowInfo.data.dag;
      console.log('[EvaluationSection] dagData: raw dag type =', typeof dagStr, ', value preview =', String(dagStr).substring(0, 200));
      // Use dag directly when it is already an object.
      if (typeof dagStr === 'object' && dagStr !== null) {
        if (dagStr.task_nodes && dagStr.task_links) {
          console.log('[EvaluationSection] dagData: dag is object with task_nodes and task_links');
          return dagStr as DagData;
        }
        console.log('[EvaluationSection] dagData: dag is object but missing task_nodes/task_links');
        return null;
      }
      dagStr = String(dagStr).trim();
      // Strip surrounding ```json ... ``` or ``` ... ``` Markdown fences.
      if (dagStr.startsWith('```')) {
        dagStr = dagStr.replace(/^```(?:json)?\s*/i, '');
        dagStr = dagStr.replace(/\s*```$/, '');
        dagStr = dagStr.trim();
        console.log('[EvaluationSection] dagData: stripped markdown wrapper, preview =', dagStr.substring(0, 200));
      }
      const parsed = JSON.parse(dagStr);
      if (parsed.task_nodes && parsed.task_links) {
        console.log('[EvaluationSection] dagData: parsed successfully, task_nodes count =', parsed.task_nodes.length);
        return parsed;
      }
      console.log('[EvaluationSection] dagData: parsed but missing task_nodes/task_links, keys =', Object.keys(parsed));
    } catch (e) {
      console.log('[EvaluationSection] dagData: parse error =', e);
    }
    return null;
  }, [workflowInfo]);

  // Build fallback task data as a string from workflowInfo.
  const initialTaskInput = useMemo(() => {
    if (!workflowInfo?.data) return '';
    const data = workflowInfo.data;
    // Extract task_nodes and task_links from dagData.
    const nodes = dagData?.task_nodes ?? [];
    const links = dagData?.task_links ?? [];
    // Build a task object compatible with WorkflowEvaluate.
    const taskObj = {
      id: data.id,
      user_request: data.describe || '',
      task_nodes: nodes,
      task_links: links,
      api_list: parseApiList(data.api_list),
    };
    return JSON.stringify(taskObj, null, 2);
  }, [workflowInfo, dagData]);

  const [taskInput, setTaskInput] = useState(initialTaskInput);

  // Keep taskInput synchronized with workflowInfo.
  useEffect(() => {
    if (initialTaskInput) {
      setTaskInput(initialTaskInput);
    }
  }, [initialTaskInput]);

  const [loadingUniversalRubric, setLoadingUniversalRubric] = useState(false);
  const [loadingReport, setLoadingReport] = useState(false);
  const [simulationLoading, setSimulationLoading] = useState(false);

  const [universalRubric, setUniversalRubric] = useState<any[]>([]);
  const [report, setReport] = useState<any>(null);
  const [simulationResults, setSimulationResults] = useState<SimulationResults | null>(null);

  const [selectedUniversalRubric, setSelectedUniversalRubric] = useState<any[]>([]);

  const [loadingFinalRubric, setLoadingFinalRubric] = useState(false);
  const [finalRubric, setFinalRubric] = useState<any[]>([]);
  const [selectedFinalRubric, setSelectedFinalRubric] = useState<any[]>([]);

  const [loadingWorkflowRegeneration, setLoadingWorkflowRegeneration] = useState(false);
  const [optimizedWorkflow, setOptimizedWorkflow] = useState<DagData | null>(null);
  const [xmlResult, setXmlResult] = useState<string | null>(null);

  const [logValidating, setLogValidating] = useState(false);
  const [logFileName, setLogFileName] = useState<string>('');

  // Use the workflowId supplied by the parent.
  const finalWorkflowId = workflowId || '';

  // Load existing evaluation details on mount and whenever workflowInfo changes.
  useEffect(() => {
    if (!finalWorkflowId) return;
    initPage();
  }, [finalWorkflowId, workflowInfo?.data?.xml]);

  const initPage = async () => {
    try {
      const res = await getWorkflowEvaluateDetail({ workflow_id: finalWorkflowId });
      const evalRes = (res as any)?.data?.data ?? (res as any)?.data ?? res;

      if (!evalRes) {
        console.log('[EvaluationSection] initPage: no evaluation record found');
        return;
      }

      console.log('[EvaluationSection] initPage: loaded evaluation record', evalRes);

      const initUniversal = evalRes?.universal_rubric ?? evalRes?.univeral_rubric ?? [];
      const initFinal = evalRes?.final_rubric ?? [];

      setUniversalRubric(Array.isArray(initUniversal) ? initUniversal : []);
      setSelectedUniversalRubric(Array.isArray(initUniversal) ? initUniversal : []);
      setReport(evalRes?.report ?? null);
      // Prefer conformance_results (latest post-validation results), then fall back to sim_results.
      setSimulationResults(evalRes?.conformance_results ?? evalRes?.sim_results ?? null);
      setFinalRubric(Array.isArray(initFinal) ? initFinal : []);
      setSelectedFinalRubric(Array.isArray(initFinal) ? initFinal : []);
      setOptimizedWorkflow(evalRes?.optimized_workflow ?? null);
      setXmlResult(evalRes?.xmlresult ?? null);
      const _logPath = evalRes?.log_file_path;
      if (_logPath && typeof _logPath === 'string') {
        setLogFileName(_logPath.split(/[\\/]/).pop() || _logPath);
      }
    } catch (error) {
      console.error('[EvaluationSection] initPage error =', error);
    }
  };

  // currentTask is the object form used for API requests.
  const currentTask = useMemo(() => {
    if (!workflowInfo?.data) {
      console.log('[EvaluationSection] currentTask: workflowInfo.data is empty, returning taskInput');
      return taskInput;
    }
    const data = workflowInfo.data;
    // Extract task_nodes and task_links from dagData.
    const nodes = dagData?.task_nodes ?? [];
    const links = dagData?.task_links ?? [];
    console.log('[EvaluationSection] currentTask: dagData =', dagData ? 'exists' : 'null', ', nodes count =', nodes.length, ', links count =', links.length);
    return {
      id: data.id,
      user_request: data.describe || '',
      extracted_task: data.extracted_task || '',
      task_nodes: nodes,
      task_links: links,
      api_list: parseApiList(data.api_list),
    };
  }, [workflowInfo, taskInput, dagData]);

  const handleToggleRubric = (
    type: "universal" | "final",
    item: any,
    checked: boolean
  ) => {
    if (type === "universal") {
      setSelectedUniversalRubric((prev) => {
        if (checked) {
          if (prev.some((x) => x.theme === item.theme)) return prev;
          return [...prev, item];
        }
        return prev.filter((x) => x.theme !== item.theme);
      });
    } else if (type === "final") {
      setSelectedFinalRubric((prev) => {
        if (checked) {
          if (prev.some((x) => x.theme === item.theme)) return prev;
          return [...prev, item];
        }
        return prev.filter((x) => x.theme !== item.theme);
      });
    }
  };

  // Stage 7: Generic Rubric Generation
  const handleGenerateUniversalRubric = async () => {
    const start = Date.now();

    if (!finalWorkflowId) {
      message.warning('workflow_id is missing.');
      return;
    }
    if (!currentTask) {
      message.warning('task is empty.');
      return;
    }

    try {
      setLoadingUniversalRubric(true);

      const res = await generateUniversalRubric({
        workflow_id: finalWorkflowId,
        task: currentTask,
      });

      const duration = Date.now() - start;
      if (duration < 2500) await sleep(2500 - duration);

      const data = (res as any)?.data ?? res;
      const universalDimensions = data?.universal_rubric ?? data?.data?.universal_rubric ?? [];

      if ((res as any)?.code === 200 || universalDimensions.length > 0) {
        setUniversalRubric(universalDimensions);
        setSelectedUniversalRubric(universalDimensions);
        message.success('Generic rubric generated successfully');
      } else {
        message.error((res as any)?.msg || 'Failed to generate generic rubric');
      }
    } catch (e) {
      console.error(e);
      message.error('Failed to generate generic rubric');
    } finally {
      setLoadingUniversalRubric(false);
    }
  };

  // Stage 8: Multi-Agent Discrepancy Analysis
  const handleGenerateSimulationResults = async () => {
    if (!finalWorkflowId) {
      message.warning('workflow_id is missing.');
      return;
    }
    if (!currentTask) {
      message.warning('task is empty.');
      return;
    }

    try {
      setSimulationLoading(true);

      console.log('[EvaluationSection] handleGenerateSimulationResults: currentTask =', JSON.stringify(currentTask, null, 2).substring(0, 500));
      console.log('[EvaluationSection] handleGenerateSimulationResults: currentTask.task_nodes count =', typeof currentTask === 'object' ? (currentTask as any)?.task_nodes?.length ?? 'undefined' : 'string');

      const res = await generateSimulationResults({
        workflow_id: finalWorkflowId,
        task: currentTask,
      });

      const parsed = unwrapApiResponse<any>(res);
      const simResults =
        parsed?.data?.sim_results ??
        parsed?.raw?.data?.sim_results ??
        parsed?.raw?.sim_results ??
        null;

      if (parsed.code === 200 && simResults) {
        setSimulationResults(simResults);
        message.success('Simulation results generated successfully');
        return;
      }

      message.error(parsed.msg || 'Failed to generate simulation results');
    } catch (error: any) {
      console.error(error);
      message.error(
        error?.response?.data?.msg ||
          error?.response?.data?.detail ||
          error?.message ||
          'Failed to generate simulation results'
      );
    } finally {
      setSimulationLoading(false);
    }
  };

  const handleSimulationStatusChange = (index: number, newStatus: StatusType) => {
    setSimulationResults((prev) => {
      if (!prev?.task_links) return prev;
      const newLinks = [...prev.task_links];
      if (newLinks[index]) {
        newLinks[index] = { ...newLinks[index], status: newStatus };
      }
      return { ...prev, task_links: newLinks };
    });
  };

  // Stage 9: Task-Specific Rubric Generation
  const handleGenerateFinalRubric = async () => {
    if (!finalWorkflowId) {
      message.warning('workflow_id is missing.');
      return;
    }

    if (!currentTask) {
      message.warning('task is empty.');
      return;
    }

    if (!simulationResults) {
      message.warning('Please generate simulation results first.');
      return;
    }

    try {
      setLoadingFinalRubric(true);

      const res = await generateFinalRubric({
        workflow_id: finalWorkflowId,
        task: currentTask,
        sim_results: simulationResults,
      });

      const parsed = unwrapApiResponse<any>(res);
      console.log('final rubric parsed =', parsed);

      const finalRubricData =
        parsed?.data?.final_rubric ??
        parsed?.raw?.data?.final_rubric ??
        parsed?.raw?.final_rubric ??
        [];

      if (parsed.code === 200 && Array.isArray(finalRubricData)) {
        setFinalRubric(finalRubricData);
        setSelectedFinalRubric(finalRubricData);
        message.success('Task-specific rubric generated successfully');
        return;
      }

      message.error(parsed.msg || 'Failed to generate task-specific rubric');
    } catch (error: any) {
      console.error('generate final rubric error ->', error);
      message.error(
        error?.response?.data?.msg ||
          error?.response?.data?.detail ||
          error?.message ||
          'Failed to generate task-specific rubric'
      );
    } finally {
      setLoadingFinalRubric(false);
    }
  };

  // Stage 10: Evaluation Result Generation
  const handleGenerateReport = async () => {
    const start = Date.now();

    if (!finalWorkflowId) {
      message.warning('workflow_id is missing.');
      return;
    }
    if (!currentTask) {
      message.warning('task is empty.');
      return;
    }
    if (selectedUniversalRubric.length === 0) {
      message.warning('Please select at least one generic rubric dimension.');
      return;
    }
    if (selectedFinalRubric.length === 0) {
      message.warning('Please select at least one task-specific rubric dimension.');
      return;
    }

    try {
      setLoadingReport(true);

      const res = await generateReport({
        workflow_id: finalWorkflowId,
        task: currentTask,
        universal_rubric: selectedUniversalRubric,
        final_rubric: selectedFinalRubric,
      });

      const duration = Date.now() - start;
      if (duration < 7800) await sleep(7800 - duration);

      const reportData = (res as any)?.data ?? null;

      if ((res as any)?.code !== 200 || !reportData) {
        message.error((res as any)?.msg || 'Failed to generate Report.');
        return;
      }

      setReport(reportData);
      message.success('Report generated successfully.');
    } catch (error) {
      console.error(error);
      message.error('Failed to generate Report.');
    } finally {
      setLoadingReport(false);
    }
  };

  // Stage 11: Workflow Model Revise
  const handleWorkflowRegeneration = async () => {
    if (!finalWorkflowId) {
      message.warning('workflow_id is missing.');
      return;
    }

    if (!currentTask) {
      message.warning('task is empty.');
      return;
    }

    if (!simulationResults) {
      message.warning('Please generate simulation results first.');
      return;
    }

    try {
      setLoadingWorkflowRegeneration(true);

      const res = await workflowRegeneration({
        workflow_id: finalWorkflowId,
        task: currentTask,
        sim_results: simulationResults,
        original_workflow: dagData,
      });

      const parsed = unwrapApiResponse<any>(res);

      const regeneratedWorkflow =
        parsed?.data?.optimized_workflow ??
        parsed?.raw?.data?.optimized_workflow ??
        parsed?.raw?.optimized_workflow ??
        null;

      if (parsed.code === 200 && regeneratedWorkflow) {
        // Generate XML before updating state so all three result views appear together.
        let xmlResultValue: string | null = null;
        try {
          const xmlRes = await generateXmlFromRevisedWorkflow({
            workflow_id: finalWorkflowId,
            revised_workflow: regeneratedWorkflow,
          });
          const xmlParsed = unwrapApiResponse<any>(xmlRes);
          xmlResultValue = xmlParsed?.data?.xml_result ?? xmlParsed?.raw?.data?.xml_result ?? null;
        } catch (xmlError) {
          console.error('Auto generate XML error ->', xmlError);
        }

        setOptimizedWorkflow(regeneratedWorkflow);
        setXmlResult(xmlResultValue);
        message.success('Workflow regenerated successfully.');
        return;
      }

      message.error(parsed.msg || 'Failed to regenerate workflow.');
    } catch (error: any) {
      console.error('workflow regeneration error ->', error);
      message.error(
        error?.response?.data?.msg ||
          error?.response?.data?.detail ||
          error?.message ||
          'Failed to regenerate workflow.'
      );
    } finally {
      setLoadingWorkflowRegeneration(false);
    }
  };

  const handleValidateEdgesWithLog = async (file: File) => {
    if (!finalWorkflowId) {
      message.warning('Workflow ID not found');
      return;
    }
    if (!simulationResults?.task_links?.length) {
      message.warning('Please generate discrepancy analysis results first');
      return;
    }
    try {
      setLogValidating(true);
      const formData = new FormData();
      formData.append('workflow_id', finalWorkflowId);
      formData.append('sim_results', JSON.stringify(simulationResults));
      formData.append('file', file);
      const res = await validateEdgesWithLog(formData);
      const data = (res as any)?.data?.data ?? (res as any)?.data ?? res;
      const updatedSim = data?.conformance_results;
      if (updatedSim?.task_links) {
        setSimulationResults(updatedSim);
        setLogFileName(file.name);
        message.success('Log validation completed — edge statuses updated');
      } else {
        message.warning('Log validation returned no results');
      }
    } catch (error) {
      console.error('handleValidateEdgesWithLog error =', error);
      message.error('Log validation failed');
    } finally {
      setLogValidating(false);
    }
  };

  const evalSteps = ['Generic Rubric', 'Discrepancy Analysis', 'Task-Specific Rubric', 'Evaluation Report', 'Workflow Revise'];

  return (
    <Spin spinning={false}>
      {/* Match the evaluation progress indicator to the generation progress indicator. */}
      <div className="mt-8 mb-4 rounded-2xl bg-white px-6 py-5 shadow-sm border border-gray-100">
        <div className="mb-2 text-sm font-medium text-gray-500">Workflow Evaluation and Revise</div>
        <div className="flex items-center justify-between text-gray-400 text-[16px]">
          {evalSteps.map((step, index) => (
            <div key={step} className={`flex items-center ${index < evalSteps.length - 1 ? 'flex-1' : ''}`}>
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gray-100 text-gray-500">
                {index + 1}
              </div>
              <span className="ml-3">{step}</span>
              {index < evalSteps.length - 1 && <div className="mx-4 h-px flex-1 bg-gray-200" />}
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-4">
        {/* Stage 1: Generic Rubric Generation */}
        <Card
          title="Stage 1: Generic Rubric Generation"
          className="rounded-2xl shadow-sm"
          extra={
            <Button
              type="primary"
              loading={loadingUniversalRubric}
              onClick={handleGenerateUniversalRubric}
            >
              Generate Generic Rubric
            </Button>
          }
        >
          <div className="flex items-center justify-between">
            <Text type="secondary">Generate the generic rubric for this workflow task.</Text>
            <Text type="secondary">Selected: {selectedUniversalRubric.length}</Text>
          </div>

          <Divider />

          <RubricDimensionList
            dimensions={universalRubric}
            type="universal"
            selectedItems={selectedUniversalRubric}
            onToggle={handleToggleRubric}
          />
        </Card>

        {/* Stage 8: Multi-Agent Discrepancy Analysis */}
        <SimulationResultsCard
          loading={simulationLoading}
          simulationResults={simulationResults}
          onGenerate={handleGenerateSimulationResults}
          onStatusChange={handleSimulationStatusChange}
          onValidateLog={handleValidateEdgesWithLog}
          logValidating={logValidating}
          logFileName={logFileName}
        />

        {/* Stage 3: Task-Specific Rubric Generation */}
        <Card
          title="Stage 3: Task-Specific Rubric Generation"
          className="rounded-2xl shadow-sm"
          extra={
            <Button
              type="primary"
              loading={loadingFinalRubric}
              onClick={handleGenerateFinalRubric}
            >
              Generate Task-specific Rubric
            </Button>
          }
        >
          <div className="flex items-center justify-between">
            <Text type="secondary">
              Generate task-specific rubric from discrepancy analysis warn edges.
            </Text>
            <Text type="secondary">
              Selected: {selectedFinalRubric.length}
            </Text>
          </div>

          <Divider />

          <RubricDimensionList
            dimensions={finalRubric}
            type="final"
            selectedItems={selectedFinalRubric}
            onToggle={handleToggleRubric}
          />
        </Card>

        {/* Stage 10: Evaluation Result Generation */}
        <ReportCard
          loading={loadingReport}
          report={report}
          selectedCount={selectedUniversalRubric.length + selectedFinalRubric.length}
          onGenerate={handleGenerateReport}
        />

        {/* Stage 5: Workflow Model Revise */}
        <WorkflowRegenerationCard
          loading={loadingWorkflowRegeneration}
          optimizedWorkflow={optimizedWorkflow}
          onGenerate={handleWorkflowRegeneration}
          xmlResult={xmlResult}
        />
      </div>
    </Spin>
  );
}
