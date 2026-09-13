declare namespace NodeJS {
  interface ProcessEnv {
    NODE_ENV: 'development' | 'production'
    TARO_ENV: 'weapp' | 'h5'
    TARO_APP_API_BASE_URL?: string
  }
}

declare module '*.svg' {
  const src: string
  export default src
}

