import './workflow.css';

import { Button, Card, Checkbox, Input, Modal, Space } from 'antd';
import { custom_api_chain, getRetrieveDocs } from '@/api/api';
import { useEffect, useMemo, useState } from 'react';

import type { GetProp } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { useParams } from 'react-router-dom';
import { useRequest } from 'ahooks';

const safeParsePageContent = (pageContent: string) => {
  try {
    return JSON.parse(pageContent);
  } catch (error) {
    console.warn('page_content is not valid JSON:', pageContent);
    return null;
  }
};

const RetrieveApi: React.FC<{
  query_list?: string[];
  task_steps?: string[];
  api_list?: any[];
  update: (value: any) => void;
}> = (props) => {
  const { workflowId } = useParams();
  const [describe, setDescribe] = useState('');
  const [customApi, setCustomAPI] = useState('');
  const [isModalVisible, setIsModalVisible] = useState(false);

  const { loading, run: runRetrieveDocs } = useRequest(getRetrieveDocs, {
    manual: true,
    onSuccess: (res) => {
      if (res.code === 200) {
        props.update({
          id: workflowId as string,
          api_list: res?.data,
        });
      }
    },
  });

  const normalizedApiList = useMemo(() => {
    return (props?.api_list || []).map((item, index) => {
      const pageContent = item?.doc?.page_content || '';
      const content = safeParsePageContent(pageContent);

      const name =
        content?.name ||
        content?.id ||
        pageContent ||
        'Unknown API';

      return {
        ...item,
        parsedName: name,
        parsedValue: `${name}-${index}`,
      };
    });
  }, [props?.api_list]);

  const onChange: GetProp<typeof Checkbox.Group, 'onChange'> = (
    checkedValues
  ) => {
    const values = normalizedApiList.map((item) => {
      return {
        ...item,
        status: checkedValues.includes(item.parsedValue) ? 1 : 0,
      };
    });

    props.update({
      id: workflowId as string,
      api_list: values.map(({ parsedName, parsedValue, ...rest }) => rest),
    });
  };

  const addCustomApi = async () => {
    const res = await custom_api_chain.invoke({
      description: describe,
    });
    setCustomAPI(res);
  };

  const handleCustomAPISubmit = () => {
    const api = {
      doc: {
        metadata: {
          source: `workflowId:${workflowId}`,
        },
        page_content: customApi,
        type: 'Custom',
      },
      status: 1,
    };

    props.update({
      id: workflowId as string,
      api_list: [...(props.api_list || []), api],
    });

    setIsModalVisible(false);
  };

  useEffect(() => {
    if (!isModalVisible) {
      setDescribe('');
      setCustomAPI('');
    }
  }, [isModalVisible]);

  return (
    <Card className="mb-4 rounded-xl shadow-sm">
      <div className="flex items-center justify-between px-1 py-1">
        <div className="text-[15px] font-semibold text-gray-800">
          Stage 4: API Retrieval
        </div>

        <Button
          type="primary"
          loading={loading}
          onClick={() => {
            runRetrieveDocs({
              queries: props.query_list as string[],
              task_steps: props.task_steps,
            });
          }}
        >
          Retrieve
        </Button>
      </div>

      <div className="px-1 pb-3 text-sm text-gray-400">
        Retrieve candidate APIs for the rewritten queries and select the usable ones.
      </div>

      <div className="mb-4 border-t border-gray-100" />

      <div className="space-y-4">
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-sm font-medium text-gray-700">
              Retrieved APIs
            </div>

            {props?.query_list?.length ? (
              <Button
                size="small"
                icon={<PlusOutlined />}
                onClick={() => setIsModalVisible(true)}
              >
                Custom API
              </Button>
            ) : null}
          </div>

          <div className="text-sm text-gray-600">
            {normalizedApiList.length ? (
              <Checkbox.Group
                className="flex flex-col gap-2"
                value={normalizedApiList
                  .filter((item) => item.status == 1)
                  .map((item) => item.parsedValue)}
                options={normalizedApiList.map((item) => ({
                  label: item.parsedName,
                  value: item.parsedValue,
                }))}
                onChange={onChange}
              />
            ) : (
              <div className="text-gray-400">No APIs retrieved yet.</div>
            )}
          </div>
        </div>
      </div>

      <Modal
        title="Custom API"
        open={isModalVisible}
        onOk={handleCustomAPISubmit}
        onCancel={() => setIsModalVisible(false)}
      >
        <Space.Compact style={{ width: '100%' }}>
          <Input
            placeholder="api describe"
            value={describe}
            onChange={(e) => setDescribe(e.target.value)}
          />
          <Button onClick={addCustomApi}>Prompt</Button>
        </Space.Compact>

        <div className="mt-2 whitespace-pre-wrap text-sm text-gray-700">
          {customApi}
        </div>
      </Modal>
    </Card>
  );
};

export default RetrieveApi;
