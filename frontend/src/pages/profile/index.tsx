import { useState } from 'react'
import Taro from '@tarojs/taro'
import { Button, Image, Input, Text, View } from '@tarojs/components'
import pandaLogo from '@/assets/panda-logo.svg'
import { assetUrl, updateProfile, uploadAvatar } from '@/services/api'
import { getAuth } from '@/store/auth'
import '../learning/index.scss'
import './index.scss'

export default function Profile() {
  const current = getAuth().user
  const [name, setName] = useState(current?.nickname || '竹岛学习者')
  const [avatar, setAvatar] = useState(current?.avatar_url || '')
  const [displayName, setDisplayName] = useState(current?.nickname || '竹岛学习者')
  async function save() { try { const user = await updateProfile(name); setDisplayName(user.nickname); setName(user.nickname); Taro.showToast({ title: '资料已保存', icon: 'success' }) } catch (e) { Taro.showToast({ title: e instanceof Error ? e.message : '保存失败', icon: 'none' }) } }
  async function choose(event: any) { const path = event.detail?.avatarUrl; if (!path) return; try { const user = await uploadAvatar(path); setAvatar(user.avatar_url); Taro.showToast({ title: '头像已更新', icon: 'success' }) } catch (error) { Taro.showToast({ title: error instanceof Error ? error.message : '头像上传失败', icon: 'none' }) } }
  const avatarSource = avatar.startsWith('/avatars/') || avatar.startsWith('http') ? assetUrl(avatar) : pandaLogo
  return <View className='learning-page'><View className='learning-appbar'><Text className='settings' onClick={() => Taro.navigateBack()}>‹</Text><Text>个人资料</Text><Text /></View><View className='profile-card'><Button className='avatar-button' openType='chooseAvatar' onChooseAvatar={choose}><Image src={avatarSource} /></Button><Text className='profile-name'>{displayName}</Text><Text className='muted'>☀ {current?.xp_total || 0} XP · 连续 {current?.current_streak_days || 0} 天</Text></View><Text className='field-label'>昵称</Text><Input className='nickname-input' type='nickname' maxlength={24} value={name} placeholder='请输入昵称' onInput={e => setName(e.detail.value)} /><Text className='privacy-note'>昵称和头像只用于展示你的学习资料。你也可以一直使用默认熊猫头像。</Text><Button className='primary-button' onClick={save}>保存资料</Button></View>
}
