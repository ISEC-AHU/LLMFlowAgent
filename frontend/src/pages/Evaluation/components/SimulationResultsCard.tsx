import { useState } from 'react';
import { Button, Card, Divider, Empty, Select, Table, Tag, Upload, message } from 'antd';
import { UploadOutlined } from '@ant-design/icons';
import type { Key } from 'react';
import type {
  SimulationResults,
  TaskLinkDifferenceItem,
  StatusType,
} from '../types';

interface Props {
  loading: boolean;
  simulationResults: SimulationResults | null;
  onGenerate: () => void;
  onStatusChange?: (index: number, newStatus: StatusType) => void;
  onValidateLog?: (file: File) => void;
  logValidating?: boolean;
  logFileName?: string;
}

type DisplayTaskLinkItem = TaskLinkDifferenceItem & {
  key: Key;
};

export default function SimulationResultsCard({
  loading,
  simulationResults,
  onGenerate,
  onStatusChange,
  onValidateLog,
  logValidating,
  logFileName,
}: Props) {
  const [selectedLogFile, setSelectedLogFile] = useState<File | null>(null);

  const getStatusColor = (status: StatusType) => {
    if (status === 'pass') return 'green';
    if (status === 'warn') return 'red';
    return 'default';
  };

  const handleBeforeUpload = (file: File) => {
    const isXes =
      file.name.endsWith('.xes') || file.name.endsWith('.xes.gz');
    if (!isXes) {
      message.warning('Please upload a .xes log file');
    }
    setSelectedLogFile(file);
    return false; // prevent auto upload
  };

  const handleValidateLog = () => {
    if (!selectedLogFile) {
      message.warning('Please select a log file first');
      return;
    }
    onValidateLog?.(selectedLogFile);
  };

  const taskLinks = simulationResults?.task_links || [];

  const taskLinkData: DisplayTaskLinkItem[] = taskLinks.map((item, index) => ({
    ...item,
    key: `${item.source}->${item.target}-${index}`,
  }));

  const linkPassCount = taskLinks.filter((item) => item.status === 'pass').length;
  const linkWarnCount = taskLinks.filter((item) => item.status === 'warn').length;

  return (
    <Card
      title="Stage 2: Multi-Agent Discrepancy Analysis"
      className="rounded-2xl shadow-sm mb-6"
      extra={
        <Button type="primary" loading={loading} onClick={onGenerate}>
          Discrepancy Analysis
        </Button>
      }
    >
      {!simulationResults ? (
        <Empty description="No discrepancy analysis results yet" />
      ) : (
        <div className="space-y-6">
          <div>
            <div className="text-[16px] font-semibold mb-3">
              Task Link
            </div>

            <div className="flex flex-wrap gap-3 mb-4">
              <Tag color="blue">Total Links: {taskLinkData.length}</Tag>
              <Tag color="green">PASS: {linkPassCount}</Tag>
              <Tag color="red">WARN: {linkWarnCount}</Tag>
            </div>

            {/* Log Validation Section */}
            <Divider className="!my-3" />
            <div className="mb-4">
              <div className="text-[14px] font-medium text-gray-600 mb-2">
                Log Validation (Optional — logs serve as ground truth)
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <Upload
                  accept=".xes,.xes.gz"
                  beforeUpload={handleBeforeUpload}
                  showUploadList={false}
                >
                  <Button icon={<UploadOutlined />} size="small">
                    Select Log File
                  </Button>
                </Upload>
                <Button
                  type="primary"
                  size="small"
                  loading={logValidating}
                  onClick={handleValidateLog}
                  disabled={!onValidateLog}
                >
                  Validate with Log
                </Button>
                {(selectedLogFile || logFileName) && (
                  <span className="text-sm text-gray-500">
                    {selectedLogFile?.name || logFileName}
                  </span>
                )}
              </div>
            </div>

            <Table
              size="small"
              pagination={false}
              dataSource={taskLinkData}
              columns={[
                {
                  title: 'Task Link',
                  key: 'task_link',
                  render: (_, record: DisplayTaskLinkItem) =>
                    `${record.source} → ${record.target}`,
                },
                {
                  title: 'Status',
                  dataIndex: 'status',
                  key: 'status',
                  width: 160,
                  render: (status: StatusType, _record: DisplayTaskLinkItem, index: number) =>
                    onStatusChange ? (
                      <Select
                        size="small"
                        value={status}
                        style={{ width: 120 }}
                        onChange={(val: StatusType) => onStatusChange(index, val)}
                        labelRender={(props) => (
                          <Tag color={getStatusColor(props.value as StatusType)} style={{ margin: 0 }}>
                            {(props.value as string).toUpperCase()}
                          </Tag>
                        )}
                        options={[
                          { value: 'pass', label: 'PASS' },
                          { value: 'warn', label: 'WARN' },
                        ]}
                      />
                    ) : (
                      <Tag color={getStatusColor(status)}>{status.toUpperCase()}</Tag>
                    ),
                },
              ]}
            />
          </div>
        </div>
      )}
    </Card>
  );
}
