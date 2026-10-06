/**
 * Explainability Dashboard — Phase 3
 * 
 * Visualizes the decision path for a selected mandate:
 * Evidence -> Cause Evaluations -> Root Cause -> Policy -> Action -> Outcome
 */

import { useState } from 'react';
import { useRecords } from '../api/hooks';
import { Search, Shield } from 'lucide-react';

function DecisionNode({ title, value, type, children }: any) {
  const getColors = () => {
    switch (type) {
      case 'evidence': return 'rgba(59, 130, 246, 0.2)'; // info
      case 'diagnosis': return 'rgba(139, 92, 246, 0.2)'; // accent
      case 'policy': return 'rgba(245, 158, 11, 0.2)'; // warning
      case 'action': return 'rgba(16, 185, 129, 0.2)'; // success
      case 'outcome': return 'rgba(239, 68, 68, 0.2)'; // danger
      default: return 'var(--bg-card)';
    }
  };

  const getBorder = () => {
    switch (type) {
      case 'evidence': return 'rgba(59, 130, 246, 0.5)';
      case 'diagnosis': return 'rgba(139, 92, 246, 0.5)';
      case 'policy': return 'rgba(245, 158, 11, 0.5)';
      case 'action': return 'rgba(16, 185, 129, 0.5)';
      case 'outcome': return 'rgba(239, 68, 68, 0.5)';
      default: return 'var(--border)';
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      <div 
        style={{
          background: getColors(),
          border: `1px solid ${getBorder()}`,
          borderRadius: 'var(--radius-md)',
          padding: '1rem',
          minWidth: '220px',
          maxWidth: '300px',
          textAlign: 'center',
          boxShadow: 'var(--shadow-md)',
          position: 'relative',
          zIndex: 2,
        }}
      >
        <div style={{ fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-secondary)', marginBottom: '0.5rem', fontWeight: 600 }}>{title}</div>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)', wordBreak: 'break-word' }}>{value}</div>
        {children && <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>{children}</div>}
      </div>
    </div>
  );
}

function VerticalLine() {
  return (
    <div style={{ width: '2px', height: '30px', background: 'var(--border)', margin: '0 auto', zIndex: 1 }} />
  );
}

