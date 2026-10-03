import { PropsWithChildren } from 'react'
import { useLaunch } from '@tarojs/taro'
import { ensureLogin } from '@/services/api'
import './app.scss'

export default function App({ children }: PropsWithChildren) {
  useLaunch(() => {
    ensureLogin().catch(() => {
      // 页面请求会展示具体错误。启动阶段不打断用户进入首页。
    })
  })
  return children
}
