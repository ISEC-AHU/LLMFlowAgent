import React from 'react';
import { Button, Form, Input, Modal, Upload, message } from 'antd';
import { UploadOutlined } from '@ant-design/icons';
import { createCollection } from '@/api/api';

interface Props {
  open: boolean;
  onCancel: () => void;
  onSuccess: () => void;
}

interface FormValues {
  name: string;
  description?: string;
  file: any[];
}

const KnowledgeBaseCreateModal: React.FC<Props> = ({
  open,
  onCancel,
  onSuccess,
}) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = React.useState(false);

  const handleFinish = async (values: FormValues) => {
    try {
      const formData = new FormData();
      formData.append('collection_name', values.name);
      formData.append('collection_describe', values.description || '');
      formData.append('create_time', Date.now().toString());

      if (values.file?.[0]?.originFileObj) {
        formData.append('file', values.file[0].originFileObj);
      }

      setLoading(true);
      const res = await createCollection(formData);

      if (res.code === 200) {
        message.success(res.msg || 'Knowledge base created');
        form.resetFields();
        onSuccess();
      } else {
        message.error(res.msg || 'Failed to create knowledge base');
      }
    } catch (error) {
      message.error('Failed to create knowledge base');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      title="Create FAISS tool knowledge base"
      open={open}
      onCancel={onCancel}
      footer={null}
      destroyOnClose
      maskClosable={false}
      width={680}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={handleFinish}
        autoComplete="off"
      >
        <Form.Item
          label="Knowledge base name"
          name="name"
          rules={[{ required: true, message: 'Please enter the knowledge base name.' }]}
        >
          <Input placeholder="e.g. multimedia-tools-v1" />
        </Form.Item>

        <Form.Item label="Description" name="description">
          <Input.TextArea rows={4} placeholder="Describe this tool set." />
        </Form.Item>

        <Form.Item
          label="Tool/API JSON"
          name="file"
          valuePropName="fileList"
          getValueFromEvent={(e) => e?.fileList}
          rules={[{ required: true, message: 'Please upload a JSON file.' }]}
        >
          <Upload
            name="file"
            accept=".json,application/json"
            multiple={false}
            maxCount={1}
            beforeUpload={() => false}
          >
            <Button icon={<UploadOutlined />}>Select JSON</Button>
          </Upload>
        </Form.Item>

        <div className="text-gray-400 text-sm mb-4">
          The backend will normalize the uploaded tools and build a FAISS index for retrieval.
        </div>

        <div className="flex justify-end gap-3">
          <Button onClick={onCancel}>Cancel</Button>
          <Button type="primary" htmlType="submit" loading={loading}>
            Create
          </Button>
        </div>
      </Form>
    </Modal>
  );
};

export default KnowledgeBaseCreateModal;
