import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { Components } from 'react-markdown';

type MarkdownNode = {
  type: string;
  value?: string;
  url?: string;
  children?: MarkdownNode[];
};

/** Convert plain citation markers without touching code or existing links. */
export function remarkCitationLinks() {
  return (tree: MarkdownNode) => {
    const visit = (node: MarkdownNode, parent?: MarkdownNode) => {
      if (!node.children) return;
      if (['code', 'inlineCode', 'link', 'linkReference'].includes(node.type)) return;

      node.children = node.children.flatMap((child) => {
        if (child.type !== 'text' || !child.value || ['link', 'linkReference'].includes(parent?.type || '')) {
          visit(child, node);
          return [child];
        }
        const parts: MarkdownNode[] = [];
        let cursor = 0;
        for (const match of child.value.matchAll(/\[(\d+)\]/g)) {
          const start = match.index ?? 0;
          if (start > cursor) parts.push({ type: 'text', value: child.value.slice(cursor, start) });
          parts.push({
            type: 'link',
            url: `#source-${match[1]}`,
            children: [{ type: 'text', value: match[0] }],
          });
          cursor = start + match[0].length;
        }
        if (cursor === 0) return [child];
        if (cursor < child.value.length) parts.push({ type: 'text', value: child.value.slice(cursor) });
        return parts;
      });
    };
    visit(tree);
  };
}

const markdownComponents = (onCitationClick?: (index: number) => void): Components => ({
    // Code blocks with syntax highlighting
    code({ className, children }) {
      const match = /language-(\w+)/.exec(className || '');
      return match ? (
        <SyntaxHighlighter
          style={oneDark}
          language={match[1]}
          PreTag="div"
          customStyle={{
            margin: '12px 0',
            borderRadius: '8px',
            fontSize: '13px',
          }}
        >
          {String(children).replace(/\n$/, '')}
        </SyntaxHighlighter>
      ) : (
        <code
          className={`${className || ''} rounded bg-[#f1f4f3] px-1.5 py-0.5 font-mono text-sm`}
        >
          {children}
        </code>
      );
    },
    // Table styling
    table({ children }) {
      return (
        <div className="my-4 overflow-x-auto">
          <table className="min-w-full border-collapse border border-[#d9e1df]">
            {children}
          </table>
        </div>
      );
    },
    th({ children }) {
      return (
        <th className="border border-[#d9e1df] bg-[#f1f4f3] px-4 py-2 text-left font-semibold text-[#172033]">
          {children}
        </th>
      );
    },
    td({ children }) {
      return (
        <td className="border border-[#d9e1df] px-4 py-2">
          {children}
        </td>
      );
    },
    // Link styling
    a({ children, href }) {
      const citation = href?.match(/^#source-(\d+)$/);
      if (citation) {
        const index = Number(citation[1]);
        return (
          <a
            className="font-semibold text-[#006a63] underline underline-offset-2"
            href={href}
            onClick={(event) => {
              event.preventDefault();
              onCitationClick?.(index);
            }}
          >
            {children}
          </a>
        );
      }
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-[#006a63] underline-offset-2 hover:underline"
        >
          {children}
        </a>
      );
    },
    // Blockquote styling
    blockquote({ children }) {
      return (
        <blockquote className="my-3 border-l-4 border-[#80d5cb] pl-4 italic text-[#53615e]">
          {children}
        </blockquote>
      );
    },
    // List styling
    ul({ children }) {
      return <ul className="my-2 list-disc space-y-1 pl-5">{children}</ul>;
    },
    ol({ children }) {
      return <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>;
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
});

/**
 * Simple MarkdownRenderer component
 */
export function MarkdownRenderer({ content, onCitationClick }: { content: string; onCitationClick?: (index: number) => void }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm, remarkCitationLinks]} components={markdownComponents(onCitationClick)}>
      {content}
    </ReactMarkdown>
  );
}
