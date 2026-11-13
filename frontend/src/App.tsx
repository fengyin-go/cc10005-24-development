import { useState } from 'react'
import { Link, Route, Routes } from 'react-router-dom'

import Overview from './views/Overview'
import SiteView from './views/site'
import TemplateView from './views/template'
import ProxyView from './views/proxy'
import SpiderView from './views/spider'
import ScheduleView from './views/schedule'
import AntibotView from './views/antibot'
import RatelimitView from './views/ratelimit'
import RetryView from './views/retry'
import ExtractorView from './views/extractor'
import PipelineView from './views/pipeline'
import ValidatorView from './views/validator'
import StorageView from './views/storage'
import MonitorView from './views/monitor'
import CleanseView from './views/cleanse'
import DeltaView from './views/delta'
import ExportView from './views/export'
import RpaflowView from './views/rpaflow'
import AuthView from './views/auth'
import LineageView from './views/lineage'

const navItems = [{ label: "运营概览", path: "/" }, { label: "站点管理", path: "/site" }, { label: "抽取模板", path: "/template" }, { label: "代理池管理", path: "/proxy" }, { label: "采集任务", path: "/spider" }, { label: "调度策略", path: "/schedule" }, { label: "反爬对抗", path: "/antibot" }, { label: "限速控制", path: "/ratelimit" }, { label: "失败重试", path: "/retry" }, { label: "字段映射", path: "/extractor" }, { label: "采集流水线", path: "/pipeline" }, { label: "结果校验", path: "/validator" }, { label: "数据落盘", path: "/storage" }, { label: "采集监控", path: "/monitor" }, { label: "数据清洗", path: "/cleanse" }, { label: "增量采集", path: "/delta" }, { label: "数据分发", path: "/export" }, { label: "RPA流程", path: "/rpaflow" }, { label: "登录凭证", path: "/auth" }, { label: "样本血缘", path: "/lineage" }]

export default function App() {
  const [operator] = useState('值班管理员')

  return (
    <div className="app-shell">
      <aside className="app-side">
        <h1 className="app-title">分布式网页采集调度系统</h1>
        <nav className="nav-list">
          {navItems.map((item) => (
            <Link key={item.path} to={item.path} className="nav-item">
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="app-main">
        <header className="app-head">
          <span className="head-desc">面向多站点网页抽取、代理池调度、反爬对抗、增量采集、失败重试与采集结果校验的分布式采集调度系统。</span>
          <span className="head-user">当前值班：{operator}</span>
        </header>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/site" element={<SiteView />} />
          <Route path="/template" element={<TemplateView />} />
          <Route path="/proxy" element={<ProxyView />} />
          <Route path="/spider" element={<SpiderView />} />
          <Route path="/schedule" element={<ScheduleView />} />
          <Route path="/antibot" element={<AntibotView />} />
          <Route path="/ratelimit" element={<RatelimitView />} />
          <Route path="/retry" element={<RetryView />} />
          <Route path="/extractor" element={<ExtractorView />} />
          <Route path="/pipeline" element={<PipelineView />} />
          <Route path="/validator" element={<ValidatorView />} />
          <Route path="/storage" element={<StorageView />} />
          <Route path="/monitor" element={<MonitorView />} />
          <Route path="/cleanse" element={<CleanseView />} />
          <Route path="/delta" element={<DeltaView />} />
          <Route path="/export" element={<ExportView />} />
          <Route path="/rpaflow" element={<RpaflowView />} />
          <Route path="/auth" element={<AuthView />} />
          <Route path="/lineage" element={<LineageView />} />
        </Routes>
      </main>
    </div>
  )
}
