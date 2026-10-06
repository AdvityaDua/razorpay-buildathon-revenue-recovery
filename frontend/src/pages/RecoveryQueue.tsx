/**
 * Recovery Queue page — PRD §11.1
 *
 * Table of failure records from the batch run.
 * Per record: diagnosis (root_cause + confidence), evidence summary,
 * action taken or STOP reason, outcome.
 * Filter/sort by diagnosis class or action type.
 */

import { useState, useMemo } from 'react';
import { useRecords, type AuditEntry } from '../api/hooks';
import { ChevronDown, ChevronRight, Shield, Search } from 'lucide-react';

const ROOT_CAUSE_LABELS: Record<string, string> = {
  insufficient_funds: 'Insufficient Funds',
  mandate_expired: 'Mandate Expired',
  afa_required: 'AFA Required',
  customer_cancelled: 'Customer Cancelled',
  genuine_decline: 'Genuine Decline',
  ambiguous: 'Ambiguous',
};

const ACTION_LABELS: Record<string, string> = {
  retry: 'Retry Payment',
  send_reminder: 'Send Reminder',
  send_reauth_link: 'Re-auth Link',
  send_stepup_auth: 'Step-up Auth',
  send_alternate_payment_prompt: 'Alt Payment',
  hold_for_review: 'Hold for Review',
  stop: 'Stop',
};

const OUTCOME_CONFIG: Record<string, { label: string; variant: string }> = {
  recovered: { label: 'Recovered', variant: 'success' },
  partial_recovery: { label: 'Partial', variant: 'warning' },
  correctly_stopped: { label: 'Correctly Stopped', variant: 'success' },
  held_for_review: { label: 'Held', variant: 'info' },
  unnecessary_action: { label: 'Unnecessary', variant: 'warning' },
  missed_recovery: { label: 'Missed', variant: 'danger' },
  no_action: { label: 'No Action', variant: 'neutral' },
};

function getConfidenceLevel(confidence: number) {
  if (confidence >= 0.8) return 'high';
  if (confidence >= 0.5) return 'medium';
  return 'low';
}

function formatCurrency(amount: number) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount);
}

