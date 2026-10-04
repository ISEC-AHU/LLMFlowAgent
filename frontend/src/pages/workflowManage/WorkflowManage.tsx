import React from 'react';
import { Button, Card, List, Popconfirm, Segmented, Tag, message } from 'antd';
import {
  PlusOutlined,
  ApartmentOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { deleteWorkflow, getWorkflowList } from '@/api/api';
import { useNavigate } from 'react-router-dom';
import { useRequest } from 'ahooks';

const WorkflowManage: React.FC = () => {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = React.useState('all');

  const { data, loading, refresh } = useRequest(getWorkflowList);

  const { run: runDeleteWorkflow, loading: deleteLoading } = useRequest(
    async (id: string) => {
      return await deleteWorkflow(id);
    },
    {
      manual: true,
      onSuccess: (res) => {
        if (res.code === 200) {
          message.success(res.msg || 'Deletion successful');
          refresh();
        } else {
          message.error(res.msg || 'Deletion failed');
        }
      },
      onError: () => {
        message.error('Deletion failed');
      },
    }
  );

  const workflowList = data?.data || [];
  const filteredList = workflowList.filter((item: any) => {
    if (statusFilter === 'all') return true;
    if (statusFilter === 'running') {
      return ['pending', 'generating', 'evaluating', 'repairing', 'verifying'].includes(
        item.run_status
      );
    }
    return item.run_status === statusFilter;
  });
  const statusColors: Record<string, string> = {
    pending: 'processing',
    generating: 'processing',
    evaluating: 'cyan',
    repairing: 'purple',
    verifying: 'geekblue',
    completed: 'success',
    needs_review: 'warning',
    failed: 'error',
    stopped: 'default',
  };

  return (
    <div className="p-6 bg-[#f5f7fa] min-h-[calc(100vh-66px)]">
      <Card className="rounded-xl shadow-sm mb-4">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center text-[24px] font-bold mb-2">
              <ApartmentOutlined className="mr-2" />
              Workflow Design
            </div>
            <div className="text-gray-500">
              Used for creating, viewing and managing workflows in the system, 
              and supports accessing the workflow details page to generate workflows based on a large language model.
            </div>
          </div>

          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => navigate('/workflow/add')}
          >
            Create a workflow design task
          </Button>
        </div>
      </Card>

      <Card
        className="rounded-xl shadow-sm"
        title={<span className="font-semibold">Workflow Design Task List</span>}
        extra={
          <Segmented
            value={statusFilter}
            onChange={(value) => setStatusFilter(String(value))}
            options={[
              { label: 'All', value: 'all' },
              { label: 'Running', value: 'running' },
              { label: 'Completed', value: 'completed' },
              { label: 'Needs review', value: 'needs_review' },
              { label: 'Failed', value: 'failed' },
            ]}
          />
        }
        loading={loading}
      >
        <List
          dataSource={filteredList}
          locale={{ emptyText: 'No Generate Workflow Task available.' }}
          renderItem={(item: any) => (
            <List.Item className="hover:bg-gray-50 rounded-md px-4">
              <div className="w-full flex items-center justify-between">
                <div
                  className="cursor-pointer"
                  onClick={() => navigate(`/workflow/${item.id}`)}
                >
                  <div className="font-medium text-[16px]">
                    Workflow {item.id}
                    {item.run_status && (
                      <Tag
                        className="ml-3"
                        color={statusColors[item.run_status] || 'default'}
                      >
                        {String(item.run_status).split('_').join(' ').toUpperCase()}
                      </Tag>
                    )}
                  </div>
                  <div className="max-w-3xl truncate text-gray-500 text-sm mt-1">
                    {item.describe || 'No workflow description yet.'}
                  </div>
                  <div className="text-gray-400 text-xs mt-2">
                    {item.current_version
                      ? `Current v${item.current_version}`
                      : 'No version yet'}
                    {item.best_version ? ` | Best v${item.best_version}` : ''}
                    {item.final_version ? ` | Final v${item.final_version}` : ''}
                    {typeof item.final_score === 'number'
                      ? ` | Score ${item.final_score.toFixed(1)}/5`
                      : ''}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    type="link"
                    onClick={() => navigate(`/workflow/${item.id}`)}
                  >
                    Enter
                  </Button>

                  <Popconfirm
                    title="Confirm deletion of this generate workflow task?"
                    okText="Delete"
                    cancelText="Cancel"
                    onConfirm={() => runDeleteWorkflow(String(item.id))}
                  >
                    <Button
                      type="text"
                      danger
                      icon={<DeleteOutlined />}
                      loading={deleteLoading}
                    />
                  </Popconfirm>
                </div>
              </div>
            </List.Item>
          )}
        />
      </Card>
    </div>
  );
};

export default WorkflowManage;
