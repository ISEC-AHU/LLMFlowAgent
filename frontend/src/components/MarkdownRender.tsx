/*
 * @Author: jinglongfang
 * @Date: 2024-05-21 15:38:36
 * @LastEditors: jinglongfang
 * @LastEditTime: 2024-05-22 09:52:03
 * @FilePath: \workflow-frontend\src\components\MarkdownRender.tsx
 * @Description:
 */

import { message } from 'antd';
import { marked } from 'marked';
import renderer from '@/utils/renderer';
import { useEffect, useRef } from 'react';

const MarkdownRenderer = ({ markdown }: { markdown: string }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleCopy = (event: Event) => {
      const button = event.currentTarget as HTMLElement;
      const targetId = button.getAttribute('data-target');
      if (targetId) {
        const codeBlock = document.getElementById(targetId)?.innerText;
        if (codeBlock) {
          navigator.clipboard
            .writeText(codeBlock)
            .then(() => {
              message.success('Copied to clipboard');
            })
            .catch(() => {
              message.error('Copy failed');
            });
        }
      }
    };

    // Scope button lookup to this component to avoid duplicate bindings across renderer instances.
    const buttons = container.querySelectorAll('.copy-code-btn');
    buttons.forEach((button) => {
      button.addEventListener('click', handleCopy);
    });

    return () => {
      buttons.forEach((button) => {
        button.removeEventListener('click', handleCopy);
      });
    };
  }, [markdown]);

  return (
    <div
      ref={containerRef}
      dangerouslySetInnerHTML={{ __html: marked(markdown, { renderer }) }}
    ></div>
  );
};

export default MarkdownRenderer;
