import { useEffect, useState } from 'react'
import Taro, { useShareAppMessage } from '@tarojs/taro'
import { Button, Canvas, Image, Text, View } from '@tarojs/components'
import pandaHappy from '@/assets/panda-happy.svg'
import { getSession } from '@/store/session'
import './index.scss'

function wrapText(context: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const lines: string[] = []
  let current = ''
  for (const char of text) {
    const next = current + char
    if (context.measureText(next).width > maxWidth && current) {
      lines.push(current)
      current = char
    } else {
      current = next
    }
  }
  if (current) lines.push(current)
  return lines
}

export default function PosterPage() {
  const { quiz, report } = getSession()
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!quiz || !report) Taro.reLaunch({ url: '/pages/index/index' })
  }, [quiz, report])

  useShareAppMessage(() => ({
    title: report?.share_quote || '我在竹知岛完成了一次知识闯关',
    path: '/pages/index/index',
  }))

  if (!quiz || !report) return <View className='page-shell' />

  async function buildPoster(): Promise<string> {
    if (process.env.TARO_ENV !== 'weapp') throw new Error('请在微信开发者工具或真机中保存分享卡')
    const query = Taro.createSelectorQuery()
    const canvasNode = await new Promise<any>((resolve, reject) => {
      query.select('#shareCanvas').fields({ node: true, size: true }).exec((result) => {
        if (!result?.[0]?.node) reject(new Error('分享卡画布初始化失败'))
        else resolve(result[0].node)
      })
    })
    const width = 640
    const height = 1080
    canvasNode.width = width
    canvasNode.height = height
    const context = canvasNode.getContext('2d') as CanvasRenderingContext2D

    context.fillStyle = '#fffdf5'
    context.fillRect(0, 0, width, height)
    context.fillStyle = '#1f6044'
    context.font = '700 26px sans-serif'
    context.fillText('竹知岛 · 今日闯关', 54, 76)

    context.fillStyle = '#202520'
    context.font = '700 54px sans-serif'
    const quoteLines = wrapText(context, report!.share_quote, 500).slice(0, 4)
    quoteLines.forEach((line, index) => context.fillText(line, 54, 190 + index * 72))
    context.fillStyle = '#ffd76a'
    context.fillRect(54, 190 + quoteLines.length * 72 + 10, 74, 10)

    context.fillStyle = '#68736b'
    context.font = '24px sans-serif'
    context.fillText('我刚刚闯过', 54, 570)
    context.fillStyle = '#1f6044'
    context.font = '700 28px sans-serif'
    wrapText(context, `《${quiz!.title.replace('闯关', '').trim()}》 · 掌握度 ${report!.accuracy}%`, 500)
      .slice(0, 2)
      .forEach((line, index) => context.fillText(line, 54, 620 + index * 40))

    try {
      const panda = canvasNode.createImage()
      await new Promise<void>((resolve, reject) => {
        panda.onload = () => resolve()
        panda.onerror = () => reject(new Error('熊猫图片加载失败'))
        panda.src = pandaHappy
      })
      context.drawImage(panda, 44, 740, 215, 230)
    } catch {
      context.fillStyle = '#2f7d59'
      context.beginPath()
      context.arc(145, 850, 72, 0, Math.PI * 2)
      context.fill()
      context.fillStyle = '#fff'
      context.font = '700 30px sans-serif'
      context.fillText('团团', 112, 861)
    }

    context.fillStyle = '#68736b'
    context.font = '20px sans-serif'
    context.fillText('和团团一起，把知识变成关卡', 54, 1025)

    const qrX = 430
    const qrY = 825
    const cell = 22
    context.fillStyle = '#fff'
    context.fillRect(qrX - 16, qrY - 16, 176, 176)
    context.fillStyle = '#202520'
    for (let row = 0; row < 7; row += 1) {
      for (let col = 0; col < 7; col += 1) {
        if ((row + col) % 3 !== 1 || (row < 2 && col < 2) || (row > 4 && col > 4)) {
          context.fillRect(qrX + col * cell, qrY + row * cell, cell - 3, cell - 3)
        }
      }
    }

    const result = await Taro.canvasToTempFilePath({
      canvas: canvasNode,
      x: 0,
      y: 0,
      width,
      height,
      destWidth: width,
      destHeight: height,
      fileType: 'png',
      quality: 1,
    })
    return result.tempFilePath
  }

  async function savePoster(): Promise<void> {
    if (saving) return
    setSaving(true)
    try {
      const path = await buildPoster()
      await Taro.saveImageToPhotosAlbum({ filePath: path })
      Taro.showToast({ title: '分享卡已保存到相册', icon: 'success' })
    } catch (error) {
      Taro.showToast({ title: error instanceof Error ? error.message : '保存失败，请稍后重试', icon: 'none', duration: 2600 })
    } finally {
      setSaving(false)
    }
  }

  return (
    <View className='page-shell poster-page'>
      <View className='appbar'><Text className='icon-button' onClick={() => Taro.navigateBack()}>‹</Text><Text className='appbar-title'>分享学习成果</Text><View className='bar-space' /></View>
      <View className='poster-wrap'>
        <View className='poster-card'>
          <Text className='poster-brand'>竹知岛 · 今日闯关</Text>
          <Text className='poster-quote'>{report.share_quote}</Text>
          <View className='poster-line' />
          <Text className='poster-topic'>我刚刚闯过</Text>
          <Text className='poster-score'>《{quiz.title.replace('闯关', '').trim()}》 · 掌握度 {report.accuracy}%</Text>
          <Image className='poster-panda panda-image' src={pandaHappy} mode='aspectFit' />
          <Text className='poster-foot'>和团团一起，把知识变成关卡</Text>
          <View className='qr-placeholder'><Text>小程序码</Text></View>
        </View>
        <Text className='poster-tip'>保存图片后，你可以发送给微信好友</Text>
        <Button className='primary-button save-button' loading={saving} onClick={savePoster}>{saving ? '正在生成' : '保存到相册'}</Button>
      </View>
      <Canvas id='shareCanvas' canvasId='shareCanvas' type='2d' className='share-canvas' />
    </View>
  )
}

