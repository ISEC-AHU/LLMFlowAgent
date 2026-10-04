import React from 'react';
import { Button, Card, message, Popconfirm, Tag } from 'antd';
import {
  DeleteOutlined,
  DatabaseOutlined,
  CheckCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons';
import {
  deleteCollection,
  getCollectionList,
  selectCollection,
} from '@/api/api';
import { useRequest } from 'ahooks';
import KnowledgeBaseCreateModal from './KnowledgeBaseCreateModal';

interface CollectionType {
  collection_name: string;
  collection_describe?: string;
  create_time?: string;
  is_selected?: boolean;
  tool_count?: number;
  retrieval_backend?: string;
}

const KnowledgeBase: React.FC = () => {
  const [open, setOpen] = React.useState(false);
  const {
    data,
    loading,
    run: runCollectionList,
  } = useRequest(getCollectionList);

  const collectionList: CollectionType[] = data?.data || [];
  const currentCollection = collectionList.find((item) => item.is_selected);

  const handleDelete = async (collectionName: string) => {
    try {
      const res = await deleteCollection(collectionName);
      if (res.code === 200) {
        message.success(res.msg || 'Knowledge base deleted');
        runCollectionList();
      } else {
        message.error(res.msg || 'Deletion failed');
      }
    } catch (error) {
      message.error('Deletion failed');
    }
  };

  const handleSelect = async (collectionName: string) => {
    try {
      const res = await selectCollection({ collection_name: collectionName });
      if (res.code === 200) {
        message.success(res.msg || 'Knowledge base selected');
        runCollectionList();
      } else {
        message.error(res.msg || 'Selection failed');
      }
    } catch (error) {
      message.error('Selection failed');
    }
  };

  return (
    <div className="p-6 bg-[#f5f7fa] min-h-[calc(100vh-66px)]">
      <Card className="rounded-xl shadow-sm mb-4">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center text-[24px] font-bold mb-2">
              <DatabaseOutlined className="mr-2" />
              Tool Knowledge Base
            </div>
            <div className="text-gray-500">
              Create, select, and delete FAISS-backed tool knowledge bases used by workflow
              generation, evaluation, simulation, and regeneration.
            </div>
          </div>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setOpen(true)}
          >
            New knowledge base
          </Button>
        </div>
      </Card>

      <Card className="rounded-xl shadow-sm mb-4">
        <div className="font-semibold mb-2">Current knowledge base:</div>
        {currentCollection ? (
          <Tag color="blue" className="px-3 py-1">
            <CheckCircleOutlined className="mr-1" />
            {currentCollection.collection_name}
          </Tag>
        ) : (
          <span className="text-gray-400">No selected knowledge bases yet</span>
        )}
      </Card>

      <Card
        className="rounded-xl shadow-sm"
        title={<span className="font-semibold">Knowledge base list</span>}
        loading={loading}
      >
        {collectionList.length === 0 ? (
          <div className="text-gray-400 py-8 text-center">No knowledge base available</div>
        ) : (
          <div>
            {collectionList.map((item) => {
              const selected = item.is_selected === true;

              return (
                <div
                  key={item.collection_name}
                  className="flex items-center justify-between py-5 border-b border-gray-100 last:border-b-0"
                >
                  <div className="pr-4">
                    <div className="flex items-center mb-2">
                      <span className="font-semibold text-[16px] mr-2">
                        {item.collection_name}
                      </span>
                      {selected && <Tag color="blue">Selected</Tag>}
                      <Tag color="green">FAISS</Tag>
                      {typeof item.tool_count === 'number' && (
                        <Tag>{item.tool_count} tools</Tag>
                      )}
                    </div>

                    <div className="text-gray-600 mb-1">
                      {item.collection_describe || 'No description available.'}
                    </div>

                    {/* <div className="text-gray-400 text-sm">
                      Document:{item.collection_name}.pdf
                    </div> */}
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    {selected ? (
                      <Button type="primary" disabled>
                        Current
                      </Button>
                    ) : (
                      <Button onClick={() => handleSelect(item.collection_name)}>
                        Choose
                      </Button>
                    )}

                    <Popconfirm
                      title="Delete this knowledge base?"
                      okText="Confirm"
                      cancelText="Cancel"
                      onConfirm={() => handleDelete(item.collection_name)}
                    >
                      <Button
                        danger
                        icon={<DeleteOutlined />}
                      >
                        Delete
                      </Button>
                    </Popconfirm>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <KnowledgeBaseCreateModal
        open={open}
        onCancel={() => setOpen(false)}
        onSuccess={() => {
          setOpen(false);
          runCollectionList();
        }}
      />
    </div>
  );
};

export default KnowledgeBase;
