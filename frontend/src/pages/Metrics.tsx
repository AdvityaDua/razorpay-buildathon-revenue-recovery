/**
 * Metrics page — PRD §11.2
 *
 * Headline numbers: ₹ recovered (system vs. baseline), recovery rate %, % correctly stopped.
 * Diagnosis precision/recall table.
 * Confidence calibration chart.
 */

import { useMetrics } from '../api/hooks';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend, Cell, PieChart, Pie,
} from 'recharts';
import { TrendingUp, TrendingDown, Shield, AlertTriangle, CheckCircle, Activity } from 'lucide-react';

function formatCurrency(amount: number) {
  if (amount >= 100000) {
    return `₹${(amount / 100000).toFixed(1)}L`;
  }
  if (amount >= 1000) {
    return `₹${(amount / 1000).toFixed(1)}K`;
  }
  return `₹${amount.toFixed(0)}`;
}

function formatCurrencyFull(amount: number) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(amount);
}

const CHART_COLORS = {
  primary: '#6366f1',
  secondary: '#8b5cf6',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  info: '#3b82f6',
  muted: '#6b7280',
};

const CAUSE_COLORS: Record<string, string> = {
  insufficient_funds: '#6366f1',
  mandate_expired: '#f59e0b',
  afa_required: '#3b82f6',
  customer_cancelled: '#ef4444',
  genuine_decline: '#8b5cf6',
  ambiguous: '#6b7280',
};

