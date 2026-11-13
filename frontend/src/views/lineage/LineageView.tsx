import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'

import LineageDrawer from './LineageDrawer'
import { StatusBadge } from './components'
import type { LineageStats, SampleListItem } from './types'

const STATUS_OPTIONS = ['已交付', '已隔离', '待续做', '证据缺口']

interface Filters {
  keyword: string
  status: string
  evidence_gap: string
  merged_only: string
}

const EMPTY_FILTERS: Filters = { keyword: '', status: '', evidence_gap: '', merged_only: '' }

/** 样本血缘追踪页：列表定位问题样本，点开抽屉看逐段证据与重演。 */
export default function LineageView() {
  const [rows, setRows] = useState<SampleListItem[]>([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState<LineageStats | null>(null)
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [appliedFilters, setAppliedFilters] = useState<Filters>(EMPTY_FILTERS)
  const [activeId, setActiveId] = useState<number | null>(null)
  const [toast, setToast] = useState<{ message: string; error: boolean } | null>(null)
  const [errorMessage, setErrorMessage] = useState('')

  const showToast = useCallback((message: string, isError = false) => {
    setToast({ message, error: isError })
    window.setTimeout(() => setToast(null), 3200)
  }, [])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const params = new URLSearchParams()
    if (appliedFilters.keyword) params.set('keyword', appliedFilters.keyword)
    if (appliedFilters.status) params.set('status', appliedFilters.status)
    if (appliedFilters.evidence_gap) params.set('evidence_gap', appliedFilters.evidence_gap)
    if (appliedFilters.merged_only) params.set('merged_only', appliedFilters.merged_only)
    try {
      const response = await request(`/api/lineage?${params.toString()}`)
      if (!response.ok) throw new Error('样本血缘列表读取失败')
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '样本血缘列表读取失败')
    }
  }, [appliedFilters])

  const reloadStats = useCallback(async () => {
    const response = await request('/api/lineage/stats')
    if (response.ok) setStats(await response.json())
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    void reloadStats()
  }, [reloadStats])

  const statCards = stats ? [
    { label: '样本总数', value: stats.sample_total },
    { label: '已交付', value: stats.delivered },
    { label: '校验隔离', value: stats.quarantined },
    { label: '待续做断点', value: stats.resume_pending },
    { label: '证据缺口', value: stats.evidence_gap },
    { label: '去重合并样本', value: stats.merged },
  ] : []

  return (
    <section className="page" data-module="lineage">
      <header className="page-head">
        <div>
          <h2>样本血缘追踪</h2>
          <p className="page-desc">
            从原始网页片段追到字段映射、数据清洗、结果校验与最终存储的每段证据；
            支持断点幂等续做与候选规则重演，重演只生成实验轨迹，不覆盖正式交付。
          </p>
        </div>
      </header>

      <div className="stat-row">
        {statCards.map((card) => (
          <article key={card.label} className="stat-card">
            <span className="stat-label">{card.label}</span>
            <strong className="stat-value">{card.value}</strong>
          </article>
        ))}
      </div>

      <form
        className="filter-bar"
        onSubmit={(event) => {
          event.preventDefault()
          setAppliedFilters(filters)
        }}
      >
        <label className="filter-item">
          <span>样本编号 / 业务键 / 标题</span>
          <input
            value={filters.keyword}
            placeholder="按关键词检索"
            onChange={(e) => setFilters((prev) => ({ ...prev, keyword: e.target.value }))}
          />
        </label>
        <label className="filter-item">
          <span>样本状态</span>
          <select value={filters.status} onChange={(e) => setFilters((prev) => ({ ...prev, status: e.target.value }))}>
            <option value="">全部</option>
            {STATUS_OPTIONS.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </label>
        <label className="filter-item">
          <span>证据缺口</span>
          <select
            value={filters.evidence_gap}
            onChange={(e) => setFilters((prev) => ({ ...prev, evidence_gap: e.target.value }))}
          >
            <option value="">全部</option>
            <option value="true">仅看有缺口</option>
            <option value="false">仅看证据完整</option>
          </select>
        </label>
        <label className="filter-item">
          <span>去重合并</span>
          <select
            value={filters.merged_only}
            onChange={(e) => setFilters((prev) => ({ ...prev, merged_only: e.target.value }))}
          >
            <option value="">全部</option>
            <option value="true">仅看合并样本</option>
          </select>
        </label>
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => { setFilters(EMPTY_FILTERS); setAppliedFilters(EMPTY_FILTERS) }}>
          重置条件
        </button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            <th>样本编号</th>
            <th>业务键 / 标题</th>
            <th>状态</th>
            <th>来源数</th>
            <th>处理段</th>
            <th>标记</th>
            <th>续做断点</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td className="mono">{row.sample_code}</td>
              <td>
                <div className="mono" style={{ fontSize: 12 }}>{row.business_key}</div>
                <div>{row.title}</div>
              </td>
              <td><StatusBadge status={row.status} /></td>
              <td>
                {row.source_count}
                {row.merged && <div className="muted-text" style={{ fontSize: 12 }}>合并保留全部来源</div>}
                {row.source_count === 0 && <div className="muted-text" style={{ fontSize: 12 }}>来源缺失</div>}
              </td>
              <td>
                {row.segment_count} 段
                {row.gap_segment_count > 0 && (
                  <div className="muted-text" style={{ fontSize: 12 }}>含 {row.gap_segment_count} 段缺口</div>
                )}
              </td>
              <td>
                <span className="badge-stack">
                  {row.quarantined && <span className="badge danger">已隔离</span>}
                  {row.merged && <span className="badge warn">合并</span>}
                  {row.evidence_gap && <span className="badge gap">证据缺口</span>}
                  {!row.quarantined && !row.merged && !row.evidence_gap && <span className="badge ok">正常</span>}
                </span>
              </td>
              <td>{row.resume_stage ? <span className="badge warn">{row.resume_stage}</span> : <span className="muted-text">—</span>}</td>
              <td className="row-actions">
                <button className="link" type="button" onClick={() => setActiveId(row.id)}>
                  查看血缘证据
                </button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={8}>没有符合条件的样本</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条样本血缘记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>

      {activeId !== null && (
        <LineageDrawer
          sampleId={activeId}
          onClose={() => setActiveId(null)}
          onToast={showToast}
          onChanged={() => {
            void reload()
            void reloadStats()
          }}
        />
      )}
      {toast && <div className={`toast ${toast.error ? 'error' : ''}`}>{toast.message}</div>}
    </section>
  )
}
