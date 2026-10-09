import { defineConfig, type UserConfigExport } from '@tarojs/cli'
import path from 'node:path'
import devConfig from './dev'
import prodConfig from './prod'

export default defineConfig<'webpack5'>(async (merge, { command, mode }) => {
  const baseConfig: UserConfigExport<'webpack5'> = {
    projectName: 'bamboo-quiz-miniapp',
    date: '2026-9-13',
    designWidth: 375,
    deviceRatio: {
      375: 2,
      640: 1.17,
      750: 1,
      828: 0.905,
    },
    sourceRoot: 'src',
    outputRoot: 'dist',
    plugins: ['@tarojs/plugin-framework-react'],
    alias: {
      '@': path.resolve(__dirname, '..', 'src'),
    },
    defineConstants: {
      'process.env.TARO_APP_API_BASE_URL': JSON.stringify(process.env.TARO_APP_API_BASE_URL || 'http://127.0.0.1:8000'),
    },
    copy: { patterns: [], options: {} },
    framework: 'react',
    compiler: {
      type: 'webpack5',
      prebundle: { enable: false },
    },
    cache: { enable: true },
    mini: {
      postcss: {
        pxtransform: { enable: true, config: {} },
        url: { enable: true, config: { limit: 10240 } },
        cssModules: { enable: false, config: { namingPattern: 'module', generateScopedName: '[name]__[local]___[hash:base64:5]' } },
      },
    },
    h5: {
      publicPath: '/',
      staticDirectory: 'static',
      router: { mode: 'browser' },
      postcss: {
        autoprefixer: { enable: true, config: {} },
        cssModules: { enable: false, config: { namingPattern: 'module', generateScopedName: '[name]__[local]___[hash:base64:5]' } },
      },
    },
  }
  return merge({}, baseConfig, command === 'build' ? prodConfig : devConfig)
})
