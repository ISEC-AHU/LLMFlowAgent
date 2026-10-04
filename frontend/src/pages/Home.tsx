/*
 * @Author: jinglongfang
 * @Date: 2024-05-16 16:35:33
 * @LastEditors: jinglong fang
 * @LastEditTime: 2024-06-18 14:32:52
 * @FilePath: \workflow-frontend\src\pages\Home.tsx
 * @Description:
 */

import { Layout, theme } from 'antd';
import { Route, Routes, useNavigate } from 'react-router-dom';

import ExternalLinkIcon from '@/assets/external-link.svg?react';
import ReadmeViewer from '@/components/MarkDownViewer/MardkDownViewer';
import Setting from './setting/Setting';
import { UserOutlined } from '@ant-design/icons';
import Workflow from './workflow/Workflow';
import { useEventEmitter } from 'ahooks';
import KnowledgeBase from './knowledgeBase/KnowledgeBase';
import WorkflowManage from './workflowManage/WorkflowManage';

const { Header, Content } = Layout;

function Home() {
  const {
    token: { colorPrimary },
  } = theme.useToken();

  const refresh$ = useEventEmitter();
  const navigate = useNavigate();

  return (
    <Layout className="min-h-screen">
      <Header
        className="shadow flex items-center justify-between px-4 bg-white"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 100,
          width: '100%',
        }}
      >
        <div className="flex items-center">
          <div
            className="font-bold text-2xl cursor-pointer flex items-center"
            onClick={() => navigate('/')}
          >
            <img
              src="/agent.svg"
              alt="LLMFlowAgent logo"
              style={{ width: 40, height: 40, objectFit: 'contain' }}
            />
            <span className="ml-2">LLMFlowAgent</span>
          </div>

          <a
            target="blank"
            href="https://github.com/ISEC-AHU/EdgeWorkflow"
            className="ml-12 flex items-center"
          >
            <span className="mr-1">EdgeWorkflow</span>
            <ExternalLinkIcon
              style={{ '--hover-color': colorPrimary } as React.CSSProperties}
            />
          </a>
        </div>

        <div className="flex items-center">
          <UserOutlined className="cursor-pointer" style={{ fontSize: 20 }} />
        </div>
      </Header>

      <Content
        style={{
          width: '100%',
          maxWidth: '100%',
          overflowX: 'clip',
          background: '#f5f7fa',
        }}
      >
        <div className="flex w-full min-w-0 max-w-full" style={{ overflowX: 'clip' }}>
          <div
            className="w-[290px] shrink-0 bg-white border-r shadow-sm overflow-y-auto"
            style={{
              height: 'calc(100vh - 64px)',
              position: 'sticky',
              top: 64,
            }}
          >
            <Setting refresh$={refresh$} />
          </div>

            <div
              className="min-w-0 max-w-full flex-1 box-border"
              style={{
                minHeight: 'calc(100vh - 64px)',
                overflowX: 'clip',
              }}
            >
              <div
                className="w-full min-w-0 max-w-full px-6"
                style={{ overflowX: 'clip' }}
              >
              <Routes>
                <Route path="/" element={<ReadmeViewer />} />
                <Route path="knowledge-base" element={<KnowledgeBase />} />
                <Route path="workflow-manage" element={<WorkflowManage />} />
                <Route
                  path="workflow/:workflowId"
                  element={<Workflow refresh$={refresh$} />}
                />
                <Route
                  path="workflow/add"
                  element={<Workflow refresh$={refresh$} />}
                />
              </Routes>
            </div>
          </div>
        </div>
      </Content>
    </Layout>
  );
}

export default Home;
