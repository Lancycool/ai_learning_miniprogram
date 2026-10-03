import { useRef, useState } from 'react'
import Taro, { useDidShow } from '@tarojs/taro'
import { Button, Image, Text, Textarea, View } from '@tarojs/components'
import pandaHappy from '@/assets/panda-happy.svg'
import pandaLogo from '@/assets/panda-logo.svg'
import pandaSad from '@/assets/panda-sad.svg'
import pandaThinking from '@/assets/panda-thinking.svg'
import { ApiError, ensureLogin, generateQuiz } from '@/services/api'
import { clearSession, startSession } from '@/store/session'
import { getAuth } from '@/store/auth'
import { setActiveTab } from '@/store/navigation'
import { useNavigationLayout } from '@/utils/navigation'
import type { UserProfile } from '@/types/api'
import './index.scss'

type PageState = 'home' | 'loading' | 'error'

const examples = ['为什么天空是蓝色？', '三分钟理解 RAG', '咖啡为什么能提神？']

export default function IndexPage() {
  const navigation = useNavigationLayout()
  const [pageState, setPageState] = useState<PageState>('home')
  const [topic, setTopic] = useState('')
  const [errorMessage, setErrorMessage] = useState('系统没有得到完整的题目。你的学习内容不会丢失。')
  const [user, setUser] = useState<UserProfile | null>(getAuth().user)
  const requestToken = useRef(0)

  useDidShow(() => {
    setActiveTab(0)
    ensureLogin().then(setUser).catch(() => undefined)
  })

  async function submit(): Promise<void> {
    const normalized = topic.trim()
    if (!normalized) {
      Taro.showToast({ title: '请先告诉团团你想学什么', icon: 'none' })
      return
    }
    const token = ++requestToken.current
    clearSession()
    setPageState('loading')
    try {
      const quiz = await generateQuiz(normalized)
      if (token !== requestToken.current) return
      startSession(quiz)
      await Taro.navigateTo({ url: '/pages/quiz/index' })
      setPageState('home')
    } catch (error) {
      if (token !== requestToken.current) return
      setErrorMessage(error instanceof ApiError ? error.message : '生成失败，请稍后重试。')
      setPageState('error')
    }
  }

  function cancel(): void {
    requestToken.current += 1
    setPageState('home')
  }

  if (pageState === 'loading') {
    return (
      <View className='page-shell tab-page loading-page' style={{ paddingTop: `${navigation.contentTop}px` }}>
        <View className='appbar'><Text className='back' onClick={cancel}>‹</Text><Text className='appbar-title'>准备关卡</Text><View className='bar-space' /></View>
        <View className='loading-center'>
          <View className='plant-scene'>
            <Image className='panda-image thinking-panda' src={pandaThinking} mode='aspectFit' />
            <View className='bamboo-plant' />
          </View>
          <Text className='loading-title'>团团正在种下关卡</Text>
          <Text className='loading-description'>系统正在整理“{topic.trim()}”，通常需要几秒钟。</Text>
          <View className='loading-steps'>
            <View className='loading-step done'><Text className='step-dot'>✓</Text><Text>找到主题里的核心概念</Text></View>
            <View className='loading-step done'><Text className='step-dot'>✓</Text><Text>整理常见误区</Text></View>
            <View className='loading-step active'><Text className='step-dot' /><Text>生成 5 道闯关题</Text></View>
          </View>
          <Button className='quiet-action' onClick={cancel}>取消生成</Button>
        </View>
      </View>
    )
  }

  if (pageState === 'error') {
    return (
      <View className='page-shell tab-page error-page' style={{ paddingTop: `${navigation.contentTop}px` }}>
        <View className='appbar'><Text className='back' onClick={() => setPageState('home')}>‹</Text><Text className='appbar-title'>准备关卡</Text><View className='bar-space' /></View>
        <View className='error-content'>
          <Image className='panda-image error-panda' src={pandaSad} mode='aspectFit' />
          <Text className='error-title'>这次没有种出关卡</Text>
          <Text className='error-copy'>{errorMessage}</Text>
          <View className='error-reason'><Text className='reason-title'>你可以这样处理：</Text><Text>检查网络后重试，或把主题写得更具体一些。</Text></View>
          <Button className='primary-button' onClick={submit}>重新生成</Button>
          <Button className='quiet-action' onClick={() => setPageState('home')}>返回修改内容</Button>
        </View>
      </View>
    )
  }

  return (
    <View className='page-shell tab-page home-page' style={{ paddingTop: `${navigation.statusBarHeight}px` }}>
      <View className='appbar home-appbar' style={{ height: `${navigation.navigationBarHeight}px`, paddingRight: `${navigation.rightInset}px` }}>
        <View className='brand'><View className='brand-mark'><Image src={pandaLogo} mode='aspectFit' /></View><Text>竹知岛</Text></View>
      </View>
      <View className='home-account' onClick={() => Taro.switchTab({ url: '/pages/learning/index' })}>
        <View className='home-greeting'><Text className='home-greeting-label'>你好，</Text><Text className='home-user'>{user?.nickname || '竹岛学习者'}</Text></View>
        <View className='mini-xp'><Text>☀</Text><Text>{user?.xp_total || 0} XP</Text></View>
      </View>
      <View className='home-intro'>
        <View className='intro-copy'><Text className='home-title'>今天想闯过{`\n`}什么知识？</Text><Text className='home-description'>你给团团一个主题，团团把它变成五道小关卡。</Text></View>
        <Image className='panda-image home-panda' src={pandaHappy} mode='aspectFit' />
      </View>
      <View className='input-panel'>
        <Text className='input-label'>输入一句话或一段文字</Text>
        <Textarea
          className='topic-input'
          maxlength={2000}
          value={topic}
          placeholder='例如：我想弄懂 RAG 和普通搜索有什么区别'
          onInput={(event) => setTopic(event.detail.value)}
        />
        <View className='input-tools'>
          <Text onClick={() => Taro.showToast({ title: '文档和链接导入将在下一版开放', icon: 'none' })}>＋ 文档或链接</Text>
          <Text>{topic.length} / 2000</Text>
        </View>
      </View>
      <View className='examples'>
        <Text className='examples-label'>没有想法？你可以从这里开始</Text>
        <View className='chips'>
          {examples.map((example) => <Text className='chip' key={example} onClick={() => setTopic(example)}>{example}</Text>)}
        </View>
      </View>
      <Button className='primary-button home-cta' onClick={submit}>让团团生成关卡 <Text>➜</Text></Button>
      <Text className='safe-note'>AI 内容可能有误，重要知识请再核对。</Text>
    </View>
  )
}
