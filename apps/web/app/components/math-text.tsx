import katex from "katex";

export function MathText({ text }: { text: string }) {
  const parts = text.split(/(\$[^$]+\$)/g).filter(Boolean);
  return <>{parts.map((part, index) => {
    if (!part.startsWith("$") || !part.endsWith("$")) return <span key={index}>{part}</span>;
    const html = katex.renderToString(part.slice(1, -1), {
      throwOnError: false,
      strict: "warn",
      trust: false,
      output: "htmlAndMathml",
    });
    return <span className="inline-math" key={index} dangerouslySetInnerHTML={{ __html: html }} />;
  })}</>;
}
