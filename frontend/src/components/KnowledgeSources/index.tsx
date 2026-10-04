import { Text, View } from '@tarojs/components'
import type { SourceSnapshot } from '@/types/knowledge'
import './index.scss'

export default function KnowledgeSources({ sources, completed }: { sources?: SourceSnapshot; completed: boolean }) {
  if (!completed || !sources) return null
  return <View className='knowledge-sources'><Text className='sources-heading'>{sources.kind === 'original' ? '原题来源快照' : '本题资料依据'}</Text>
    {sources.manually_edited && <Text className='sources-note'>这道原题包含你核对后的修改。</Text>}
    {sources.missing_explanation && <Text className='sources-note'>原文没有提供讲解。</Text>}
    {sources.citations.map((citation, index) => <View className='source-item' key={`${citation.source_id || 'original'}-${index}`}><Text className='source-title'>{citation.title || sources.document_title || '原资料'}{citation.chapter_title || sources.chapter_title ? ` · ${citation.chapter_title || sources.chapter_title}` : ''}</Text><Text className='source-quote'>{citation.quote}</Text>{citation.url && <Text className='sources-note'>{citation.url}</Text>}</View>)}
    <Text className='sources-note'>系统保留了本次学习时的来源。原资料更新或删除后，这份快照仍可查看。</Text>
  </View>
}
