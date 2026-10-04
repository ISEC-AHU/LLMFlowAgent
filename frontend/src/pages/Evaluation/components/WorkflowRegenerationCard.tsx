import { Button, Card, Divider, Typography } from 'antd';
import type { DagData } from '../types';
import FlowChart from '../../../components/FlowGraph/FlowChart';
import MarkdownRenderer from '../../../components/MarkdownRender';

const { Text } = Typography;

interface WorkflowRegenerationCardProps {
  loading: boolean;
  optimizedWorkflow: DagData | null;
  onGenerate: () => void;
  xmlResult?: string | null;
}

export default function WorkflowRegenerationCard({
  loading,
  optimizedWorkflow,
  onGenerate,
  xmlResult,
}: WorkflowRegenerationCardProps) {
  const dagJsonString = optimizedWorkflow
    ? '```json\n' + JSON.stringify(optimizedWorkflow, null, 2) + '\n```'
    : '';

  return (
    <Card
      title="Stage 5: Workflow Model Revise"
      className="rounded-2xl shadow-sm"
      extra={
        <Button type="primary" loading={loading} onClick={onGenerate}>
          Revise Workflow
        </Button>
      }
    >
      <div className="flex items-center justify-between">
        <Text type="secondary">
          Generate the final workflow DAG by merging the original DAG with discrepancy analysis results.
        </Text>
      </div>

      <Divider />

      {optimizedWorkflow ? (
        <div className="space-y-4">
          {/* Flow Preview */}
          {optimizedWorkflow.task_nodes && optimizedWorkflow.task_nodes.length > 0 && (
            <div>
              <div className="mb-2 text-sm font-medium text-gray-700">Flow Preview</div>
              <div className="rounded-lg border border-gray-200 bg-[#f8fafc] p-4">
                <FlowChart
                  width={'80%'}
                  height={150}
                  taskData={optimizedWorkflow}
                />
              </div>
            </div>
          )}

          {/* DAG Result */}
          <div>
            <div className="mb-2 text-sm font-medium text-gray-700">DAG Result</div>
            <div className="rounded-lg border border-gray-200 bg-white p-4">
              <MarkdownRenderer markdown={dagJsonString} />
            </div>
          </div>

          {/* XML Result */}
          <Divider />
          <div className="text-sm font-medium text-gray-700 mb-2">XML Result</div>
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            {xmlResult ? (
              <MarkdownRenderer markdown={xmlResult} />
            ) : (
              <div className="text-sm text-gray-400">No XML generated yet.</div>
            )}
          </div>
        </div>
      ) : (
        <Text type="secondary">
          No regenerated workflow has been generated yet.
        </Text>
      )}
    </Card>
  );
}
