import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders LLM-generated markdown (the /ask answer) with design-system
 * styling. Tailwind preflight strips all element margins, so every block
 * element needs explicit spacing here.
 */
export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ node, ...props }) => <p className="mb-3 last:mb-0" {...props} />,
        ul: ({ node, ...props }) => (
          <ul className="mb-3 list-disc space-y-1.5 pl-5 last:mb-0" {...props} />
        ),
        ol: ({ node, ...props }) => (
          <ol className="mb-3 list-decimal space-y-1.5 pl-5 last:mb-0" {...props} />
        ),
        strong: ({ node, ...props }) => <strong className="font-semibold" {...props} />,
        // in-page hash links are citation markers ([n] -> #source-n); style
        // them like the chips on the source cards they jump to
        a: ({ node, href, ...props }) =>
          href?.startsWith("#") ? (
            <a
              href={href}
              className="mx-px rounded-md bg-card px-1 font-mono text-[12px] font-medium text-body hover:bg-strong"
              {...props}
            />
          ) : (
            <a
              href={href}
              className="font-semibold text-ink underline underline-offset-2"
              target="_blank"
              rel="noopener noreferrer"
              {...props}
            />
          ),
        h1: ({ node, ...props }) => (
          <h3 className="mb-2 mt-5 text-[16px] font-semibold first:mt-0" {...props} />
        ),
        h2: ({ node, ...props }) => (
          <h3 className="mb-2 mt-5 text-[16px] font-semibold first:mt-0" {...props} />
        ),
        h3: ({ node, ...props }) => (
          <h3 className="mb-2 mt-4 text-[15px] font-semibold first:mt-0" {...props} />
        ),
        code: ({ node, ...props }) => (
          <code className="rounded bg-card px-1 py-0.5 font-mono text-[13px]" {...props} />
        ),
        blockquote: ({ node, ...props }) => (
          <blockquote className="mb-3 border-l-2 border-hairline pl-3 text-muted" {...props} />
        ),
        hr: ({ node, ...props }) => <hr className="my-4 border-hairline" {...props} />,
        table: ({ node, ...props }) => (
          <div className="mb-3 overflow-x-auto">
            <table className="w-full border-collapse text-sm" {...props} />
          </div>
        ),
        th: ({ node, ...props }) => (
          <th className="border-b border-hairline px-2 py-1.5 text-left font-semibold" {...props} />
        ),
        td: ({ node, ...props }) => (
          <td className="border-b border-hairline-soft px-2 py-1.5 align-top" {...props} />
        ),
      }}
    >
      {children}
    </ReactMarkdown>
  );
}
