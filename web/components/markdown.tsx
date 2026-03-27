import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert prose-headings:font-serif prose-headings:tracking-tight prose-a:text-primary prose-a:underline prose-a:underline-offset-2">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  );
}
