import Taro from '@tarojs/taro'
import type { LoginData, UserProfile } from '@/types/api'

const KEY = 'bamboo_auth_v1'
export interface AuthState { accessToken: string; refreshToken: string; user: UserProfile | null }
let state: AuthState = Taro.getStorageSync<AuthState>(KEY) || { accessToken: '', refreshToken: '', user: null }
export function getAuth(): AuthState { return state }
export function saveAuth(data: LoginData): void { state = { accessToken: data.access_token, refreshToken: data.refresh_token, user: data.user }; Taro.setStorageSync(KEY, state) }
export function updateUser(user: UserProfile): void { state = { ...state, user }; Taro.setStorageSync(KEY, state) }
export function clearAuth(): void { state = { accessToken: '', refreshToken: '', user: null }; Taro.removeStorageSync(KEY) }
