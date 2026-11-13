import type { ReactNode } from 'react'

import type { FieldDiff, Segment } from './types'

/** 状态徽章：把后端的状态字符串映射成统一配色。 */
export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { cls: string; text: string }> = {
    已交付: { cls: 'ok', text: '已交付' },
    已隔离: { cls: 'danger', text: '已隔离' },
    待续做: { cls: 'warn', text: '待续做' },
    证据缺口: { cls: 'gap', text: '证据缺口' },
  }
  const item = map[status] ?? { cls: 'gap', text: status }
  return <span className={`badge ${item.cls}`}>{item.text}</span>
}

/** 处理段状态小圆标：隔离 / 缺口 / 候选实验。 */
export function SegmentFlags({ segment }: { segment: Segment }) {
  return (
    <span className="badge-stack">
      {segment.evidence_gap && <span className="badge gap">证据缺口</span>}
      {segment.status === 'quarantined' && <span className="badge danger">已隔离</span>}
      {segment.is_candidate && <span className="badge experiment">候选规则</span>}
      {segment.diverged && <span className="badge warn">与交付分叉</span>}
    </span>
  )
}

/** 任意 JSON 快照的只读展示，null 明确渲染成缺口提示而不是空白。 */
export function SnapshotBox({ title, value, missing }: { title: string; value: unknown; missing?: boolean }) {
  if (missing || value === null || value === undefined) {
    return (
      <div className="snapshot-box">
        <h5>{title}</h5>
        <pre className="muted-text">（无快照：该段证据缺失，无法回溯此值）</pre>
      </div>
    )
  }
  return (
    <div className="snapshot-box">
      <h5>{title}</h5>
      <pre className="mono">{JSON.stringify(value, null, 2)}</pre>
    </div>
  )
}

/** 逐字段差异表：左交付、右实验，没有差异时给出明确说明。 */
export function DiffTable({ diffs }: { diffs: FieldDiff[] | undefined }) {
  if (!diffs || diffs.length === 0) {
    return <p className="muted-text" style={{ fontSize: 12, margin: '6px 0' }}>该段输出与正式交付一致，无字段差异。</p>
  }
  return (
    <table className="diff-table">
      <thead>
        <tr><th style={{ width: 120 }}>字段</th><th>正式交付值</th><th>实验分支值</th></tr>
      </thead>
      <tbody>
        {diffs.map((diff) => (
          <tr key={diff.field}>
            <td className="mono">{diff.field}</td>
            <td className="old mono">{render(diff.delivered)}</td>
            <td className="new mono">{render(diff.experiment)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function render(value: unknown): string {
  if (value === null || value === undefined) return '∅'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** 单条处理段卡片：规则版本、变换说明、输入/输出快照与差异全部摊开。 */
export function SegmentCard({ segment, extra }: { segment: Segment; extra?: ReactNode }) {
  const cls = [
    'seg-card',
    segment.evidence_gap ? 'gap' : '',
    segment.status === 'quarantined' ? 'quarantined' : '',
    segment.is_candidate ? 'candidate' : '',
  ].filter(Boolean).join(' ')
  return (
    <article className={cls}>
      <div className="seg-head">
        <div>
          <span className="seg-name">{segment.stage_name}</span>
          <span className="seg-rule">
            　<span className="mono">{segment.rule_id} @ {segment.rule_version}</span>
            {segment.batch_id ? `　批次 ${segment.batch_id}` : ''}
          </span>
        </div>
        <SegmentFlags segment={segment} />
      </div>
      <div className="seg-transform">{segment.transform}</div>
      {segment.reasons.length > 0 && (
        <ul className="muted-text" style={{ fontSize: 12, margin: '4px 0', paddingLeft: 18 }}>
          {segment.reasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      )}
      {segment.compare_note && <p className="muted-text" style={{ fontSize: 12, margin: '4px 0' }}>{segment.compare_note}</p>}
      {segment.evidence_gap ? (
        <SnapshotBox title="输入快照" value={null} missing />
      ) : (
        <div className="snapshot-grid">
          <SnapshotBox title="进入本段的值（输入快照）" value={segment.input_value} />
          <SnapshotBox title="变换后的值（输出快照）" value={segment.output_value} />
        </div>
      )}
      {extra}
    </article>
  )
}
