import { useState } from 'react'
import Taro, { useResize } from '@tarojs/taro'

interface NavigationLayout {
  statusBarHeight: number
  navigationBarHeight: number
  rightInset: number
  contentTop: number
}

function readNavigationLayout(): NavigationLayout {
  if (process.env.TARO_ENV !== 'weapp') {
    return { statusBarHeight: 20, navigationBarHeight: 48, rightInset: 0, contentTop: 20 }
  }

  let statusBarHeight = 24
  let windowWidth = 375
  try {
    const info = typeof Taro.getWindowInfo === 'function' ? Taro.getWindowInfo() : Taro.getSystemInfoSync()
    if (typeof info.statusBarHeight === 'number' && Number.isFinite(info.statusBarHeight) && info.statusBarHeight > 0) statusBarHeight = info.statusBarHeight
    if (Number.isFinite(info.windowWidth) && info.windowWidth > 0) windowWidth = info.windowWidth
  } catch {
    // A conservative default also works before device information is available.
  }

  let navigationBarHeight = 48
  let rightInset = 96
  try {
    const menu = Taro.getMenuButtonBoundingClientRect()
    if (menu.width > 0 && menu.height > 0 && menu.top >= statusBarHeight && menu.bottom > menu.top && menu.left > 0 && menu.right <= windowWidth) {
      const menuGap = menu.top - statusBarHeight
      navigationBarHeight = Math.max(44, menu.bottom - statusBarHeight + menuGap)
      // Page horizontal padding is 20 design pixels on a 375-wide design.
      const pageInset = 20 * windowWidth / 375
      rightInset = Math.max(0, windowWidth - menu.left + 10 - pageInset)
    }
  } catch {
    // Keep the right side clear when the capsule API is temporarily unavailable.
  }

  return {
    statusBarHeight,
    navigationBarHeight,
    rightInset,
    contentTop: statusBarHeight + navigationBarHeight + 12,
  }
}

export function useNavigationLayout(): NavigationLayout {
  const [layout, setLayout] = useState(readNavigationLayout)
  useResize(() => { setLayout(readNavigationLayout()) })
  return layout
}
