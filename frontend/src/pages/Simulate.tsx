/**
 * Live Simulation Page — Phase 3
 * Allows tweaking inputs and running the agent pipeline in real-time.
 */

import { useState } from 'react';
import { useSimulate } from '../api/hooks';
import { PlayCircle, Settings2, Activity, CheckCircle, AlertTriangle } from 'lucide-react';

const DEFAULT_RECORD = {
  mandate_id: 'live_sim_001',
  customer_id: 'cust_live',
  merchant_id: 'demo_merch',
  amount: 2500,
  mandate_type: 'upi_autopay',
  scheduled_debit_at: new Date().toISOString(),
  actual_attempt_at: new Date().toISOString(),
  pre_debit_notification_sent_at: new Date(Date.now() - 86400000).toISOString(),
  error_code: 'INSUFFICIENT_FUNDS',
  error_reason: 'Balance not sufficient',
  error_source: 'bank',
  error_step: 'debit',
  mandate_status: 'active',
  mandate_created_at: new Date(Date.now() - 30 * 86400000).toISOString(),
  mandate_validity_days: 365,
  customer_prior_successful_payments: 5,
  customer_prior_failures: 0,
  customer_last_payment_date: new Date(Date.now() - 30 * 86400000).toISOString().split('T')[0],
  retry_attempt_number: 0,
};

export default function SimulatePage() {
  const [record, setRecord] = useState<any>(DEFAULT_RECORD);
  const { mutate: runSimulation, data: result, isPending, error } = useSimulate();

  const handleChange = (field: string, value: any) => {
    setRecord((prev: any) => ({ ...prev, [field]: value }));
  };

  const handleSimulate = () => {
    runSimulation(record);
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2.5rem' }}>
      {/* Input Panel */}
      <div className="card">
        <div className="card__header">
          <div>
            <h2 className="card__title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Settings2 size={18} /> Scenario Builder
            </h2>
            <div className="card__subtitle">Configure the failure record payload</div>
          </div>
          <button 
            className="primary-button" 
            onClick={handleSimulate}
            disabled={isPending}
            style={{ opacity: isPending ? 0.7 : 1 }}
          >
            {isPending ? <div className="spinner" style={{ width: 16, height: 16, borderWidth: 2 }} /> : <PlayCircle size={16} />}
            {isPending ? 'Simulating...' : 'Run Simulation'}
          </button>
        </div>

        <div style={{ display: 'grid', gap: '1.25rem', marginTop: '1.5rem' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>Amount (₹)</label>
            <input 
              type="number" 
              value={record.amount} 
              onChange={(e) => handleChange('amount', parseFloat(e.target.value))}
              style={{ width: '100%', padding: '0.6rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'rgba(0,0,0,0.2)', color: 'white', fontFamily: 'var(--font-family)' }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>Error Code</label>
              <input 
                type="text" 
                value={record.error_code || ''} 
                onChange={(e) => handleChange('error_code', e.target.value || null)}
                placeholder="e.g. INSUFFICIENT_FUNDS"
                style={{ width: '100%', padding: '0.6rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'rgba(0,0,0,0.2)', color: 'white', fontFamily: 'var(--font-family)' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>Mandate Status</label>
              <select 
                value={record.mandate_status} 
                onChange={(e) => handleChange('mandate_status', e.target.value)}
                style={{ width: '100%', padding: '0.6rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'white', fontFamily: 'var(--font-family)' }}
              >
                <option value="active">Active</option>
                <option value="paused">Paused</option>
                <option value="revoked">Revoked</option>
                <option value="expired">Expired</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>Prior Successful Payments</label>
              <input 
                type="number" 
                value={record.customer_prior_successful_payments} 
                onChange={(e) => handleChange('customer_prior_successful_payments', parseInt(e.target.value, 10))}
                style={{ width: '100%', padding: '0.6rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'rgba(0,0,0,0.2)', color: 'white', fontFamily: 'var(--font-family)' }}
              />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>Retry Attempt Number</label>
              <input 
                type="number" 
                value={record.retry_attempt_number} 
                onChange={(e) => handleChange('retry_attempt_number', parseInt(e.target.value, 10))}
                style={{ width: '100%', padding: '0.6rem', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'rgba(0,0,0,0.2)', color: 'white', fontFamily: 'var(--font-family)' }}
              />
            </div>
          </div>
          
          <div style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(255,255,255,0.03)', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            <strong>Tip:</strong> Try setting Error Code to empty to test ambiguous cases, or Mandate Status to "revoked" to trigger a policy override.
          </div>
        </div>
      </div>

      {/* Output Panel */}
      <div className="card card--glow">
        <div className="card__header">
          <div>
            <h2 className="card__title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Activity size={18} /> Live Output
            </h2>
            <div className="card__subtitle">Agent reasoning and policy execution</div>
          </div>
        </div>

        {error && (
          <div style={{ padding: '1rem', background: 'var(--danger-bg)', color: 'var(--danger)', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
            Error running simulation: {error.message}
          </div>
        )}

        {!result && !error && !isPending && (
          <div className="empty-state" style={{ padding: '3rem 1rem' }}>
            <div className="empty-state__icon">🧠</div>
            <div className="empty-state__title">Ready to simulate</div>
            <div className="empty-state__text">Configure the scenario on the left and hit Run to watch the agent reason in real-time.</div>
          </div>
        )}

        {isPending && (
          <div className="loading-container" style={{ padding: '3rem 1rem' }}>
            <div className="spinner" />
            <span className="loading-text">Agent is thinking...</span>
          </div>
        )}

        {result && !isPending && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', animation: 'fadeIn 0.5s ease-out' }}>
            {/* Diagnosis Result */}
            <div>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.75rem' }}>1. Diagnosis</div>
              <div style={{ background: 'rgba(255,255,255,0.03)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <span style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)' }}>{result.diagnosis?.root_cause?.replace(/_/g, ' ')}</span>
                  <span className={`badge badge--${(result.diagnosis?.confidence || 0) > 0.7 ? 'success' : 'warning'}`}>
                    {((result.diagnosis?.confidence || 0) * 100).toFixed(0)}% Confidence
                  </span>
                </div>
                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>{result.diagnosis?.evidence}</div>
              </div>
            </div>

            {/* Policy & Action Result */}
            <div>
              <div style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.75rem' }}>2. Action Selected</div>
              <div style={{ background: 'rgba(255,255,255,0.03)', padding: '1.25rem', borderRadius: 'var(--radius-md)', border: `1px solid ${result.allowed_action?.was_overridden ? 'rgba(245, 158, 11, 0.5)' : 'var(--border)'}` }}>
                {result.allowed_action?.was_overridden ? (
                  <div style={{ display: 'flex', gap: '0.5rem', color: 'var(--warning)', marginBottom: '0.75rem', fontWeight: 500 }}>
                    <AlertTriangle size={18} />
                    <span>Policy Layer Override: {result.allowed_action.override_rule}</span>
                  </div>
                ) : (
                  <div style={{ display: 'flex', gap: '0.5rem', color: 'var(--success)', marginBottom: '0.75rem', fontWeight: 500 }}>
                    <CheckCircle size={18} />
                    <span>Policy Checks Passed</span>
                  </div>
                )}
                
                <div style={{ fontSize: '1.1rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.5rem' }}>
                  {result.allowed_action?.action?.replace(/_/g, ' ')}
                </div>
                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>{result.allowed_action?.reasoning}</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
