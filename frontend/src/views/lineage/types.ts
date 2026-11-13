/** 样本血缘模块的接口类型，与后端 routers/lineage.py 返回结构保持一致。 */

export type StageCode = 'collect' | 'extract' | 'cleanse' | 'validate' | 'storage'

export interface SourceItem {
  source_ref: string | null
  batch_id: string
  captured_at: string
  raw_snippet: string
  dedup_key: string | null
}

export interface FieldDiff {
  field: string
  delivered: unknown
  experiment: unknown
}

export interface Segment {
  fingerprint: string
  stage: StageCode
  stage_name: string
  rule_id: string
  rule_version: string
  batch_id: string
  source_ref?: string | null
  input_value: unknown
  output_value: unknown
  transform: string
  status: string
  reasons: string[]
  evidence_gap: boolean
  is_candidate: boolean
  diffs?: FieldDiff[]
  diverged?: boolean
  compare_note?: string
}

export interface SampleListItem {
  id: number
  sample_code: string
  business_key: string
  title: string
  status: string
  quarantined: boolean
  merged: boolean
  evidence_gap: boolean
  resume_stage: StageCode | null
  source_count: number
  segment_count: number
  gap_segment_count: number
  stages: StageCode[]
  final_value: Record<string, unknown> | null
}

export interface SampleDetail extends SampleListItem {
  sources: SourceItem[]
  segments: Segment[]
}

export interface CandidateRule {
  rule_id: string
  stage: StageCode
  stage_name: string
  rule_version: string
  summary: string
}

export interface ExperimentSummary {
  id: number
  experiment_code: string
  sample_code: string
  candidate_rule_id: string
  candidate_stage: StageCode
  candidate_rule_version: string
  created_at: string
  note: string
  first_divergence_stage: StageCode | null
  final_diverged: boolean
  experiment_quarantined: boolean
  carried_evidence_gap: boolean
}

export interface ExperimentDetail extends ExperimentSummary {
  branch: string
  immutable: boolean
  sample_id: number
  segments: Segment[]
  summary: {
    divergence_stages: StageCode[]
    first_divergence_stage: StageCode | null
    final_diverged: boolean
    final_field_diffs: FieldDiff[]
    experiment_quarantined: boolean
    delivered_quarantined: boolean
    delivered_final_untouched: boolean
  }
}

export interface LineageStats {
  sample_total: number
  delivered: number
  quarantined: number
  resume_pending: number
  evidence_gap: number
  merged: number
}
