import {
  ApartmentOutlined,
  CheckCircleFilled,
  LoadingOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import { useEffect, useMemo, useRef } from 'react';
import type { WorkflowRunEvent } from '@/api/schema';
import type { AgentName } from './workflowModel';

const iconMap = {
  coordinator: ApartmentOutlined,
  generation: RobotOutlined,
  evaluation: SafetyCertificateOutlined,
  repair: ToolOutlined,
};

const titleMap = {
  coordinator: 'Coordinator Agent',
  generation: 'Generation Agent',
  evaluation: 'Evaluation Agent',
  repair: 'Repair Agent',
};

const activeStatuses = new Set([
  'pending',
  'generating',
  'evaluating',
  'repairing',
  'verifying',
  'awaiting_review',
]);

interface Props {
  events: WorkflowRunEvent[];
  activeAgent?: AgentName;
  activeStep?: string;
  runStatus: string;
  errorMessage?: string;
}

function isAgentName(value?: string): value is AgentName {
  return ['coordinator', 'generation', 'evaluation', 'repair'].includes(
    String(value)
  );
}

export default function AgentProgress({
  events,
  activeAgent,
  activeStep,
  runStatus,
  errorMessage,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const steps = useMemo(() => {
    const relevant = events.filter((event) => isAgentName(event.agent));
    const compacted: WorkflowRunEvent[] = [];
    relevant.forEach((event) => {
      const previous = compacted[compacted.length - 1];
      if (previous?.agent === event.agent) {
        compacted[compacted.length - 1] = event;
      } else {
        compacted.push(event);
      }
    });
    return compacted;
  }, [events]);
  const latestStepId = steps[steps.length - 1]?.id;

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    container.scrollTo({ left: container.scrollWidth, behavior: 'smooth' });
  }, [latestStepId]);

  const latestCoordinator = [...events]
    .reverse()
    .find((event) => event.agent === 'coordinator');
  const terminalMessage = ({
    completed: 'Coordinator Agent completed the workflow run.',
    needs_review: 'Coordinator Agent paused the run for user review.',
    failed: 'Coordinator Agent stopped the run after an error.',
    stopped: 'Coordinator Agent stopped the workflow run.',
  } as Record<string, string>)[runStatus];
  const coordinatorMessage =
    (runStatus === 'awaiting_review' &&
      activeStep === 'request_dependency_review' &&
      'Coordinator Agent is waiting for your dependency confirmation.') ||
    (terminalMessage && (errorMessage || terminalMessage)) ||
    latestCoordinator?.message ||
    (activeStep
      ? `Coordinator Agent is managing: ${activeStep.split('_').join(' ')}.`
      : 'Coordinator Agent is ready to receive a workflow request.');
  const running = activeStatuses.has(runStatus);

  return (
    <section className="coordination-progress">
      <div className="coordination-progress-header">
        <div className="coordination-progress-avatar">
          {running && activeAgent === 'coordinator' ? (
            <LoadingOutlined spin />
          ) : (
            <ApartmentOutlined />
          )}
        </div>
        <div>
          <div className="section-eyebrow">COORDINATOR AGENT</div>
          <strong>{coordinatorMessage}</strong>
        </div>
      </div>

      <div
        ref={scrollRef}
        className="agent-progress"
        aria-label="Dynamic agent coordination trace"
      >
        {steps.length ? (
          steps.map((event, index) => {
            const agent = event.agent as AgentName;
            const Icon = iconMap[agent];
            const active =
              running &&
              index === steps.length - 1 &&
              agent === activeAgent;
            const failed = runStatus === 'failed' && index === steps.length - 1;
            const interrupted =
              ['needs_review', 'stopped'].includes(runStatus) &&
              index === steps.length - 1;
            return (
              <div className="agent-progress-item" key={event.id}>
                <div
                  className={[
                    'agent-progress-icon',
                    active ? 'is-active' : '',
                    !active && !failed && !interrupted ? 'is-completed' : '',
                    failed ? 'is-failed' : '',
                    interrupted ? 'is-warning' : '',
                  ].join(' ')}
                >
                  {active ? (
                    <LoadingOutlined spin />
                  ) : !failed && !interrupted ? (
                    <CheckCircleFilled />
                  ) : (
                    <Icon />
                  )}
                </div>
                <div className="min-w-0" title={event.message}>
                  <div className="agent-progress-title">{titleMap[agent]}</div>
                  <div className="agent-progress-description">{event.message}</div>
                </div>
                {index < steps.length - 1 && (
                  <div className="agent-progress-line is-completed" />
                )}
              </div>
            );
          })
        ) : (
          <div className="coordination-progress-empty">
            Submit a workflow request to start the coordination trace.
          </div>
        )}
      </div>
    </section>
  );
}
