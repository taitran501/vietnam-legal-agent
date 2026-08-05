import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { Options } from 'react-markdown';

/**
 * Configure react-markdown with GFM and syntax highlighting
 */
export const markdownOptions: Options = {
  remarkPlugins: [remarkGfm],
  components: {
    // Code blocks with syntax highlighting
    code({ inline, className, children, ...props }: any) {
      const match = /language-(\w+)/.exec(className || '');
      return !inline && match ? (
        <SyntaxHighlighter
          style={oneDark as any}
          language={match[1]}
          PreTag="div"
          customStyle={{
            margin: '12px 0',
            borderRadius: '8px',
            fontSize: '13px',
          }}
          {...props}
        >
          {String(children).replace(/\n$/, '')}
        </SyntaxHighlighter>
      ) : (
        <code
          className={`${className} bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-sm font-mono`}
          {...props}
        >
          {children}
        </code>
      );
    },
    // Table styling
    table({ children }) {
      return (
        <div className="overflow-x-auto my-4">
          <table className="min-w-full border-collapse border border-gray-300 dark:border-gray-600">
            {children}
          </table>
        </div>
      );
    },
    th({ children }) {
      return (
        <th className="bg-gray-100 dark:bg-gray-700 border border-gray-300 dark:border-gray-600 px-4 py-2 text-left font-semibold">
          {children}
        </th>
      );
    },
    td({ children }) {
      return (
        <td className="border border-gray-300 dark:border-gray-600 px-4 py-2">
          {children}
        </td>
      );
    },
    // Link styling
    a({ children, href }) {
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-600 dark:text-blue-400 hover:underline"
        >
          {children}
        </a>
      );
    },
    // Blockquote styling
    blockquote({ children }) {
      return (
        <blockquote className="border-l-4 border-gray-300 dark:border-gray-600 pl-4 italic text-gray-600 dark:text-gray-400 my-2">
          {children}
        </blockquote>
      );
    },
    // List styling
    ul({ children }) {
      return <ul className="list-disc list-inside space-y-1 my-2">{children}</ul>;
    },
    ol({ children }) {
      return <ol className="list-decimal list-inside space-y-1 my-2">{children}</ol>;
    },
    // Heading styling
    h1({ children }) {
      return <h1 className="text-2xl font-bold mt-4 mb-2">{children}</h1>;
    },
    h2({ children }) {
      return <h2 className="text-xl font-bold mt-3 mb-2">{children}</h2>;
    },
    h3({ children }) {
      return <h3 className="text-lg font-semibold mt-3 mb-1">{children}</h3>;
    },
    // Paragraph styling
    p({ children }) {
      return <p className="mb-2 leading-relaxed">{children}</p>;
    },
  },
};

/**
 * Simple MarkdownRenderer component
 */
export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <ReactMarkdown {...(markdownOptions as any)}>
      {content}
    </ReactMarkdown>
  );
}
