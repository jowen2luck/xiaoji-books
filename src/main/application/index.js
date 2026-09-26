/**
 * @file index.js
 * @description 应用服务统一容器与定位器 (Service Container & Locator)
 */

import BookCatalogRepository from '../infrastructure/persistence/BookCatalogRepository.js'
import BookSearchAdapter from '../infrastructure/retrieval/BookSearchAdapter.js'
import BookService from './BookService.js'
import AnalysisService from './AnalysisService.js'
import InquiryService from './InquiryService.js'
import ReviewService from './ReviewService.js'
import { ToolRegistry } from '../agent/ToolRegistry.js'

let container = null

export function initServices() {
  if (container) return container

  const repo = new BookCatalogRepository()
  const searchAdapter = new BookSearchAdapter(repo)

  const bookService = new BookService(repo)
  const analysisService = new AnalysisService({ searchAdapter, bookService })
  const inquiryService = new InquiryService({ bookService, analysisService })
  const reviewService = new ReviewService({ bookService, analysisService })

  const toolRegistry = new ToolRegistry({
    bookService,
    analysisService,
    inquiryService,
    reviewService
  })

  // 将 toolRegistry 装配到 inquiryService 的 AgentExecutor 中
  inquiryService.setToolRegistry(toolRegistry)

  container = {
    repo,
    searchAdapter,
    bookService,
    analysisService,
    inquiryService,
    reviewService,
    toolRegistry
  }

  return container
}

export function getServices() {
  if (!container) {
    return initServices()
  }
  return container
}