export default function ExplainPage() {
  const { data, isLoading, error } = useRecords();
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedRecordId, setSelectedRecordId] = useState<string | null>(null);
  
  const records = data?.records || [];
  
  const filteredRecords = records.filter(r => 
    r.mandate_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
    r.customer_id.toLowerCase().includes(searchQuery.toLowerCase())
  ).slice(0, 50);

  const selectedRecord = records.find(r => r.mandate_id === selectedRecordId) || records[0];

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner" />
        <span className="loading-text">Loading Explainability Dashboard…</span>
      </div>
    );
  }

  if (error || !records.length) {
    return (
      <div className="empty-state">
        <div className="empty-state__icon">⚠️</div>
        <div className="empty-state__title">No records available</div>
        <div className="empty-state__text">Run a batch evaluation first to generate records.</div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', gap: '2rem', height: 'calc(100vh - 150px)' }}>
      {/* Sidebar */}
      <div className="card" style={{ width: '300px', display: 'flex', flexDirection: 'column', height: '100%', padding: '1rem' }}>
        <div style={{ position: 'relative', marginBottom: '1rem' }}>
          <Search size={14} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
          <input
            type="text"
            placeholder="Search mandate..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              padding: '0.6rem 0.85rem 0.6rem 2rem',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border)',
              background: 'rgba(0,0,0,0.2)',
              color: 'var(--text-primary)',
              width: '100%',
              outline: 'none',
              fontFamily: 'var(--font-family)',
            }}
          />
        </div>
        
        <div style={{ overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {filteredRecords.map(record => (
            <div 
              key={record.mandate_id}
              onClick={() => setSelectedRecordId(record.mandate_id)}
              style={{
                padding: '0.75rem',
                borderRadius: 'var(--radius-sm)',
                background: selectedRecord?.mandate_id === record.mandate_id ? 'rgba(139, 92, 246, 0.15)' : 'transparent',
                border: `1px solid ${selectedRecord?.mandate_id === record.mandate_id ? 'var(--accent-primary)' : 'transparent'}`,
                cursor: 'pointer',
                transition: 'all 0.2s'
              }}
            >
              <div style={{ fontSize: '0.85rem', fontWeight: 600, fontFamily: 'monospace' }}>{record.mandate_id.slice(0, 16)}...</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.25rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                <span>₹{record.amount}</span>
                <span style={{ color: record.allowed_action?.action === 'stop' ? 'var(--danger)' : 'var(--text-secondary)' }}>
                  {record.diagnosis?.root_cause?.replace(/_/g, ' ')}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Main visualization area */}
      <div className="card card--glow" style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '3rem 2rem' }}>
        {selectedRecord ? (
          <div style={{ width: '100%', maxWidth: '800px' }}>
            <h2 style={{ textAlign: 'center', marginBottom: '2rem', color: 'var(--text-primary)' }}>
              Decision Path: <span style={{ fontFamily: 'monospace', color: 'var(--text-secondary)' }}>{selectedRecord.mandate_id}</span>
            </h2>
            
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              {/* Evidence Node */}
              <DecisionNode 
                title="1. Evidence Collected" 
                value={`Amount: ₹${selectedRecord.amount}`}
                type="evidence"
              >
                <div>{selectedRecord.diagnosis?.evidence || 'No evidence string available'}</div>
              </DecisionNode>

              <VerticalLine />

              {/* Diagnosis Node */}
              <DecisionNode 
                title="2. LLM Diagnosis" 
                value={selectedRecord.diagnosis?.root_cause?.replace(/_/g, ' ') || 'Error'}
                type="diagnosis"
              >
                <div>Confidence: {(selectedRecord.diagnosis?.confidence || 0) * 100}%</div>
                {selectedRecord.diagnosis?.cause_evaluations && (
                  <div style={{ marginTop: '0.5rem', fontSize: '0.7rem', textAlign: 'left', background: 'rgba(0,0,0,0.3)', padding: '0.5rem', borderRadius: '4px' }}>
                    {selectedRecord.diagnosis.cause_evaluations.slice(0,2).map(ce => (
                      <div key={ce.cause} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.2rem' }}>
                        <span style={{ color: ce.verdict === 'plausible' ? 'var(--success)' : 'var(--text-muted)' }}>{ce.verdict === 'plausible' ? '✓' : '✗'}</span>
                        <span>{ce.cause.replace(/_/g, ' ')}</span>
                      </div>
                    ))}
                    {selectedRecord.diagnosis.cause_evaluations.length > 2 && <div style={{ color: 'var(--text-muted)' }}>+ {selectedRecord.diagnosis.cause_evaluations.length - 2} more evaluated</div>}
                  </div>
                )}
              </DecisionNode>

              <VerticalLine />

              {/* Policy Gate */}
              <DecisionNode 
                title="3. Policy Check" 
                value={selectedRecord.allowed_action?.was_overridden ? 'OVERRIDDEN' : 'APPROVED'}
                type="policy"
              >
                {selectedRecord.allowed_action?.was_overridden ? (
                  <div style={{ color: 'var(--warning)' }}>
                    <Shield size={12} style={{ display: 'inline', marginRight: '4px' }} />
                    Rule triggered: {selectedRecord.allowed_action.override_rule}
                    <div style={{ marginTop: '4px' }}>LLM proposed {selectedRecord.allowed_action.original_proposed_action}, overridden to {selectedRecord.allowed_action.action}.</div>
                  </div>
                ) : (
                  <div style={{ color: 'var(--success)' }}>
                    LLM proposed action ({selectedRecord.proposed_action?.action}) passed compliance checks.
                  </div>
                )}
              </DecisionNode>

              <VerticalLine />

              {/* Action Node */}
              <DecisionNode 
                title="4. Executed Action" 
                value={selectedRecord.allowed_action?.action?.replace(/_/g, ' ') || 'None'}
                type="action"
              >
                <div>Reasoning: {selectedRecord.allowed_action?.reasoning}</div>
              </DecisionNode>
              
              <VerticalLine />
              
              {/* Outcome Node */}
              <DecisionNode 
                title="5. Simulated Outcome" 
                value={selectedRecord.simulated_outcome?.replace(/_/g, ' ') || 'None'}
                type="outcome"
              >
                {selectedRecord.amount_recovered > 0 && (
                  <div style={{ color: 'var(--success)', fontWeight: 600 }}>
                    ₹{selectedRecord.amount_recovered} Recovered
                  </div>
                )}
              </DecisionNode>
            </div>
          </div>
        ) : (
          <div className="empty-state">Select a record to view its decision path</div>
        )}
      </div>
    </div>
  );
}
