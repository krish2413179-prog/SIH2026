'use client';

/**
 * Admin panel — VASPs, typology definitions, and audit log management.
 * Requirements: 7.1, 7.2, 7.4, 9.5, 14.4
 */

import { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '@/lib/api';
import { RoleGuard } from '@/lib/roleGuard';

type Tab = 'vasps' | 'typology' | 'audit';

const VASP_CATEGORIES = ['CEX', 'DEX', 'mixer', 'bridge', 'darknet', 'other'];

function VASPsTab() {
  const qc = useQueryClient();
  const [name, setName] = useState('');
  const [category, setCategory] = useState('CEX');
  const [jurisdiction, setJurisdiction] = useState('IN');
  const [status, setStatus] = useState('active');
  const [csvErrors, setCsvErrors] = useState<any[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const { data: vasps, isLoading } = useQuery({
    queryKey: ['admin', 'vasps'],
    queryFn: async () => (await api.get('/admin/vasps')).data,
  });

  const createMutation = useMutation({
    mutationFn: async () => {
      await api.post('/admin/vasps', { name, category, jurisdiction, operational_status: status });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['admin', 'vasps'] }); setName(''); },
  });

  const importMutation = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData(); form.append('file', file);
      const res = await api.post('/admin/vasps/import', form, { headers: { 'Content-Type': 'multipart/form-data' } });
      return res.data;
    },
    onSuccess: (data) => {
      setCsvErrors(data.errors || []);
      qc.invalidateQueries({ queryKey: ['admin', 'vasps'] });
    },
  });

  return (
    <div className="space-y-6">
      {/* Add VASP form */}
      <div className="rounded-xl border border-gray-700 bg-gray-800 p-5">
        <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">Add VASP</h3>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <input value={name} onChange={e => setName(e.target.value)} placeholder="VASP name"
            className="col-span-2 rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" />
          <select value={category} onChange={e => setCategory(e.target.value)}
            className="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none">
            {VASP_CATEGORIES.map(c => <option key={c}>{c}</option>)}
          </select>
          <input value={jurisdiction} onChange={e => setJurisdiction(e.target.value)} placeholder="IN" maxLength={2}
            className="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" />
        </div>
        <div className="mt-3 flex gap-3">
          <button onClick={() => createMutation.mutate()} disabled={createMutation.isPending || !name}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">
            {createMutation.isPending ? 'Adding…' : 'Add VASP'}
          </button>
          <button onClick={() => fileRef.current?.click()}
            className="rounded-lg border border-gray-600 px-4 py-2 text-sm text-gray-300 hover:border-gray-400 transition-colors">
            Import CSV
          </button>
          <input ref={fileRef} type="file" accept=".csv" className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) importMutation.mutate(f); }} />
        </div>
        {csvErrors.length > 0 && (
          <div className="mt-3 rounded-lg border border-red-700 bg-red-900/30 p-3 text-xs space-y-1 max-h-32 overflow-auto">
            {csvErrors.map((e, i) => <div key={i} className="text-red-300">Row {e.row ?? i+1}: {e.detail ?? JSON.stringify(e)}</div>)}
          </div>
        )}
      </div>

      {/* VASPs table */}
      <div className="rounded-xl border border-gray-700 overflow-hidden">
        <table className="w-full text-sm text-left">
          <thead className="bg-gray-800 border-b border-gray-700">
            <tr>
              {['Name', 'Category', 'Jurisdiction', 'Status', 'Updated'].map(h => (
                <th key={h} className="px-4 py-3 text-xs text-gray-400 font-semibold uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700 bg-gray-900">
            {isLoading ? (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-500">Loading…</td></tr>
            ) : (vasps?.items ?? []).map((v: any) => (
              <tr key={v.id} className="hover:bg-gray-800/50">
                <td className="px-4 py-3 font-medium text-white">{v.name}</td>
                <td className="px-4 py-3 text-gray-400">{v.category}</td>
                <td className="px-4 py-3 text-gray-400">{v.jurisdiction}</td>
                <td className="px-4 py-3">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${v.operational_status === 'active' ? 'bg-green-700 text-green-100' : v.operational_status === 'sanctioned' ? 'bg-red-700 text-red-100' : 'bg-gray-600 text-gray-300'}`}>
                    {v.operational_status}
                  </span>
                </td>
                <td className="px-4 py-3 text-xs text-gray-500">{v.last_updated ? new Date(v.last_updated).toLocaleDateString() : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TypologyTab() {
  const qc = useQueryClient();
  const [typologyName, setTypologyName] = useState('');
  const [definitionJson, setDefinitionJson] = useState('{}');
  const [uploadError, setUploadError] = useState<string | null>(null);

  const uploadMutation = useMutation({
    mutationFn: async () => {
      const def = JSON.parse(definitionJson);
      const res = await api.post('/admin/typology-definitions', { typology_name: typologyName, definition_json: def });
      return res.data;
    },
    onSuccess: () => { setTypologyName(''); setDefinitionJson('{}'); setUploadError(null); },
    onError: (e: any) => setUploadError(e.response?.data?.detail ?? 'Upload failed'),
  });

  return (
    <div className="rounded-xl border border-gray-700 bg-gray-800 p-5 space-y-4">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-400">Upload Typology Definition</h3>
      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">Typology Name</label>
          <input value={typologyName} onChange={e => setTypologyName(e.target.value)} placeholder="e.g. layering"
            className="w-full rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">Definition JSON</label>
          <textarea value={definitionJson} onChange={e => setDefinitionJson(e.target.value)} rows={8}
            className="w-full rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-sm font-mono text-white focus:border-blue-500 focus:outline-none resize-none" />
        </div>
        {uploadError && <p className="text-sm text-red-400">{uploadError}</p>}
        <button onClick={() => uploadMutation.mutate()} disabled={uploadMutation.isPending || !typologyName.trim()}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">
          {uploadMutation.isPending ? 'Uploading…' : 'Upload Definition'}
        </button>
      </div>
    </div>
  );
}

function AuditTab() {
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [exportFormat, setExportFormat] = useState<'json' | 'csv'>('json');

  const { data: logs, isLoading, refetch } = useQuery({
    queryKey: ['audit', fromDate, toDate],
    queryFn: async () => {
      const params: any = { format: 'json', page: 1, page_size: 50 };
      if (fromDate) params.from_date = fromDate;
      if (toDate) params.to_date = toDate;
      const res = await api.get('/admin/audit-logs/export', { params });
      return res.data;
    },
  });

  const handleExport = async () => {
    const params: any = { format: exportFormat };
    if (fromDate) params.from_date = fromDate;
    if (toDate) params.to_date = toDate;
    const res = await api.get('/admin/audit-logs/export', { params, responseType: 'blob' });
    const url = URL.createObjectURL(res.data);
    const a = document.createElement('a'); a.href = url; a.download = `audit-logs.${exportFormat}`; a.click();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">From</label>
          <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
            className="rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none [color-scheme:dark]" />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">To</label>
          <input type="date" value={toDate} onChange={e => setToDate(e.target.value)}
            className="rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none [color-scheme:dark]" />
        </div>
        <button onClick={() => refetch()} className="rounded-lg border border-gray-600 px-4 py-2 text-sm text-gray-300 hover:border-gray-400 transition-colors">Filter</button>
        <select value={exportFormat} onChange={e => setExportFormat(e.target.value as any)}
          className="rounded-lg border border-gray-600 bg-gray-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none">
          <option value="json">JSON</option>
          <option value="csv">CSV</option>
        </select>
        <button onClick={handleExport} className="rounded-lg bg-gray-700 px-4 py-2 text-sm text-gray-200 hover:bg-gray-600 transition-colors">Export</button>
      </div>
      <div className="rounded-xl border border-gray-700 overflow-hidden">
        <table className="w-full text-xs text-left">
          <thead className="bg-gray-800 border-b border-gray-700">
            <tr>
              {['Timestamp', 'Action', 'Resource', 'Actor', 'IP'].map(h => (
                <th key={h} className="px-4 py-3 text-gray-400 font-semibold uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-700 bg-gray-900">
            {isLoading ? (
              <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-500">Loading…</td></tr>
            ) : (Array.isArray(logs) ? logs : logs?.items ?? []).slice(0, 50).map((l: any, i: number) => (
              <tr key={i} className="hover:bg-gray-800/50">
                <td className="px-4 py-2 text-gray-400 whitespace-nowrap">{l.timestamp ? new Date(l.timestamp).toLocaleString() : '—'}</td>
                <td className="px-4 py-2 font-medium text-white">{l.action_type}</td>
                <td className="px-4 py-2 text-gray-400">{l.resource_type}{l.resource_id ? ` (${String(l.resource_id).slice(0,8)})` : ''}</td>
                <td className="px-4 py-2 font-mono text-gray-500">{l.actor_user_id ? String(l.actor_user_id).slice(0,8) : 'system'}</td>
                <td className="px-4 py-2 text-gray-500">{l.source_ip}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function AdminPage() {
  const [tab, setTab] = useState<Tab>('vasps');

  return (
    <RoleGuard requiredRole="admin">
      <main className="min-h-screen bg-gray-900 text-white px-6 py-8">
        <div className="mx-auto max-w-7xl space-y-6">
          <h1 className="text-2xl font-bold">Admin Panel</h1>
          {/* Tabs */}
          <div className="flex gap-1 border-b border-gray-700">
            {(['vasps', 'typology', 'audit'] as Tab[]).map(t => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-5 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${tab === t ? 'border-blue-500 text-blue-400' : 'border-transparent text-gray-400 hover:text-white'}`}>
                {t === 'vasps' ? 'VASPs' : t === 'typology' ? 'Typology Defs' : 'Audit Logs'}
              </button>
            ))}
          </div>
          {tab === 'vasps' && <VASPsTab />}
          {tab === 'typology' && <TypologyTab />}
          {tab === 'audit' && <AuditTab />}
        </div>
      </main>
    </RoleGuard>
  );
}
