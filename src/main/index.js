import { app, BrowserWindow, shell, protocol, net, ipcMain } from 'electron'
import { join } from 'path'
import { pathToFileURL } from 'node:url'
import fs from 'node:fs'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import { initServices } from './application/index.js'
import { registerAllIPCHandlers } from './adapters/ipc/index.js'

// 注册本地 PDF 特权协议
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'book-pdf',
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      bypassCSP: true,
      stream: true
    }
  }
])

// 自动加载根目录的 .env 文件
try {
  const envPath = join(process.cwd(), '.env')
  if (fs.existsSync(envPath)) {
    const content = fs.readFileSync(envPath, 'utf-8')
    content.split(/\r?\n/).forEach(line => {
      const trimmed = line.trim()
      if (trimmed && !trimmed.startsWith('#') && trimmed.includes('=')) {
        const [k, ...v] = trimmed.split('=')
        if (k && !process.env[k.trim()]) {
          process.env[k.trim()] = v.join('=').trim()
        }
      }
    })
    console.log('[Main] .env configuration loaded successfully.')
  }
} catch (e) {
  console.warn('[Main] Failed to load .env:', e.message)
}


function getPreloadPath() {
  const mjs = join(__dirname, '../preload/index.mjs')
  const js = join(__dirname, '../preload/index.js')
  
  // 确保 .mjs 和 .js 至少有一者可用，并相互补全
  if (fs.existsSync(mjs) && !fs.existsSync(js)) {
    try { fs.copyFileSync(mjs, js) } catch {}
  } else if (fs.existsSync(js) && !fs.existsSync(mjs)) {
    try { fs.copyFileSync(js, mjs) } catch {}
  }

  const candidates = [
    mjs,
    js,
    join(__dirname, '../preload/index.cjs'),
    join(process.cwd(), 'out/preload/index.mjs'),
    join(process.cwd(), 'out/preload/index.js')
  ]

  for (const c of candidates) {
    if (fs.existsSync(c)) {
      console.log('[Main] Preload script resolved at:', c)
      return c
    }
  }

  console.warn('[Main] Warning: No preload script candidate found!')
  return mjs
}

function createWindow() {
  const preloadPath = getPreloadPath()
  const mainWindow = new BrowserWindow({
    width: 1320,
    height: 880,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    autoHideMenuBar: true,
    title: '图书助手 (Book Assistant)',
    webPreferences: {
      preload: preloadPath,
      sandbox: false,
      contextIsolation: true,
      webSecurity: false
    }
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow.show()
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  // HMR 或生产加载
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
    // 开发模式自动打开 DevTools 便于调试查看
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

app.whenReady().then(() => {
  // 设置 App 用户模型 ID
  electronApp.setAppUserModelId('com.bookassistant.app')

  // 处理本地 PDF 自定义协议 (支持 Windows 绝对盘符路径与各类 URL 变体)
  protocol.handle('book-pdf', (request) => {
    try {
      let raw = request.url.split('#')[0].split('?')[0]
      raw = raw.replace(/^book-pdf:\/\//i, '')
      raw = decodeURIComponent(raw)

      // 去除可能存在的前导斜杠 (如 ///D:/... 或 /D:/...)
      while (raw.startsWith('/') && !/^[a-zA-Z]:/.test(raw)) {
        raw = raw.slice(1)
      }

      // 兼容 Chromium 将盘符 D: 识别为 host 并吃掉冒号变为 "d/..." 或 "D/..." 的情况
      if (/^[a-zA-Z]\//.test(raw)) {
        raw = raw[0].toUpperCase() + ':' + raw.slice(1)
      }

      if (!fs.existsSync(raw)) {
        console.warn('[Main] book-pdf file not found on disk:', raw)
        return new Response('File not found: ' + raw, { status: 404 })
      }

      const fileUrl = pathToFileURL(raw).toString()
      return net.fetch(fileUrl)
    } catch (err) {
      console.error('[Main] Failed to handle book-pdf protocol:', err)
      return new Response('Error loading PDF: ' + err.message, { status: 500 })
    }
  })

  // 允许使用系统原生 PDF 工具打开
  ipcMain.handle('shell:open-path', async (_event, filePath) => {
    try {
      if (filePath && fs.existsSync(filePath)) {
        await shell.openPath(filePath)
        return { success: true }
      }
      return { success: false, error: '文件不存在' }
    } catch (e) {
      return { success: false, error: e.message }
    }
  })

  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  // 初始化应用服务与注册 IPC 通道
  try {
    initServices()
    registerAllIPCHandlers()
    console.log('[Main] Book Assistant services & IPC handlers initialized successfully.')
  } catch (err) {
    console.error('[Main] Failed to initialize services:', err)
  }

  createWindow()

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})
