import Taro from '@tarojs/taro'
import { Text, View } from '@tarojs/components'
import type { WebSearchMetadata } from '@/types/api'
import './web-search.scss'

export default function WebSearchInfo({ metadata, completed = false, privateSource }: { metadata?: WebSearchMetadata | null; completed?: boolean; privateSource?: string }) {
  const label = privateSource ? privateSource === 'original' ? '系统保留了原题内容' : metadata?.context_used ? '系统依据私有资料出题，并参考了公开资料' : privateSource === 'review' ? '本次复习包含私有资料题目' : '系统本次依据私有资料出题' : !metadata ? '历史题库未记录搜索状态' : metadata.status === 'success' && metadata.context_used ? '系统已参考联网搜索结果' : metadata.status === 'disabled' ? '系统本次未开启联网搜索' : '系统本次未使用联网资料，题目由模型已有知识生成'
  return <View className='web-search-info'>
    <Text className='web-search-status'>{label}</Text>
    {completed && metadata?.context_used && <>
      <Text className='web-search-note'>以下资料仅作为本次出题参考。</Text>
      {metadata.sources.map((source) => <View className='web-search-source' key={source.source_id}>
        <Text className='web-search-title'>{source.title}</Text>
        {source.published_at && <Text>{source.published_at}</Text>}
        <Text className='web-search-content'>{source.content}</Text>
        <Text className='web-search-link' onClick={() => Taro.setClipboardData({ data: source.url })}>复制来源链接</Text>
      </View>)}
    </>}
  </View>
}
