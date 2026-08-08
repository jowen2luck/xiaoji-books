# 数据概览 (Layer 0 Scan Report)

> 生成时间: 2026-07-29
> 扫描路径: data/_kage/www.marxists.org/chinese/

## 总量统计

| 指标 | 数值 |
|------|------|
| 总文件数 | 1,534 |
| 总容量 | 12,563 MB (~12.3 GB) |
| PDF 文件 | 1,458 (95%) |
| CHM 文件 | 33 |
| DJVU 文件 | 12 |
| 压缩包 (zip/rar) | 10 |

## 一级分类（按文献主题）

| 分类 | 文件数 | 说明 |
|------|--------|------|
| history_of_international | 334 | 国际共运史（按国别/地区细分） |
| europe | 191 | 欧洲作者文献（法/德/意/波/匈等） |
| ccp | 180 | 中共党史文献（含毛泽东/周恩来/邓小平等） |
| literature | 133 | 文学作品 |
| chinese_marxists | 102 | 中国马克思主义者（陈独秀/李大钊/瞿秋白等） |
| asia | 90 | 亚洲文献（日/韩/越/印尼/印度等） |
| marx-engels | 66 | 马克思恩格斯全集 (MEGA01-MEGA50) |
| america | 56 | 美洲相关文献 |
| lenin | 55 | 列宁著作（含《列宁选集》） |
| lenin-collected-works | 41 | 《列宁全集》补遗 |
| politicaleconomics | 35 | 政治经济学 |
| philosophy | 34 | 哲学文献 |
| biography | 32 | 传记类 |
| archives_of_russia | 25 | 俄罗斯档案选编 |
| russian_communists | 24 | 俄国共产党人（巴枯宁/克鲁泡特金等） |
| che_and_castrol | 17 | 切·格瓦拉与卡斯特罗 |
| class-enemy | 17 | 阶级敌人（反面教材） |
| scientist | 14 | 科学家著作（贝尔纳/维纳/李四光等） |
| latin-america | 10 | 拉丁美洲文献 |
| black-africa | 9 | 黑非洲文献 |
| paris_commune | 8 | 巴黎公社文献 |
| trotsky | 6 | 托洛茨基著作 |
| the_third_international | 5 | 第三国际（共产国际）文献 |
| the_second_international | 3 | 第二国际文献 |
| other | ~20 | 其他杂项 |

## 特殊目录

- `pdf/chinese_marxists/` — 按人物分子目录（mao/, chen_duxiu/, lidazhao/, zhou_enlai/ 等）
- `pdf/ccp/` — 按时期分子目录（1/, 2/, 3/, gd-1921-1949/, deng_xiaoping/, trotskyist/ 等）
- `pdf/history_of_international/` — 按地区分子目录（china/, europe/, asia/, russia/ 等）
- `pdf/europe/` — 按作者分子目录（gramsci/, lukacs/, rosa/, france/, germany/ 等）
- `reference-books/` — 参考工具书 6 份 PDF
- `internationale/` — 《国际歌》相关多媒体（mp3/pdf/zip）

## 下一步（Layer 1 OCR Pipeline）

- [ ] 对 1,458 个 PDF 执行 OCR / 文本提取
- [ ] 恢复 书→卷→章→段 结构
- [ ] 建立段落级索引
- [ ] 对 33 个 CHM 文件进行反编译
- [ ] 对 12 个 DJVU 文件进行文本提取
- [ ] 处理 10 个压缩嵌套文件

## 编目文件输出

- `data/archive-index.json` — 完整文件索引（含 ID、路径、大小、类型、分类）
- `knowledge/graph/relations/catalog.json` — 分类编目摘要
