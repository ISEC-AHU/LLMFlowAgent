/*
 * @Author: jinglong fang
 * @Date: 2024-05-22 09:48:17
 * @LastEditors: jinglong fang
 * @LastEditTime: 2024-06-21 13:34:05
 * @FilePath: \workflow-frontend\src\components\MarkDownViewer\MardkDownViewer.tsx
 * @Description:
 */

import 'highlight.js/styles/atom-one-light.css';
import './markdown-styles.css';

import Markdown from 'react-markdown';
import type { Components } from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import readmeMarkdown from '../../../../README.md?raw';

const ReadmeViewer = () => {
  const components: Components = {
    h1: ({ node: _node, ...props }) => <h1 className="custom-h1" {...props} />,
    h2: ({ node: _node, ...props }) => <h2 className="custom-h2" {...props} />,
    p: ({ node: _node, ...props }) => <p className="custom-paragraph" {...props} />,
    code: ({ node: _node, ...props }) => <code className="custom-code" {...props} />,
    li: ({ node: _node, ...props }) => <li className="custom-list-item" {...props} />,
    ul: ({ node: _node, ...props }) => <ul className="custom-list" {...props} />,
    ol: ({ node: _node, ...props }) => (
      <ol className="custom-ordered-list" {...props} />
    ),
  };

  return (
    <div className="markdown-content">
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        children={readmeMarkdown}
        components={components}
      />
    </div>
  );
};

export default ReadmeViewer;
