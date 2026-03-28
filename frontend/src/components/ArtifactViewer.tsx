'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FileText,
  FileJson,
  FileCode,
  FileSpreadsheet,
  File,
  Download,
  Copy,
  Check,
  ChevronDown,
  Image,
  ExternalLink,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { type Artifact } from '@/lib/types';
import { cn, formatTimestamp } from '@/lib/utils';

// ============================================================
// File type helpers
// ============================================================

const TYPE_CONFIG: Record<Artifact['type'], {
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bg: string;
  label: string;
}> = {
  text: { icon: FileText, color: 'text-accent', bg: 'bg-accent/10', label: 'Text' },
  json: { icon: FileJson, color: 'text-warning', bg: 'bg-warning/10', label: 'JSON' },
  csv: { icon: FileSpreadsheet, color: 'text-success', bg: 'bg-success/10', label: 'CSV' },
  code: { icon: FileCode, color: 'text-primary', bg: 'bg-primary/10', label: 'Code' },
  markdown: { icon: FileText, color: 'text-accent', bg: 'bg-accent/10', label: 'Markdown' },
  image: { icon: Image, color: 'text-warning', bg: 'bg-warning/10', label: 'Image' },
  binary: { icon: File, color: 'text-text-muted', bg: 'bg-surface', label: 'Binary' },
};

function formatBytes(bytes?: number): string {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

// ============================================================
// Content renderers
// ============================================================

function TextPreview({ content }: { content: string }) {
  return (
    <pre className="text-xs text-text-muted font-mono leading-relaxed overflow-auto whitespace-pre-wrap break-words">
      {content}
    </pre>
  );
}

function JsonPreview({ content }: { content: string }) {
  let formatted = content;
  try {
    formatted = JSON.stringify(JSON.parse(content), null, 2);
  } catch {
    // use raw
  }
  return (
    <pre className="text-xs text-text-muted font-mono leading-relaxed overflow-auto">
      {formatted}
    </pre>
  );
}

function CsvPreview({ content }: { content: string }) {
  const lines = content.trim().split('\n');
  if (lines.length === 0) return <TextPreview content={content} />;

  const headers = lines[0].split(',');
  const rows = lines.slice(1).map((l) => l.split(','));

  return (
    <div className="overflow-auto">
      <table className="text-xs w-full border-collapse">
        <thead>
          <tr className="bg-surface-overlay">
            {headers.map((h, i) => (
              <th key={i} className="text-left p-2 font-mono font-semibold text-accent border border-border">
                {h.trim()}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 20).map((row, ri) => (
            <tr key={ri} className="even:bg-surface">
              {row.map((cell, ci) => (
                <td key={ci} className="p-2 font-mono text-text-muted border border-border">
                  {cell.trim()}
                </td>
              ))}
            </tr>
          ))}
          {rows.length > 20 && (
            <tr>
              <td colSpan={headers.length} className="p-2 text-center text-text-muted italic">
                …{rows.length - 20} more rows
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function MarkdownPreview({ content }: { content: string }) {
  return (
    <div className="prose prose-invert prose-sm max-w-none text-text-muted [&_code]:font-mono [&_code]:text-accent [&_pre]:bg-black/30 [&_a]:text-primary">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}

function ArtifactContent({ artifact }: { artifact: Artifact }) {
  switch (artifact.type) {
    case 'json': return <JsonPreview content={artifact.content} />;
    case 'csv': return <CsvPreview content={artifact.content} />;
    case 'markdown': return <MarkdownPreview content={artifact.content} />;
    case 'code': return <TextPreview content={artifact.content} />;
    default: return <TextPreview content={artifact.content} />;
  }
}

// ============================================================
// Individual artifact card
// ============================================================

function ArtifactCard({ artifact }: { artifact: Artifact }) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const cfg = TYPE_CONFIG[artifact.type] || TYPE_CONFIG.text;
  const Icon = cfg.icon;

  async function handleCopy() {
    await navigator.clipboard.writeText(artifact.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function handleDownload() {
    const ext = {
      text: 'txt',
      json: 'json',
      csv: 'csv',
      code: 'py',
      markdown: 'md',
      image: 'png',
      binary: 'bin',
    }[artifact.type] || 'txt';

    const blob = new Blob([artifact.content], { type: artifact.mimeType || 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = artifact.name || `artifact.${ext}`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="border border-border rounded-xl overflow-hidden"
    >
      {/* Header */}
      <div
        className="flex items-center gap-3 p-3 cursor-pointer hover:bg-surface-elevated/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className={cn('w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0', cfg.bg)}>
          <Icon className={cn('w-4 h-4', cfg.color)} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-text truncate">{artifact.name}</p>
            <span className={cn('text-xs px-1.5 py-0.5 rounded font-medium', cfg.bg, cfg.color)}>
              {cfg.label}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-0.5 text-xs text-text-muted">
            {artifact.sizeBytes && <span>{formatBytes(artifact.sizeBytes)}</span>}
            <span>{formatTimestamp(artifact.createdAt)}</span>
            <span>{artifact.content.split('\n').length} lines</span>
          </div>
        </div>

        <div className="flex items-center gap-1.5 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
          <button
            onClick={handleCopy}
            className="p-1.5 rounded-lg text-text-muted hover:text-text hover:bg-surface-overlay transition-colors"
            title="Copy to clipboard"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
          <button
            onClick={handleDownload}
            className="p-1.5 rounded-lg text-text-muted hover:text-text hover:bg-surface-overlay transition-colors"
            title="Download"
          >
            <Download className="w-3.5 h-3.5" />
          </button>
          <ChevronDown
            className={cn('w-4 h-4 text-text-muted transition-transform ml-1', expanded && 'rotate-180')}
            onClick={() => setExpanded(!expanded)}
          />
        </div>
      </div>

      {/* Content */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="border-t border-border p-4 max-h-96 overflow-y-auto bg-black/20">
              <ArtifactContent artifact={artifact} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ============================================================
// Main component
// ============================================================

interface ArtifactViewerProps {
  artifacts: Artifact[];
}

export function ArtifactViewer({ artifacts }: ArtifactViewerProps) {
  if (artifacts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-32 gap-3 text-text-muted">
        <File className="w-8 h-8 opacity-30" />
        <p className="text-xs">No artifacts produced yet.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-text">Artifacts</span>
          <span className="text-xs text-text-muted bg-surface-overlay px-2 py-0.5 rounded-full">
            {artifacts.length}
          </span>
        </div>
        <a
          href="#"
          className="text-xs text-primary hover:text-accent flex items-center gap-1 transition-colors"
        >
          <ExternalLink className="w-3 h-3" />
          Export all
        </a>
      </div>

      <div className="flex flex-col gap-2">
        {artifacts.map((artifact) => (
          <ArtifactCard key={artifact.id} artifact={artifact} />
        ))}
      </div>
    </div>
  );
}
