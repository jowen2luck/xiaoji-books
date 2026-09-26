/**
 * @file run_ingest.js
 * @description 命令行一键扫描切片并索引已处理好的书籍
 * 运行方式: node scripts/run_ingest.js
 */

import BookIngestionPipeline from '../src/main/pipeline/BookIngestionPipeline.js'

async function main() {
  console.log('========================================================')
  console.log('📚 图书助手 — 已处理书籍自动化切片与全量索引入库管道')
  console.log('📌 规则：只识别并纳入已提取/OCR处理好的书，未处理生书坚决不纳入')
  console.log('========================================================')

  const pipeline = new BookIngestionPipeline()
  const stats = await pipeline.run({ force: false })

  console.log('\n✅ 扫描切片与索引构建完成：')
  console.log(`- 扫描候选批次目录数: ${stats.scannedDirs}`)
  console.log(`- 发现具有提取内容的图书: ${stats.discoveredBooks} 本`)
  console.log(`- 本次新增入库与索引: ${stats.newlyIngested} 本`)
  console.log(`- 索引段落切片总数: ${stats.totalParagraphsIndexed} 段`)
  console.log(`- 过滤排除未处理生书: ${stats.skippedUntreated} 本`)
  if (stats.errors.length > 0) {
    console.warn(`- 警告/错误数: ${stats.errors.length}`)
  }
}

main().catch(err => {
  console.error('Pipeline failed:', err)
  process.exit(1)
})
