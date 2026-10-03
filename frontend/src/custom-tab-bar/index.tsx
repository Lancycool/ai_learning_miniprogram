import { useRef, useSyncExternalStore } from 'react'
import Taro from '@tarojs/taro'
import { Button, Text, View } from '@tarojs/components'
import { getActiveTab, subscribeTabBar } from '@/store/navigation'
import type { TabIndex } from '@/store/navigation'
import './index.scss'

const tabs = [
  { index: 0, label: '闯关', path: '/pages/index/index', icon: 'flag' },
  { index: 1, label: '我的', path: '/pages/learning/index', icon: 'user' },
] as const

export default function CustomTabBar() {
  const selected = useSyncExternalStore(subscribeTabBar, getActiveTab, getActiveTab)
  const switching = useRef(false)

  async function switchTab(index: TabIndex, path: string): Promise<void> {
    if (switching.current || selected === index) return
    switching.current = true
    try {
      await Taro.switchTab({ url: path })
    } catch {
      Taro.showToast({ title: '页面切换失败，请重试', icon: 'none' })
    } finally {
      switching.current = false
    }
  }

  return (
    <View className='island-tabbar' ariaRole='navigation' ariaLabel='底部导航'>
      <View className='island-tabbar__items'>
        {tabs.map((tab) => (
          <Button
            key={tab.path}
            className={`island-tabbar__item ${selected === tab.index ? 'island-tabbar__item--active' : ''}`}
            hoverClass='island-tabbar__item--pressed'
            ariaLabel={`${tab.label}${selected === tab.index ? '，当前页面' : ''}`}
            onClick={() => switchTab(tab.index, tab.path)}
          >
            <View className={`island-tabbar__icon island-tabbar__icon--${tab.icon}`}>
              <View className='island-tabbar__icon-part' />
              <View className='island-tabbar__icon-part' />
            </View>
            <Text className='island-tabbar__label'>{tab.label}</Text>
          </Button>
        ))}
      </View>
    </View>
  )
}
