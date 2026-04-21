import { useState } from "react";

interface CopyButtonProps {
  text: string;
  className?: string;
}

export default function CopyButton({ text, className = "" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      onClick={handleCopy}
      className={`text-xs px-2 py-1 rounded border border-border hover:border-fg-muted text-fg-secondary hover:text-fg-primary transition-colors ${className}`}
    >
      {copied ? "✓ Copied" : "Copy"}
    </button>
  );
}
