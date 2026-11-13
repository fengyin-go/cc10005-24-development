import { useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

import { DiffTable, SegmentCard, SnapshotBox, StatusBadge } from './components'
import type {
  CandidateRule,
  ExperimentDetail,
  ExperimentSummary,
  SampleDetail,
} from './types'

interface DrawerProps {
  sampleId: number
  onClose: () => void
  onToast: (message: string, isError?: boolean) => void
  onChanged: () => void
}

/** 样本血缘详情抽屉：来源证据、逐段时间线、候选规则重演都在这里完成。 */
export default function LineageDrawer({ sampleId, onClose, onToast, onChanged }: DrawerProps) {
  const [detail, setDetail] = useState<SampleDetail | null>(null)
  const [tab, setTab] = useState<'lineage' | 'experiment'>('lineage')
  const [candidates, setCandidates] = useState<CandidateRule[]>([])
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([])
  const [activeExperiment, setActiveExperiment] = useState<ExperimentDetail | null>(null)
  const [selectedRule, setSelectedRule] = useState('')
  const [replayNote, setReplayNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [resuming, setResuming] = useState(false)

  async function loadDetail() {
    const response = await request(`/api/lineage/${sampleId}`)
    if (response.ok) setDetail(await response.json())
  }

  async function loadExperiments() {
    const response = await request(`/api/lineage/experiments?sample_id=${sampleId}`)
    if (response.ok) setExperiments((await response.json()).items ?? [])
  }

  useEffect(() => {
    void loadDetail()
    void request('/api/lineage/candidate-rules')
      .then((r) => r.ok ? r.json() : { items: [] })
      .then((payload) => setCandidates(payload.items ?? []))
    void loadExperiments()
  }, [sampleId])

  const replayableCandidates = useMemo(() => {
    if (!detail?.evidence_gap) return candidates
    // 缺口样本没有采集/映射证据，前端直接禁掉这两个阶段，避免无效提交。
    return candidates.filter((rule) => rule.stage !== 'collect' && rule.stage !== 'extract')
  }, [candidates, detail])

  async function handleResume() {
    if (!detail) return
    setResuming(true)
    try {
      const response = await request(`/api/lineage/${detail.id}/resume`, {
        method: 'POST',
        body: JSON.stringify({ values: {} }),
      })
      const payload = await response.json()
      if (!payload.ok) throw new Error(payload.message)
      onToast(payload.message)
      await loadDetail()
      onChanged()
    } catch (error) {
      onToast(error instanceof Error ? error.message : '断点续做失败', true)
    } finally {
      setResuming(false)
    }
  }

  async function handleReplay() {
    if (!detail || !selectedRule) {
      onToast('请先选择一条候选规则', true)
      return
    }
    setSubmitting(true)
    try {
      const response = await request(`/api/lineage/${detail.id}/replay`, {
        method: 'POST',
        body: JSON.stringify({ values: { candidate_rule_id: selectedRule, note: replayNote } }),
      })
      const payload = await response.json()
      if (!payload.ok) throw new Error(payload.message)
      onToast(payload.message)
      setTab('experiment')
      await loadExperiments()
      await openExperiment(payload.entry.id)
      setReplayNote('')
    } catch (error) {
      onToast(error instanceof Error ? error.message : '重演失败', true)
    } finally {
      setSubmitting(false)
    }
  }

  async function openExperiment(experimentId: number) {
    const response = await request(`/api/lineage/experiments/${experimentId}`)
    if (response.ok) setActiveExperiment(await response.json())
  }

  if (!detail) {
    return (
      <>
        <div className="drawer-mask" onClick={onClose} />
        <aside className="drawer"><p className="muted-text">血缘详情加载中…</p></aside>
      </>
    )
  }

  return (
    <>
      <div className="drawer-mask" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label="样本血缘详情">
        <div className="drawer-head">
          <div>
            <h3 className="drawer-title">
              {detail.sample_code}　{detail.title}
            </h3>
            <div className="drawer-sub">
              <StatusBadge status={detail.status} />
              <span className="mono">业务键 {detail.business_key}</span>
              <span>来源 {detail.source_count} 个</span>
              <span>处理段 {detail.segment_count} 段</span>
              {detail.merged && <span className="badge warn">去重合并样本</span>}
            </div>
          </div>
          <button className="btn ghost" type="button" onClick={onClose}>关闭</button>
        </div>

        <div className="tabs">
          <button className={`tab ${tab === 'lineage' ? 'active' : ''}`} type="button" onClick={() => setTab('lineage')}>
            正式交付血缘
          </button>
          <button className={`tab ${tab === 'experiment' ? 'active' : ''}`} type="button" onClick={() => setTab('experiment')}>
            重演实验分支（{experiments.length}）
          </button>
        </div>

        {tab === 'lineage' ? (
          <LineageTab
            detail={detail}
            resuming={resuming}
            onResume={handleResume}
            candidates={replayableCandidates}
            selectedRule={selectedRule}
            setSelectedRule={setSelectedRule}
            replayNote={replayNote}
            setReplayNote={setReplayNote}
            submitting={submitting}
            onReplay={handleReplay}
          />
        ) : (
          <ExperimentTab
            experiments={experiments}
            active={activeExperiment}
            onOpen={openExperiment}
          />
        )}
      </aside>
    </>
  )
}

function LineageTab(props: {
  detail: SampleDetail
  resuming: boolean
  onResume: () => void
  candidates: CandidateRule[]
  selectedRule: string
  setSelectedRule: (value: string) => void
  replayNote: string
  setReplayNote: (value: string) => void
  submitting: boolean
  onReplay: () => void
}) {
  const { detail } = props
  return (
    <div>
      {detail.evidence_gap && (
        <div className="gap-banner">
          <strong>该样本存在证据缺口：</strong>缺少原始网页片段与抓取上下文，下列时间线中以虚线徽章明确标出，
          缺口段无法参与续做与重演，请结合迁移记录人工核对。
        </div>
      )}

      {detail.resume_stage && (
        <div className="replay-panel">
          <strong>跨批次续做</strong>
          <p className="muted-text" style={{ fontSize: 12, margin: '6px 0' }}>
            断点停在「{detail.resume_stage}」阶段之前。续做按处理段指纹幂等追加，重复触发不会产生重复段，
            断点前的 {detail.segment_count} 段证据保持不变。
          </p>
          <button className="btn primary" type="button" disabled={props.resuming} onClick={props.onResume}>
            {props.resuming ? '续做中…' : `从 ${detail.resume_stage} 阶段幂等续做`}
          </button>
        </div>
      )}

      <h4 className="section-title">全部来源证据（{detail.sources.length}）</h4>
      {detail.sources.length === 0 ? (
        <div className="gap-banner">无任何采集来源：历史迁移样例，来源 URL 与原始 HTML 片段均缺失。</div>
      ) : (
        <div className="source-grid">
          {detail.sources.map((source) => (
            <article className="source-card" key={source.source_ref ?? source.captured_at}>
              <strong style={{ fontSize: 13 }}>来源</strong>
              <div className="meta mono">{source.source_ref}</div>
              <div className="meta">抓取批次：{source.batch_id}　时间：{source.captured_at}</div>
              {source.dedup_key && <div className="meta">去重键：<span className="mono">{source.dedup_key}</span></div>}
              <pre className="snippet">{source.raw_snippet}</pre>
            </article>
          ))}
        </div>
      )}

      <h4 className="section-title">逐段处理证据时间线</h4>
      <div className="timeline">
        {detail.segments.map((segment) => (
          <SegmentCard key={`${segment.stage}-${segment.fingerprint || segment.batch_id}`} segment={segment} />
        ))}
      </div>

      {detail.final_value && (
        <>
          <h4 className="section-title">最终存储结果（交付值，不可变）</h4>
          <SnapshotBox title="final_value" value={detail.final_value} />
        </>
      )}

      <h4 className="section-title">候选规则重演（只生成实验轨迹）</h4>
      <div className="replay-panel">
        <p className="muted-text" style={{ fontSize: 12, marginTop: 0 }}>
          重演在实验分支上重跑整条链路，正式交付给存储的证据不会被覆盖；实验与交付的逐字段差异会单独留档。
        </p>
        <div className="replay-row">
          <select value={props.selectedRule} onChange={(e) => props.setSelectedRule(e.target.value)}>
            <option value="">请选择候选规则…</option>
            {props.candidates.map((rule) => (
              <option key={rule.rule_id} value={rule.rule_id}>
                [{rule.stage_name}] {rule.rule_id}（{rule.rule_version}）— {rule.summary}
              </option>
            ))}
          </select>
          <input
            placeholder="实验备注（可选）"
            value={props.replayNote}
            onChange={(e) => props.setReplayNote(e.target.value)}
            style={{ padding: '6px 8px', border: '1px solid var(--border)', borderRadius: 6, minWidth: 200 }}
          />
          <button className="btn primary" type="button" disabled={props.submitting} onClick={props.onReplay}>
            {props.submitting ? '重演中…' : '用候选规则重演'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ExperimentTab(props: {
  experiments: ExperimentSummary[]
  active: ExperimentDetail | null
  onOpen: (id: number) => void
}) {
  if (props.experiments.length === 0) {
    return <p className="muted-text">该样本还没有重演实验。在「正式交付血缘」页签底部选择候选规则即可生成第一条实验轨迹。</p>
  }
  return (
    <div>
      <div className="replay-row" style={{ marginBottom: 10 }}>
        {props.experiments.map((exp) => (
          <button
            key={exp.id}
            className={`btn ${props.active?.id === exp.id ? 'primary' : ''}`}
            type="button"
            onClick={() => props.onOpen(exp.id)}
          >
            {exp.experiment_code} · {exp.candidate_rule_id}
          </button>
        ))}
      </div>

      {props.active && (
        <div>
          <div className="drawer-sub" style={{ marginBottom: 8 }}>
            <span className="badge experiment">实验分支 · 不可变</span>
            <span className="mono">{props.active.candidate_rule_id} @ {props.active.candidate_rule_version}</span>
            <span>创建于 {props.active.created_at}</span>
            {props.active.carried_evidence_gap && <span className="badge gap">沿用证据缺口</span>}
            {props.active.summary.experiment_quarantined
              ? <span className="badge danger">实验结果被隔离</span>
              : <span className="badge ok">实验结果通过校验</span>}
          </div>
          {props.active.note && <p className="muted-text" style={{ fontSize: 12 }}>备注：{props.active.note}</p>}

          <h4 className="section-title">实验结论</h4>
          <ul style={{ fontSize: 13 }}>
            <li>首次分叉阶段：{props.active.summary.first_divergence_stage ?? '无分叉，与交付完全一致'}</li>
            <li>最终结果是否分叉：{props.active.summary.final_diverged ? '是' : '否'}</li>
            <li>正式交付证据保持不变：{props.active.summary.delivered_final_untouched ? '是' : '否'}</li>
          </ul>
          {props.active.summary.final_field_diffs.length > 0 && (
            <>
              <h5 style={{ marginBottom: 4 }}>最终值逐字段差异</h5>
              <DiffTable diffs={props.active.summary.final_field_diffs} />
            </>
          )}

          <h4 className="section-title">实验处理段（与正式血缘平行留档）</h4>
          <div className="timeline">
            {props.active.segments.map((segment) => (
              <SegmentCard
                key={`${segment.stage}-${segment.rule_id}`}
                segment={segment}
                extra={segment.diffs !== undefined ? (
                  <div style={{ marginTop: 8 }}>
                    <h5 style={{ margin: '0 0 4px', fontSize: 12, color: 'var(--muted)' }}>
                      与正式交付同段对比
                    </h5>
                    <DiffTable diffs={segment.diffs} />
                  </div>
                ) : undefined}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
