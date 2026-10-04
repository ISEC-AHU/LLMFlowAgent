import { useCallback, useEffect, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import {
  acceptWorkflowVersion,
  addWorkflow,
  confirmWorkflowDependencyReview,
  getLatestWorkflowRun,
  getWorkflowRun,
  retryWorkflowRun,
  startWorkflowRun,
  stopWorkflowRun,
} from '@/api/api';
import type { WorkflowRunRecord } from '@/api/schema';

export const ACTIVE_RUN_STATUSES = new Set([
  'pending',
  'generating',
  'evaluating',
  'repairing',
  'verifying',
  'awaiting_review',
]);

const POLLING_RUN_STATUSES = new Set([
  'pending',
  'generating',
  'evaluating',
  'repairing',
  'verifying',
]);

const POLLING_INTERVAL_MS = 1500;
const POLLING_FAILURE_THRESHOLD = 3;

const getPollingErrorMessage = (error: unknown) => {
  if (typeof error !== 'object' || error === null) {
    return 'Unable to refresh the workflow run.';
  }
  const candidate = error as {
    response?: { data?: { detail?: string; msg?: string } };
    message?: string;
  };
  return (
    candidate.response?.data?.detail ||
    candidate.response?.data?.msg ||
    candidate.message ||
    'Unable to refresh the workflow run.'
  );
};

export function useWorkflowRun() {
  const [run, setRun] = useState<WorkflowRunRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [pollingError, setPollingError] = useState<string | null>(null);

  const loadLatest = useCallback(async (workflowId: string) => {
    const response = await getLatestWorkflowRun(workflowId);
    if (response.code !== 200) {
      throw new Error(response.msg || 'Unable to load the workflow run.');
    }
    setRun(response.data || null);
    setPollingError(null);
    return response.data || null;
  }, []);

  const refresh = useCallback(async (runId?: string) => {
    const id = runId || run?.id;
    if (!id) return null;
    const response = await getWorkflowRun(id);
    if (response.code !== 200 || !response.data) {
      throw new Error(response.msg || 'Unable to refresh the workflow run.');
    }
    setRun(response.data);
    setPollingError(null);
    return response.data;
  }, [run?.id]);

  useEffect(() => {
    if (!run?.id || !POLLING_RUN_STATUSES.has(run.status)) {
      setPollingError(null);
      return;
    }
    const runId = run.id;
    let cancelled = false;
    let timer: number | undefined;
    let consecutiveFailures = 0;
    let failureReported = false;

    const scheduleNextPoll = () => {
      if (!cancelled) {
        timer = window.setTimeout(poll, POLLING_INTERVAL_MS);
      }
    };

    const poll = async () => {
      try {
        const response = await getWorkflowRun(runId);
        if (response.code !== 200 || !response.data) {
          throw new Error(response.msg || 'Unable to refresh the workflow run.');
        }
        if (cancelled) return;
        consecutiveFailures = 0;
        failureReported = false;
        setPollingError(null);
        setRun(response.data);
      } catch (error) {
        if (cancelled) return;
        consecutiveFailures += 1;
        if (
          consecutiveFailures >= POLLING_FAILURE_THRESHOLD &&
          !failureReported
        ) {
          failureReported = true;
          setPollingError(
            `Live status could not be refreshed after repeated attempts: ${getPollingErrorMessage(error)}`
          );
        }
      } finally {
        scheduleNextPoll();
      }
    };

    setPollingError(null);
    scheduleNextPoll();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [run?.id, run?.status]);

  const start = useCallback(
    async ({
      workflowId,
      description,
      maxIterations,
      regenerationThreshold,
      acceptanceThreshold,
      autoRepair,
    }: {
      workflowId?: string;
      description: string;
      maxIterations: number;
      regenerationThreshold: number;
      acceptanceThreshold: number;
      autoRepair: boolean;
    }) => {
      setLoading(true);
      try {
        let id = workflowId;
        if (!id) {
          const created = await addWorkflow(uuidv4());
          if (created.code !== 200 || !created.data?.id) {
            throw new Error(created.msg || 'Unable to create the workflow.');
          }
          id = String(created.data.id);
        }
        const response = await startWorkflowRun(id, {
          description,
          max_iterations: maxIterations,
          regeneration_threshold: regenerationThreshold,
          acceptance_threshold: acceptanceThreshold,
          auto_repair: autoRepair,
        });
        if (response.code !== 200 || !response.data) {
          throw new Error(response.msg || 'Unable to start workflow optimization.');
        }
        setRun(response.data);
        setPollingError(null);
        return { workflowId: id, run: response.data };
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const stop = useCallback(async () => {
    if (!run?.id) return;
    const response = await stopWorkflowRun(run.id);
    if (response.code !== 200) {
      throw new Error(response.msg || 'Unable to stop the workflow run.');
    }
    if (response.data) setRun(response.data);
    setPollingError(null);
  }, [run?.id]);

  const retry = useCallback(async () => {
    if (!run?.id) return;
    const response = await retryWorkflowRun(run.id);
    if (response.code !== 200 || !response.data) {
      throw new Error(response.msg || 'Unable to retry the workflow run.');
    }
    setRun(response.data);
    setPollingError(null);
  }, [run?.id]);

  const accept = useCallback(
    async (versionNo: number) => {
      if (!run?.id) return;
      const response = await acceptWorkflowVersion(run.id, versionNo);
      if (response.code !== 200 || !response.data) {
        throw new Error(response.msg || 'Unable to accept this workflow version.');
      }
      setRun(response.data);
    },
    [run?.id]
  );

  const confirmDependencies = useCallback(
    async (
      versionNo: number,
      taskLinks: Array<{
        source: string;
        target: string;
        status: 'pass' | 'warn';
      }>
    ) => {
      if (!run?.id) return;
      const response = await confirmWorkflowDependencyReview(
        run.id,
        versionNo,
        taskLinks
      );
      if (response.code !== 200 || !response.data) {
        throw new Error(response.msg || 'Unable to confirm dependency review.');
      }
      setRun(response.data);
      return response.data;
    },
    [run?.id]
  );

  return {
    run,
    setRun,
    loading,
    pollingError,
    loadLatest,
    refresh,
    start,
    stop,
    retry,
    accept,
    confirmDependencies,
  };
}