export default function MetricsPage() {
  const { data, isLoading, error } = useMetrics();

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="spinner" />
        <span className="loading-text">Loading metrics…</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="empty-state">
        <div className="empty-state__icon">📊</div>
        <div className="empty-state__title">No metrics available</div>
        <div className="empty-state__text">
          Run a batch evaluation first to generate metrics.
        </div>
      </div>
    );
  }

  const m = data.metrics;
  const pr = m.diagnosis_precision_recall;
  const overall = pr.overall as { accuracy: number; total_evaluated: number; total_correct: number };

  // Precision/recall table data
  const prTableData = Object.entries(pr)
    .filter(([key]) => key !== 'overall')
    .map(([cause, vals]) => ({
      cause,
      ...(vals as { precision: number; recall: number; f1: number; true_positives: number; false_positives: number; false_negatives: number }),
    }));

  // Recovery comparison data
  const recoveryComparisonData = [
    { name: 'AI System', value: m.system_recovered_inr, fill: CHART_COLORS.primary },
    { name: 'Baseline', value: m.baseline_recovered_inr, fill: CHART_COLORS.muted },
    { name: 'Total Recoverable', value: m.total_recoverable_inr, fill: 'rgba(255,255,255,0.1)' },
  ];

  // Calibration data
  const calibrationData = m.confidence_calibration.map((bin) => ({
    ...bin,
    ideal: parseFloat(bin.bin.split('-')[0]) + (parseFloat(bin.bin.split('-')[1]) - parseFloat(bin.bin.split('-')[0])) / 2,
  }));

  // False diagnosis pie data
  const falseDiagData = Object.entries(m.false_diagnoses.by_true_class || {}).map(
    ([cause, count]) => ({
      name: cause.replace(/_/g, ' '),
      value: count,
      fill: CAUSE_COLORS[cause] || CHART_COLORS.muted,
    })
  );

  const improvementPct = m.baseline_recovery_rate_pct > 0
    ? ((m.system_recovery_rate_pct - m.baseline_recovery_rate_pct) / m.baseline_recovery_rate_pct * 100).toFixed(1)
    : '∞';

  return (
    <div>
      <div className="page-header">
        <h1 className="page-header__title">Evaluation Metrics</h1>
        <p className="page-header__description">
          Batch size: {m.batch_size} records
          {data.metadata?.timestamp && ` · Run: ${data.metadata.timestamp}`}
        </p>
      </div>

      {/* ─── Headline Stats ─── */}
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-card__label">₹ Recovered (System)</div>
          <div className="stat-card__value stat-card__value--success">
            {formatCurrency(m.system_recovered_inr)}
          </div>
          <div className={`stat-card__delta stat-card__delta--positive`}>
            <TrendingUp size={14} />
            {m.system_recovery_rate_pct.toFixed(1)}% recovery rate
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__label">₹ Recovered (Baseline)</div>
          <div className="stat-card__value" style={{ color: 'var(--text-muted)' }}>
            {formatCurrency(m.baseline_recovered_inr)}
          </div>
          <div className="stat-card__delta" style={{ color: 'var(--text-muted)' }}>
            {m.baseline_recovery_rate_pct.toFixed(1)}% recovery rate
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__label">Improvement over Baseline</div>
          <div className="stat-card__value stat-card__value--accent">
            +{improvementPct}%
          </div>
          <div className="stat-card__delta stat-card__delta--positive">
            <TrendingUp size={14} />
            {formatCurrency(m.system_recovered_inr - m.baseline_recovered_inr)} more recovered
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__label">Diagnosis Accuracy</div>
          <div className="stat-card__value stat-card__value--accent">
            {(overall.accuracy * 100).toFixed(1)}%
          </div>
          <div className="stat-card__delta" style={{ color: 'var(--text-secondary)' }}>
            {overall.total_correct}/{overall.total_evaluated} correct
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__label">Correctly Stopped</div>
          <div className="stat-card__value stat-card__value--success">
            {m.correctly_stopped_pct.percentage.toFixed(1)}%
          </div>
          <div className="stat-card__delta" style={{ color: 'var(--text-secondary)' }}>
            <CheckCircle size={14} />
            {m.correctly_stopped_pct.correctly_stopped}/{m.correctly_stopped_pct.total_hard_stop_cases} hard-stop cases
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__label">Policy Overrides</div>
          <div className="stat-card__value stat-card__value--warning">
            {m.policy_override_count}
          </div>
          <div className="stat-card__delta" style={{ color: 'var(--text-secondary)' }}>
            <Shield size={14} />
            Times policy layer corrected LLM
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__label">Unnecessary Retries Avoided</div>
          <div className="stat-card__value stat-card__value--success">
            {m.unnecessary_retries_avoided.system_correctly_stopped}
          </div>
          <div className="stat-card__delta" style={{ color: 'var(--text-secondary)' }}>
            <AlertTriangle size={14} />
            vs {m.unnecessary_retries_avoided.baseline_unnecessary_retries} baseline retries
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-card__label">Self-Consistency Rate</div>
          <div className="stat-card__value stat-card__value--accent">
            {(m.self_consistency_rate.rate * 100).toFixed(1)}%
          </div>
          <div className="stat-card__delta" style={{ color: 'var(--text-secondary)' }}>
            <Activity size={14} />
            {m.self_consistency_rate.consistent}/{m.self_consistency_rate.total_evaluated}
          </div>
        </div>
      </div>

      {/* ─── Recovery Comparison Chart ─── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1.5rem' }}>
        <div className="card">
          <div className="card__header">
            <div>
              <div className="card__title">Revenue Recovery Comparison</div>
              <div className="card__subtitle">AI System vs Naive Retry Baseline</div>
            </div>
          </div>
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={recoveryComparisonData} layout="vertical" margin={{ left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis
                  type="number"
                  tick={{ fill: '#9ca3af', fontSize: 11 }}
                  tickFormatter={(v) => formatCurrency(v)}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  tick={{ fill: '#9ca3af', fontSize: 12 }}
                  width={120}
                />
                <Tooltip
                  contentStyle={{
                    background: '#1a1a2e',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '8px',
                    color: '#e8e8f0',
                    fontSize: '12px',
                  }}
                  formatter={(value: number) => [formatCurrencyFull(value), 'Amount']}
                />
                <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                  {recoveryComparisonData.map((entry, index) => (
                    <Cell key={index} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Confidence Calibration */}
        <div className="card">
          <div className="card__header">
            <div>
              <div className="card__title">Confidence Calibration</div>
              <div className="card__subtitle">Predicted confidence vs actual accuracy (reliability plot)</div>
            </div>
          </div>
          <div className="chart-container">
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={calibrationData}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis
                  dataKey="bin"
                  tick={{ fill: '#9ca3af', fontSize: 11 }}
                  label={{ value: 'Confidence Bin', position: 'insideBottom', offset: -5, style: { fill: '#6b7280', fontSize: 11 } }}
                />
                <YAxis
                  tick={{ fill: '#9ca3af', fontSize: 11 }}
                  domain={[0, 1]}
                  label={{ value: 'Accuracy', angle: -90, position: 'insideLeft', style: { fill: '#6b7280', fontSize: 11 } }}
                />
                <Tooltip
                  contentStyle={{
                    background: '#1a1a2e',
                    border: '1px solid rgba(255,255,255,0.1)',
                    borderRadius: '8px',
                    color: '#e8e8f0',
                    fontSize: '12px',
                  }}
                />
                <Legend wrapperStyle={{ fontSize: '12px', color: '#9ca3af' }} />
                <Line
                  type="monotone"
                  dataKey="accuracy"
                  stroke={CHART_COLORS.primary}
                  strokeWidth={2}
                  dot={{ r: 5, fill: CHART_COLORS.primary }}
                  name="Actual Accuracy"
                />
                <Line
                  type="monotone"
                  dataKey="avg_confidence"
                  stroke={CHART_COLORS.muted}
                  strokeDasharray="5 5"
                  strokeWidth={1.5}
                  dot={{ r: 4, fill: CHART_COLORS.muted }}
                  name="Avg Confidence"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* ─── Precision / Recall Table ─── */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1.5rem', marginBottom: '1.5rem' }}>
        <div className="card">
          <div className="card__header">
            <div>
              <div className="card__title">Diagnosis Precision / Recall</div>
              <div className="card__subtitle">Per root-cause class against ground truth</div>
            </div>
          </div>
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Root Cause</th>
                  <th>Precision</th>
                  <th>Recall</th>
                  <th>F1</th>
                  <th>TP</th>
                  <th>FP</th>
                  <th>FN</th>
                </tr>
              </thead>
              <tbody>
                {prTableData.map((row) => (
                  <tr key={row.cause}>
                    <td>
                      <span className="badge badge--accent" style={{ borderColor: CAUSE_COLORS[row.cause] + '40', color: CAUSE_COLORS[row.cause] }}>
                        {row.cause.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td style={{ fontWeight: 600 }}>{(row.precision * 100).toFixed(1)}%</td>
                    <td style={{ fontWeight: 600 }}>{(row.recall * 100).toFixed(1)}%</td>
                    <td style={{ fontWeight: 600, color: 'var(--accent-primary)' }}>{(row.f1 * 100).toFixed(1)}%</td>
                    <td style={{ color: 'var(--success)' }}>{row.true_positives}</td>
                    <td style={{ color: 'var(--danger)' }}>{row.false_positives}</td>
                    <td style={{ color: 'var(--warning)' }}>{row.false_negatives}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* False Diagnoses Breakdown */}
        <div className="card">
          <div className="card__header">
            <div>
              <div className="card__title">False Diagnoses</div>
              <div className="card__subtitle">{m.false_diagnoses.total_false} total misdiagnoses by true class</div>
            </div>
          </div>
          {falseDiagData.length > 0 ? (
            <div className="chart-container" style={{ display: 'flex', justifyContent: 'center' }}>
              <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                  <Pie
                    data={falseDiagData}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={90}
                    paddingAngle={3}
                    dataKey="value"
                    label={({ name, value }) => `${name}: ${value}`}
                    labelLine={{ stroke: '#6b7280' }}
                  >
                    {falseDiagData.map((entry, index) => (
                      <Cell key={index} fill={entry.fill} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      background: '#1a1a2e',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: '8px',
                      color: '#e8e8f0',
                      fontSize: '12px',
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="empty-state" style={{ padding: '2rem' }}>
              <div className="empty-state__icon">✅</div>
              <div className="empty-state__title">No false diagnoses</div>
            </div>
          )}
        </div>
      </div>

      {/* ─── Calibration Bin Details ─── */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="card__header">
          <div>
            <div className="card__title">Confidence Calibration Bins</div>
            <div className="card__subtitle">Detailed bin breakdown showing count, accuracy, and average confidence</div>
          </div>
        </div>
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Confidence Bin</th>
                <th>Count</th>
                <th>Actual Accuracy</th>
                <th>Avg Confidence</th>
                <th>Calibration Gap</th>
              </tr>
            </thead>
            <tbody>
              {m.confidence_calibration.map((bin) => {
                const gap = Math.abs(bin.accuracy - bin.avg_confidence);
                return (
                  <tr key={bin.bin}>
                    <td style={{ fontFamily: 'monospace' }}>{bin.bin}</td>
                    <td>{bin.count}</td>
                    <td style={{ fontWeight: 600 }}>{(bin.accuracy * 100).toFixed(1)}%</td>
                    <td>{(bin.avg_confidence * 100).toFixed(1)}%</td>
                    <td>
                      <span style={{ color: gap > 0.15 ? 'var(--danger)' : gap > 0.08 ? 'var(--warning)' : 'var(--success)' }}>
                        {(gap * 100).toFixed(1)}%
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
