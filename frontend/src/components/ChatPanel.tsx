'use client';

import React, { useState, useRef, useEffect } from 'react';
import { Send, Loader2, MessageSquare, Bot, User } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { cn } from '@/lib/utils';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  model?: string;
  timestamp: string;
}

async function sendChat(message: string, history: Message[]): Promise<{ response: string; model: string }> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message,
      history: history.map(m => ({ role: m.role, content: m.content })),
    }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function handleSend() {
    const msg = input.trim();
    if (!msg || loading) return;

    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: msg,
      timestamp: new Date().toISOString(),
    };

    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);
    setError(null);

    try {
      const { response, model } = await sendChat(msg, messages);
      const assistantMsg: Message = {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: response,
        model,
        timestamp: new Date().toISOString(),
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Request failed');
    } finally {
      setLoading(false);
      textareaRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold text-text">Chat</span>
        </div>
        <p className="text-xs text-text-muted mt-0.5">Talk directly to the AI</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3">
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted">
            <Bot className="w-10 h-10 opacity-20" />
            <p className="text-xs text-center">Ask anything. The AI can help with<br />research, writing, code, and more.</p>
          </div>
        )}
        {messages.map(msg => (
          <div key={msg.id} className={cn('flex gap-2', msg.role === 'user' ? 'flex-row-reverse' : 'flex-row')}>
            <div className={cn(
              'w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5',
              msg.role === 'user' ? 'bg-primary/20' : 'bg-surface-overlay'
            )}>
              {msg.role === 'user'
                ? <User className="w-3 h-3 text-primary" />
                : <Bot className="w-3 h-3 text-accent" />}
            </div>
            <div className={cn(
              'max-w-[80%] rounded-xl px-3 py-2 text-xs',
              msg.role === 'user'
                ? 'bg-primary/15 text-text rounded-tr-none'
                : 'bg-surface-elevated text-text-muted rounded-tl-none'
            )}>
              {msg.role === 'assistant' ? (
                <div className="prose prose-invert prose-xs max-w-none [&_code]:text-accent [&_code]:bg-black/30 [&_code]:px-1 [&_code]:rounded [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1">
                  <ReactMarkdown>{msg.content}</ReactMarkdown>
                </div>
              ) : (
                <p className="whitespace-pre-wrap">{msg.content}</p>
              )}
              {msg.model && (
                <p className="text-[10px] text-text-muted opacity-50 mt-1 font-mono">{msg.model}</p>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex gap-2">
            <div className="w-6 h-6 rounded-full bg-surface-overlay flex items-center justify-center flex-shrink-0">
              <Bot className="w-3 h-3 text-accent" />
            </div>
            <div className="bg-surface-elevated rounded-xl rounded-tl-none px-3 py-2">
              <Loader2 className="w-3 h-3 animate-spin text-text-muted" />
            </div>
          </div>
        )}
        {error && (
          <p className="text-xs text-error bg-error/10 rounded-lg px-3 py-2">{error}</p>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex-shrink-0 p-3 border-t border-border">
        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything… (Enter to send)"
            rows={1}
            className={cn(
              'flex-1 resize-none bg-surface-elevated border border-border rounded-xl px-3 py-2',
              'text-xs text-text placeholder:text-text-muted',
              'focus:outline-none focus:border-primary/50 transition-colors',
              'min-h-[36px] max-h-24 overflow-y-auto'
            )}
            style={{ fieldSizing: 'content' } as React.CSSProperties}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            className={cn(
              'flex-shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all',
              input.trim() && !loading
                ? 'bg-primary hover:bg-primary-hover text-white shadow-glow-sm'
                : 'bg-surface-elevated text-text-muted cursor-not-allowed'
            )}
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>
    </div>
  );
}
