import { FC } from 'react';
import {
  ApartmentOutlined,
  DatabaseOutlined,
} from '@ant-design/icons';
import { useLocation, useNavigate } from 'react-router-dom';
import { EventEmitter } from 'ahooks/lib/useEventEmitter';

const Setting: FC<{ refresh$: EventEmitter<void> }> = function () {
  const navigate = useNavigate();
  const location = useLocation();

  const pathname = location.pathname;

  const isKnowledgeBaseActive = pathname === '/knowledge-base';

  const isWorkflowManageActive =
    pathname === '/workflow-manage' ||
    pathname === '/workflow/add' ||
    /^\/workflow\/[^/]+$/.test(pathname);
  

  const getMenuClassName = (active: boolean) => {
    return `
      flex items-center rounded-md px-3 py-3 cursor-pointer border transition-all
      ${
        active
          ? 'bg-blue-50 border-blue-200 text-blue-600'
          : 'bg-white border-gray-100 hover:bg-gray-100 text-black'
      }
    `;
  };

  return (
    <div className="p-4">
      <div className="mb-4">
        <div
          className={getMenuClassName(isKnowledgeBaseActive)}
          onClick={() => navigate('/knowledge-base')}
        >
          <DatabaseOutlined className="mr-2" />
          <span className="font-bold">Tool Knowledge Base</span>
        </div>
      </div>

      <div className="mb-4">
        <div
          className={getMenuClassName(isWorkflowManageActive)}
          onClick={() => navigate('/workflow-manage')}
        >
          <ApartmentOutlined className="mr-2" />
          <span className="font-bold">Workflow Design</span>
        </div>
      </div>

    </div>
  );
};

export default Setting;