function RecordRow({ entry, isExpanded, onToggle }: {
  entry: AuditEntry;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const diagnosis = entry.diagnosis;
  const rootCause = diagnosis?.root_cause || 'error';
  const confidence = diagnosis?.confidence ?? 0;
  const action = entry.allowed_action?.action || 'none';
  const outcome = entry.simulated_outcome || 'no_action';
  const outcomeConfig = OUTCOME_CONFIG[outcome] || { label: outcome, variant: 'neutral' };
  const wasOverridden = entry.allowed_action?.was_overridden || false;

  return (
    <>
      <tr onClick={onToggle} style={{ cursor: 'pointer' }}>
        <td>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>
              {entry.mandate_id.slice(0, 18)}…
            </span>
          </span>
        </td>
        <td>{formatCurrency(entry.amount)}</td>
        <td>
          <span className={`badge badge--${rootCause === 'ambiguous' ? 'warning' : rootCause === 'customer_cancelled' ? 'danger' : 'accent'}`}>
            {ROOT_CAUSE_LABELS[rootCause] || rootCause}
          </span>
        </td>
        <td>
          <div className="confidence-bar">
            <div className="confidence-bar__track">
              <div
                className={`confidence-bar__fill confidence-bar__fill--${getConfidenceLevel(confidence)}`}
                style={{ width: `${confidence * 100}%` }}
              />
            </div>
            <span className="confidence-bar__label">{(confidence * 100).toFixed(0)}%</span>
          </div>
        </td>
        <td>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
            {wasOverridden && <Shield size={12} style={{ color: 'var(--warning)' }} />}
            <span className={`badge badge--${action === 'stop' ? 'danger' : action === 'hold_for_review' ? 'warning' : 'info'}`}>
              {ACTION_LABELS[action] || action}
            </span>
          </span>
        </td>
        <td>
          <span className={`badge badge--${outcomeConfig.variant}`}>
            {outcomeConfig.label}
          </span>
        </td>
        <td style={{ fontWeight: entry.amount_recovered > 0 ? 600 : 400, color: entry.amount_recovered > 0 ? 'var(--success)' : 'var(--text-muted)' }}>
          {entry.amount_recovered > 0 ? formatCurrency(entry.amount_recovered) : '—'}
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={7} style={{ padding: 0 }}>
            <div className="row-detail">
              <div className="row-detail__grid">
                <div className="row-detail__item">
                  <div className="row-detail__label">Evidence</div>
                  <div className="row-detail__value">
                    {diagnosis?.evidence || entry.diagnosis_error || 'N/A'}
                  </div>
                </div>
                <div className="row-detail__item">
                  <div className="row-detail__label">Action Reasoning</div>
                  <div className="row-detail__value">
                    {entry.allowed_action?.reasoning || entry.hold_reason || 'N/A'}
                  </div>
                </div>
                {wasOverridden && (
                  <div className="row-detail__item">
                    <div className="row-detail__label">⚠️ Policy Override</div>
                    <div className="row-detail__value">
                      LLM proposed <strong>{entry.allowed_action?.original_proposed_action}</strong>,
                      overridden to <strong>{entry.allowed_action?.action}</strong> by
                      rule: <code>{entry.allowed_action?.override_rule}</code>
                    </div>
                  </div>
                )}
                {diagnosis && (
                  <div className="row-detail__item">
                    <div className="row-detail__label">Cause Evaluations</div>
                    <div className="row-detail__value">
                      {diagnosis.cause_evaluations.map((ce) => (
                        <div key={ce.cause} style={{ marginBottom: '0.25rem' }}>
                          <span className={`badge badge--${ce.verdict === 'plausible' ? 'success' : 'neutral'}`} style={{ marginRight: '0.35rem' }}>
                            {ce.verdict}
                          </span>
                          <strong>{ce.cause}</strong>: {ce.reason}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function RecoveryQueue() {
  const { data, isLoading, error } = useRecords();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const records = data?.records || [];

  const filteredRecords = useMemo(() => {
    let filtered = records;

    if (filter !== 'all') {
      filtered = filtered.filter((r) => {
        if (filter === 'overridden') return r.allowed_action?.was_overridden;
        if (filter === 'held') return r.was_held;
        if (filter === 'recovered') return r.simulated_outcome === 'recovered';
        if (filter === 'stopped') return r.allowed_action?.action === 'stop';
        return r.diagnosis?.root_cause === filter;
      });
    }

    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (r) =>
          r.mandate_id.toLowerCase().includes(q) ||
          r.customer_id.toLowerCase().includes(q)
      );
    }

    return filtered;
  }, [records, filter, searchQuery]);

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner" />
        <span className="loading-text">Loading recovery queue…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="empty-state">
        <div className="empty-state__icon">⚠️</div>
        <div className="empty-state__title">No batch data available</div>
        <div className="empty-state__text">
          Run a batch evaluation first using the API endpoint POST /api/batch/run,
          or run `python -m backend.eval.run_batch` from the project root.
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <h1 className="page-header__title">Recovery Queue</h1>
        <p className="page-header__description">
          {records.length} failure records from batch evaluation
          {data?.metadata?.timestamp && (
            <span> · Run: {data.metadata.timestamp}</span>
          )}
        </p>
      </div>

      {/* Filters */}
      <div className="filters-bar">
        <div style={{ position: 'relative', marginRight: '0.5rem' }}>
          <Search size={14} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
          <input
            type="text"
            placeholder="Search mandate or customer ID…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              padding: '0.4rem 0.85rem 0.4rem 2rem',
              borderRadius: '9999px',
              border: '1px solid var(--border)',
              background: 'transparent',
              color: 'var(--text-primary)',
              fontSize: '0.8rem',
              fontFamily: 'var(--font-family)',
              outline: 'none',
              width: '240px',
            }}
          />
        </div>
        {[
          { key: 'all', label: 'All' },
          { key: 'recovered', label: '✅ Recovered' },
          { key: 'stopped', label: '🛑 Stopped' },
          { key: 'held', label: '⏸ Held' },
          { key: 'overridden', label: '🛡 Overridden' },
          { key: 'insufficient_funds', label: 'Insufficient Funds' },
          { key: 'mandate_expired', label: 'Mandate Expired' },
          { key: 'customer_cancelled', label: 'Customer Cancelled' },
          { key: 'ambiguous', label: 'Ambiguous' },
        ].map(({ key, label }) => (
          <button
            key={key}
            className={`filter-chip ${filter === key ? 'filter-chip--active' : ''}`}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="card">
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Mandate ID</th>
                <th>Amount</th>
                <th>Diagnosis</th>
                <th>Confidence</th>
                <th>Action</th>
                <th>Outcome</th>
                <th>₹ Recovered</th>
              </tr>
            </thead>
            <tbody>
              {filteredRecords.map((entry) => (
                <RecordRow
                  key={entry.mandate_id}
                  entry={entry}
                  isExpanded={expandedId === entry.mandate_id}
                  onToggle={() =>
                    setExpandedId(
                      expandedId === entry.mandate_id ? null : entry.mandate_id
                    )
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
        {filteredRecords.length === 0 && (
          <div className="empty-state">
            <div className="empty-state__title">No records match filters</div>
          </div>
        )}
      </div>
    </div>
  );
}
