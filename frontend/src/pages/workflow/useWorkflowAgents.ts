import { useCallback, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import {
  addWorkflow,
  create_game_chain,
  generateFinalRubric,
  generateReport,
  generateSimulationResults,
  generateUniversalRubric,
  generateXmlFromRevisedWorkflow,
  getRetrieveDocs,
  rewriteQueries,
  updateWorkflow,
  workflowRegeneration,
  write_dag_chain,
} from '@/api/api';
import { unwrapApiResponse } from '@/utils/apiHelper';
import type { DagData } from '../Evaluation/types';
import {
  type AgentStep,
  makeTask,
  parseDag,
} from './workflowModel';

const initialGenerationSteps: AgentStep[] = [
  { key: 'decompose', label: 'Task decomposition', status: 'waiting' },
  { key: 'rewrite', label: 'Query rewriting', status: 'waiting' },
  { key: 'retrieve', label: 'API retrieval', status: 'waiting' },
  { key: 'dag', label: 'DAG generation', status: 'waiting' },
];

const updateStep = (
  steps: AgentStep[],
  key: string,
  patch: Partial<AgentStep>
) => steps.map((step) => (step.key === key ? { ...step, ...patch } : step));

const responseData = <T,>(response: any): T | null => {
  const parsed = unwrapApiResponse<T>(response);
  return parsed.data;
};

export function useWorkflowGeneration() {
  const [steps, setSteps] = useState<AgentStep[]>(initialGenerationSteps);
  const [loading, setLoading] = useState(false);

  const run = useCallback(
    async ({
      description,
      workflowId,
      sessionId,
    }: {
      description: string;
      workflowId?: string;
      sessionId?: string;
    }) => {
      setLoading(true);
      setSteps(initialGenerationSteps);

      let activeStep = 'decompose';
      try {
        let id = workflowId;
        let sid = sessionId;

        if (!id) {
          sid = uuidv4();
          const created = await addWorkflow(sid);
          if (created.code !== 200 || !created.data?.id) {
            throw new Error(created.msg || 'Unable to create the workflow.');
          }
          id = String(created.data.id);
        }
        if (!sid) throw new Error('Workflow session is unavailable.');

        setSteps((value) =>
          updateStep(value, 'decompose', { status: 'running' })
        );
        await create_game_chain.invoke(
          { input: '' },
          { configurable: { session_id: sid } }
        );
        const requestText = description.trim().toLowerCase().startsWith('workflow:')
          ? description.trim()
          : `workflow: ${description.trim()}`;
        const extracted = String(
          await create_game_chain.invoke(
            { input: requestText },
            { configurable: { session_id: sid } }
          )
        );
        await updateWorkflow({
          id,
          describe: description.trim(),
          extracted_task: extracted,
        });
        const taskCount = extracted
          .split('\n')
          .map((item) => item.trim())
          .filter(Boolean).length;
        setSteps((value) =>
          updateStep(value, 'decompose', {
            status: 'completed',
            summary: `${taskCount} atomic tasks`,
          })
        );

        activeStep = 'rewrite';
        setSteps((value) =>
          updateStep(value, 'rewrite', { status: 'running' })
        );
        const rewritten = await rewriteQueries({ text: extracted });
        if (rewritten.code !== 200 || !Array.isArray(rewritten.data)) {
          throw new Error(rewritten.msg || 'Query rewriting failed.');
        }
        await updateWorkflow({
          id,
          extracted_task: extracted,
          rewrite_queries: rewritten.data,
        });
        setSteps((value) =>
          updateStep(value, 'rewrite', {
            status: 'completed',
            summary: `${rewritten.data.length} retrieval queries`,
          })
        );

        activeStep = 'retrieve';
        setSteps((value) =>
          updateStep(value, 'retrieve', { status: 'running' })
        );
        const retrieved = await getRetrieveDocs({
          queries: rewritten.data,
          task_steps: extracted
            .split('\n')
            .map((item) => item.trim())
            .filter(Boolean),
        });
        if (retrieved.code !== 200 || !Array.isArray(retrieved.data)) {
          throw new Error(retrieved.msg || 'API retrieval failed.');
        }
        const apiList = retrieved.data as any[];
        await updateWorkflow({ id, api_list: apiList });
        setSteps((value) =>
          updateStep(value, 'retrieve', {
            status: 'completed',
            summary: `${apiList.length} selected APIs`,
          })
        );

        activeStep = 'dag';
        setSteps((value) =>
          updateStep(value, 'dag', { status: 'running' })
        );
        const dagResponse = await write_dag_chain.invoke(
          {
            text: description.trim(),
            task_list: extracted,
            api_list: JSON.stringify(
              apiList
                .filter((item) => item.status === 1)
                .map((item) => item.doc)
            ),
          },
          { configurable: { session_id: sid } }
        );
        const dag = parseDag(dagResponse);
        if (!dag) throw new Error('The generated DAG is not valid JSON.');
        await updateWorkflow({ id, dag: String(dagResponse) });
        setSteps((value) =>
          updateStep(value, 'dag', {
            status: 'completed',
            summary: `${dag.task_nodes.length} nodes | ${dag.task_links.length} edges`,
          })
        );

        return {
          workflowId: id,
          sessionId: sid,
          description: description.trim(),
          extractedTask: extracted,
          rewriteQueries: rewritten.data,
          apiList,
          dag,
        };
      } catch (error) {
        setSteps((value) =>
          updateStep(value, activeStep, { status: 'failed' })
        );
        throw error;
      } finally {
        setLoading(false);
      }
    },
    []
  );

  return { run, steps, loading };
}

export function useWorkflowEvaluation() {
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState('');

  const run = useCallback(async (workflowId: string, workflow: any, dag: DagData) => {
    setLoading(true);
    try {
      const task = makeTask(workflow, dag);

      setStage('Generating generic evaluation criteria');
      const universalResponse = await generateUniversalRubric({
        workflow_id: workflowId,
        task,
      });
      const universalPayload = responseData<any>(universalResponse);
      const universalRubric =
        universalPayload?.universal_rubric ||
        universalPayload?.data?.universal_rubric ||
        [];

      setStage('Comparing independent DAG proposals');
      const simulationResponse = await generateSimulationResults({
        workflow_id: workflowId,
        task,
      });
      const simulationPayload = responseData<any>(simulationResponse);
      const simulation =
        simulationPayload?.sim_results ||
        simulationPayload?.data?.sim_results ||
        null;
      if (!simulation) throw new Error('Discrepancy analysis returned no result.');

      setStage('Generating task-specific evaluation criteria');
      const finalResponse = await generateFinalRubric({
        workflow_id: workflowId,
        task,
        sim_results: simulation,
      });
      const finalPayload = responseData<any>(finalResponse);
      const finalRubric =
        finalPayload?.final_rubric || finalPayload?.data?.final_rubric || [];

      setStage('Scoring the workflow');
      const reportResponse = await generateReport({
        workflow_id: workflowId,
        task,
        universal_rubric: universalRubric,
        final_rubric: finalRubric,
      });
      const report = responseData<any>(reportResponse);
      if (!report) throw new Error('Evaluation report returned no result.');

      return { universalRubric, simulation, finalRubric, report };
    } finally {
      setLoading(false);
      setStage('');
    }
  }, []);

  return { run, loading, stage };
}

export function useWorkflowRepair() {
  const [loading, setLoading] = useState(false);
  const [stage, setStage] = useState('');

  const run = useCallback(
    async ({
      workflowId,
      workflow,
      originalDag,
      simulation,
    }: {
      workflowId: string;
      workflow: any;
      originalDag: DagData;
      simulation: any;
    }) => {
      setLoading(true);
      try {
        setStage('Applying dependency repairs');
        const repairedResponse = await workflowRegeneration({
          workflow_id: workflowId,
          task: makeTask(workflow, originalDag),
          sim_results: simulation,
          original_workflow: originalDag,
        });
        const repairedPayload = responseData<any>(repairedResponse);
        const revisedDag = parseDag(
          repairedPayload?.optimized_workflow ||
            repairedPayload?.data?.optimized_workflow
        );
        if (!revisedDag) throw new Error('Repair returned an invalid DAG.');

        setStage('Generating the final XML model');
        const xmlResponse = await generateXmlFromRevisedWorkflow({
          workflow_id: workflowId,
          revised_workflow: revisedDag,
        });
        const xmlPayload = responseData<any>(xmlResponse);
        const xml =
          xmlPayload?.xml_result || xmlPayload?.data?.xml_result || null;

        return { revisedDag, xml };
      } finally {
        setLoading(false);
        setStage('');
      }
    },
    []
  );

  return { run, loading, stage };
}
