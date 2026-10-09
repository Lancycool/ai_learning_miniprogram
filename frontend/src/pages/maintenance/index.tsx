import { useMemo, useState } from 'react'
import { Button, Input, Text, View } from '@tarojs/components'
import { getKnowledgeTraces, type KnowledgeTraceItem, type KnowledgeTraceResult } from '@/services/api'
import './index.scss'

const caseLabels: Record<string, string> = { no_retrieval: '没有召回', no_accepted_hit: '没有有效命中', invalid_citation: '引用无效', unsupported_answer: '答案缺少依据', insufficient_material: '资料不足', knowledge_generation_timeout: '生成超时' }
const statusLabels: Record<string, string> = { succeeded: '成功', failed: '失败' }
const formatDate = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const json = (value: unknown) => JSON.stringify(value, null, 2)

function TraceRow({ item }: { item: KnowledgeTraceItem }) {
  const [expanded, setExpanded] = useState(false)
  const badCount = item.bad_cases.length
  return <View className={`trace-row ${badCount ? 'has-bad-case' : ''}`}>
    <View className='trace-summary' onClick={() => setExpanded(!expanded)}>
      <View className='trace-main'>
        <Text className='trace-query'>{item.query || '未记录查询'}</Text>
        <Text className='trace-meta'>{formatDate(item.created_at)} · 任务 {item.task_id}</Text>
      </View>
      <View className='trace-signals'>
        <Text className={`status-pill ${item.status}`}>{statusLabels[item.status] || item.status}</Text>
        {badCount > 0 && <Text className='bad-pill'>{badCount} 个问题</Text>}
        <Text className='chevron'>{expanded ? '−' : '+'}</Text>
      </View>
    </View>
    {expanded && <View className='trace-detail'>
      <View className='detail-grid'>
        <View><Text className='detail-label'>追踪编号</Text><Text className='detail-value'>{item.trace_id}</Text></View>
        <View><Text className='detail-label'>资料编号</Text><Text className='detail-value'>{item.document_id || '—'}</Text></View>
        <View><Text className='detail-label'>引用片段</Text><Text className='detail-value'>{item.selected_source_ids?.length || 0} 条</Text></View>
        <View><Text className='detail-label'>总耗时</Text><Text className='detail-value'>{item.timings?.total_ms ? `${item.timings.total_ms} ms` : '—'}</Text></View>
      </View>
      {badCount > 0 && <View className='bad-case-list'><Text className='section-label'>Bad Case</Text>{item.bad_cases.map(item => <View className='bad-case' key={item.bad_case_id}><Text className={`severity ${item.severity}`}>{item.severity}</Text><View><Text className='bad-case-title'>{caseLabels[item.type] || item.type}</Text><Text className='detail-value'>{json(item.details)}</Text></View></View>)}</View>}
      <Text className='section-label'>召回候选片段</Text>
      {item.retrievals?.length ? item.retrievals.map((hit, index) => <View className={`retrieval-card ${hit.accepted ? 'accepted' : 'rejected'}`} key={`${String(hit.source_id)}-${index}`}><View className='retrieval-head'><Text>#{Number(hit.rank || index + 1)} {String(hit.source_id || '未知片段')}</Text><Text>{hit.distance == null ? '无距离' : `距离 ${Number(hit.distance).toFixed(3)}`}</Text><Text>{hit.accepted ? '已接受' : String(hit.filter_reason || '已过滤')}</Text></View><Text className='retrieval-quote'>{String(hit.quote || '没有保存片段内容')}</Text></View>) : <Text className='empty-detail'>没有记录候选片段。</Text>}
      <View className='trace-json'><Text className='section-label'>引用校验</Text><Text className='code-block'>{json(item.validation || {})}</Text></View>
      {item.error_message && <View className='error-note'><Text>{item.error_code}: {item.error_message}</Text></View>}
    </View>}
  </View>
}

export default function Maintenance() {
  const [key, setKey] = useState(''), [taskId, setTaskId] = useState(''), [documentId, setDocumentId] = useState('')
  const [status, setStatus] = useState(''), [caseType, setCaseType] = useState(''), [page, setPage] = useState(1)
  const [result, setResult] = useState<KnowledgeTraceResult | null>(null), [loading, setLoading] = useState(false), [error, setError] = useState('')
  const query = async (nextPage = 1) => { if (!key.trim()) { setError('请输入维护查询密钥'); return }; setLoading(true); setError(''); try { setResult(await getKnowledgeTraces(key, { taskId, documentId, status, caseType, page: nextPage })); setPage(nextPage) } catch (reason) { setError(reason instanceof Error ? reason.message : '查询失败') } finally { setLoading(false) } }
  const badTotal = useMemo(() => result?.items.reduce((sum, item) => sum + item.bad_cases.length, 0) || 0, [result])
  const totalPages = result ? Math.max(1, Math.ceil(result.total / result.page_size)) : 1
  return <View className='maintenance-page'>
    <View className='maintenance-rail'><Text className='brand-mark'>竹知岛</Text><Text className='rail-kicker'>MAINTENANCE</Text><Text className='rail-title'>检索观测台</Text><Text className='rail-copy'>查看私有资料出题的召回链路，定位没有命中、引用异常和资料不足。</Text><View className='rail-note'><Text>维护者入口</Text><Text>密钥只在本次页面会话中使用。</Text></View></View>
    <View className='maintenance-content'><View className='content-head'><View><Text className='eyebrow'>PRIVATE KNOWLEDGE / TRACE</Text><Text className='page-title'>检索追踪</Text><Text className='page-subtitle'>把模型的答案拆回资料片段，先看证据，再判断问题。</Text></View><Text className='secure-label'>受保护接口</Text></View>
      <View className='filter-panel'><View className='key-field'><Text className='field-label'>维护查询密钥</Text><Input className='maintenance-input key-input' password value={key} onInput={event => setKey(event.detail.value)} placeholder='输入 KNOWLEDGE_TRACE_ADMIN_KEY' /></View><View className='filter-grid'><View><Text className='field-label'>任务编号</Text><Input className='maintenance-input' value={taskId} onInput={event => setTaskId(event.detail.value)} placeholder='可选' /></View><View><Text className='field-label'>资料编号</Text><Input className='maintenance-input' value={documentId} onInput={event => setDocumentId(event.detail.value)} placeholder='可选' /></View><View><Text className='field-label'>任务状态</Text><Input className='maintenance-input' value={status} onInput={event => setStatus(event.detail.value)} placeholder='succeeded / failed' /></View><View><Text className='field-label'>Bad Case 类型</Text><Input className='maintenance-input' value={caseType} onInput={event => setCaseType(event.detail.value)} placeholder='如 no_retrieval' /></View></View><Button className='query-button' loading={loading} onClick={() => void query(1)}>{loading ? '查询中' : '查询追踪'}</Button></View>
      {error && <View className='error-banner'><Text>{error}</Text></View>}
      {result && <><View className='metric-row'><View className='metric-card'><Text className='metric-number'>{result.total}</Text><Text className='metric-label'>保留期内追踪</Text></View><View className='metric-card alert'><Text className='metric-number'>{badTotal}</Text><Text className='metric-label'>当前页 Bad Case</Text></View><View className='metric-card'><Text className='metric-number'>{result.items.filter(item => item.status === 'succeeded').length}</Text><Text className='metric-label'>当前页成功任务</Text></View></View><View className='result-head'><Text className='result-title'>最近追踪</Text><Text className='result-count'>第 {result.page} / {totalPages} 页</Text></View><View className='trace-list'>{result.items.length ? result.items.map(item => <TraceRow item={item} key={item.trace_id} />) : <View className='empty-state'><Text>没有符合筛选条件的追踪。</Text><Text>你可以清空筛选条件后再查询。</Text></View>}</View><View className='pagination'><Button className='page-button' disabled={page <= 1 || loading} onClick={() => void query(page - 1)}>上一页</Button><Text>{result.page} / {totalPages}</Text><Button className='page-button' disabled={page >= totalPages || loading} onClick={() => void query(page + 1)}>下一页</Button></View></>}
    </View>
  </View>
}
