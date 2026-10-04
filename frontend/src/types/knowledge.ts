import type { Option, Quiz, QuestionType } from './api'

export interface KnowledgeCapabilities {
  enabled: boolean; management_available: boolean; parsing_available: boolean; index_available: boolean
  original_practice_available: boolean; supported_extensions: string[]; max_file_bytes: number
  max_bases: number; max_documents: number; max_storage_bytes: number; poll_after_ms: number
}
export interface KnowledgeBase {
  knowledge_base_id: string; name: string; description: string; cover: string; document_count: number
}
export interface KnowledgeDocument {
  document_id: string; knowledge_base_id: string; title: string; file_type: string; file_size: number; version_id: string; version_no: number
  parse_status: string; index_status: string; cleanup_status: string; task_id: string | null; deleted: boolean
}
export interface KnowledgeChapter {
  chapter_id: string; title: string; level: number; parent_chapter_id: string | null; sequence_no: number
  start_offset: number; end_offset: number
}
export interface DocumentPreview {
  document: KnowledgeDocument; text: string; offset: number; total_characters: number; has_more: boolean
  warnings: { code: string; message: string }[]; chapters: KnowledgeChapter[]
}
export interface KnowledgeScope {
  knowledge_base_id: string
  documents: { document_id: string; version_id: string; chapter_ids: string[] | null }[]
}
export interface KnowledgeResult extends Partial<Quiz> {
  draft_id?: string; bank_id?: string; parsed?: boolean; index_available?: boolean; chunk_count?: number
}
export interface KnowledgeTask {
  task_id: string; status: 'queued' | 'running' | 'succeeded' | 'failed'; stage: string; task_type: string
  poll_after_ms: number; processed_count: number; total_count: number | null; document: KnowledgeDocument
  error: { code: string; message: string } | null; result: KnowledgeResult | null
}
export interface OriginalDraftItem {
  id: string; type: QuestionType | 'unknown' | 'unsupported'; stem: string
  options: (Option & { source_label?: string | null })[]; answer: string[]; explanation: string | null
  chapter_id: string | null; source: { quote?: string; start_offset?: number; end_offset?: number; manual?: boolean }
  issues: string[]; excluded: boolean; manually_edited: boolean
}
export interface OriginalDraft {
  draft_id: string; document_id: string; version_id: string; title: string; revision: number; total: number; page: number
  items: OriginalDraftItem[]; can_confirm: boolean; included_count: number; is_current_version: boolean
  coverage: { start_offset: number; end_offset: number; status: string; quote: string }[]; coverage_total: number
  issues: { code: string; message: string }[]; chapters: KnowledgeChapter[]; selected_chapter_ids: string[]
}
export interface QuestionBank {
  bank_id: string; document_id: string; version_id: string; title: string; question_count: number
  selected_chapter_ids: string[] | null; chapters: KnowledgeChapter[]; groups: { group_index: number; question_count: number }[]
}
export interface KnowledgeFile { name: string; size: number; path?: string; file?: File }
export interface SourceSnapshot {
  kind: 'knowledge' | 'original'; document_title?: string; chapter_title?: string; manually_edited?: boolean; missing_explanation?: boolean
  citations: { source_id: string; quote: string; title?: string; chapter_title?: string; url?: string; source_type?: string }[]
}
