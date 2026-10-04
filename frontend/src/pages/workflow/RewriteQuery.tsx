import './workflow.css';

import { Button, Card } from 'antd';
import RewriteFormModal, { PromptParamsResponse } from './RewriteModal';
import { getPromptParams, rewriteQueries } from '@/api/api';
import { useParams } from 'react-router-dom';
import { useRequest } from 'ahooks';
import { useState } from 'react';

export interface SetValueParams {
  extracted_task: string;
  rewrite_queries: string[];
}

interface RwriteQueryProps {
  prompt?: string;
  rewrite_queries?: string[];
  setValue: (params: SetValueParams) => void;
}

const RewriteQuery: React.FC<RwriteQueryProps> = (props) => {
  const [open, setOpen] = useState(false);
  const { workflowId } = useParams();
  const [confirmLoading, setConfirmLoading] = useState(false);

  const { run, data: ParamsData } = useRequest(getPromptParams, {
    manual: true,
  });

  const onOpenModal = () => {
    setOpen(true);
    run(workflowId as string);
  };

  const handleRewrite = async (values: PromptParamsResponse) => {
    try {
      setConfirmLoading(true);

      console.log('rewrite input values:', values);

      const text = values.text || '';
      const res = await rewriteQueries({ text, k: values.k });

      console.log('rewrite result:', res);

      if (res.code !== 200 || !Array.isArray(res.data)) {
        throw new Error(`Rewrite query failed: ${res.msg || 'invalid response'}`);
      }

      const rewriteQueriesResult = (res.data as unknown[])
        .map((item) => String(item).trim())
        .filter(Boolean);

      console.log('rewriteQueries:', rewriteQueriesResult);
      console.log('rewriteQueries length:', rewriteQueriesResult.length);

      if (rewriteQueriesResult.length === 0) {
        throw new Error('Rewrite query failed: no queries generated');
      }

      props.setValue({
        extracted_task: text,
        rewrite_queries: rewriteQueriesResult,
      });

      setOpen(false);
    } catch (e) {
      console.log('queryRewrite error:', e);
    } finally {
      setConfirmLoading(false);
    }
  };

  return (
    <Card className="mb-4 rounded-xl shadow-sm">
      <div className="flex items-center justify-between px-1 py-1">
        <div className="text-[15px] font-semibold text-gray-800">
          Stage 3: Task Rewriting
        </div>

        <Button type="primary" onClick={onOpenModal}>
          Set Params
        </Button>
      </div>

      <div className="px-1 pb-3 text-sm text-gray-400">
        Rewrite the extracted task into multiple retrieval-friendly queries.
      </div>

      <div className="mb-4 border-t border-gray-100" />
<div className="space-y-4">
  {/* Prompt display commented out
  <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
    <div className="mb-2 text-sm font-medium text-gray-700">Prompt</div>

    <div className="whitespace-pre-wrap text-sm text-gray-600">
      {props?.prompt
        ? props.prompt.split('\n').map((line, index) => (
            <div className="mb-2" key={index}>
              {line}
            </div>
          ))
        : 'No prompt available.'}
    </div>
  </div>
  */}

  <div className="rounded-lg border border-gray-200 bg-white p-4">
    <div className="mb-2 text-sm font-medium text-gray-700">
      Rewrite Results
    </div>
    <div className="text-sm text-gray-600">
      {props?.rewrite_queries?.length ? (
        props.rewrite_queries.map((query, index) => (
          <div className="mb-2" key={index}>
            <span className="mr-2 font-medium text-gray-400">
              {index + 1}.
            </span>
            {query}
          </div>
        ))
      ) : (
        <div className="text-gray-400">
          No rewrite results yet. Click "Set Params" to start.
        </div>
      )}
    </div>
  </div>
</div>

      <RewriteFormModal
        initialValues={{
          text: ParamsData?.data.text,
          k: ParamsData?.data.k,
        }}
        confirmLoading={confirmLoading}
        open={open}
        onRewrite={handleRewrite}
        onCancel={() => setOpen(false)}
      />
    </Card>
  );
};

export default RewriteQuery;
