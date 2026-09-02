'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Shield } from 'lucide-react';
import api from '@/lib/api';

export default function ReportsPage() {
  const [traceId, setTraceId] = useState('');
  const [format, setFormat] = useState<'json' | 'pdf'>('json');
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const generateMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post(`/traces/${traceId}/reports`, { format });
      return res.data;
    },
    onSuccess: (data) => { setResult(data); setError(null); },
    onError: (err: any) => { setError(err.response?.data?.detail ?? 'Failed to generate report'); setResult(null); },
  });

  return (
    <main className="min-h-screen bg-gray-900 text-white">
      {/* Header */}
      <header className="border-b border-gray-700 bg-gray-800/80 px-6 py-4 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-3">
            <Shield className="h-6 w-6 text-blue-400" />
            <h1 className="text-xl font-bold tracking-tight text-white">
              VASP Attribution Engine
            </h1>
          </div>

          <nav className="flex items-center gap-1 bg-gray-900/60 p-1 rounded-lg border border-gray-750">
            <Link
              href="/dashboard"
              className="px-3 py-1.5 text-sm font-medium rounded-md text-gray-300 hover:text-white hover:bg-gray-800 transition"
            >
              Dashboard
            </Link>
            <Link
              href="/cases"
              className="px-3 py-1.5 text-sm font-medium rounded-md text-gray-300 hover:text-white hover:bg-gray-800 transition"
            >
              Cases
            </Link>
            <Link
              href="/reports"
              className="px-3 py-1.5 text-sm font-medium rounded-md bg-blue-600 text-white transition shadow-sm"
            >
              Reports
            </Link>
            <Link
              href="/admin/vasps"
              className="px-3 py-1.5 text-sm font-medium rounded-md text-gray-300 hover:text-white hover:bg-gray-800 transition"
            >
              Admin
            </Link>
          </nav>
        </div>
      </header>

      <div className="mx-auto max-w-3xl px-6 py-8 space-y-8">
        <h1 className="text-2xl font-bold">Investigation Reports</h1>

        {/* Generate Report */}
        <section className="rounded-xl border border-gray-700 bg-gray-800 p-6 space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-gray-400">Generate Report</h2>

          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1.5">Trace ID</label>
              <input
                type="text"
                value={traceId}
                onChange={e => setTraceId(e.target.value)}
                placeholder="UUID of the trace job"
                className="w-full rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm font-mono text-white placeholder-gray-600 focus:border-blue-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-300 mb-1.5">Format</label>
              <select
                value={format}
                onChange={e => setFormat(e.target.value as 'json' | 'pdf')}
                className="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
              >
                <option value="json">JSON</option>
                <option value="pdf">PDF</option>
              </select>
            </div>

            {error && (
              <div className="rounded-lg border border-red-700 bg-red-900/30 px-4 py-3 text-sm text-red-300">{error}</div>
            )}

            <button
              onClick={() => generateMutation.mutate()}
              disabled={generateMutation.isPending || !traceId.trim()}
              className="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {generateMutation.isPending ? 'Generating…' : 'Generate Report'}
            </button>
          </div>
        </section>

        {/* Result */}
        {result && (
          <section className="rounded-xl border border-green-700 bg-green-900/20 p-6 space-y-3">
            <h2 className="text-sm font-semibold text-green-400">Report Generated</h2>
            <div className="text-sm space-y-1 text-gray-300">
              <p><span className="text-gray-500">Report ID:</span> <span className="font-mono">{result.report_id}</span></p>
              <p><span className="text-gray-500">Status:</span> {result.status}</p>
              <p><span className="text-gray-500">Format:</span> {result.format}</p>
              <p><span className="text-gray-500">Hash:</span> <span className="font-mono text-xs break-all">{result.content_hash}</span></p>
            </div>
            {result.json_payload && (
              <button
                onClick={() => {
                  const blob = new Blob([JSON.stringify(result.json_payload, null, 2)], { type: 'application/json' });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement('a'); a.href = url; a.download = `report-${result.report_id}.json`; a.click();
                }}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
              >
                Download JSON
              </button>
            )}
          </section>
        )}
      </div>
    </main>
  );
}
