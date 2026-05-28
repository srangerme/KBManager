---
name: kbm-download-paper-pdf
description: 根据论文标题、DOI、URL、arXiv ID、PMCID、citation 或 BibTeX 查找并下载合法公开 PDF。仅使用无需登录、API key、邮箱、VPN、代理或人工请求的来源。
---

# KBManager Download Paper PDF

使用此 skill 时，必须明确告诉用户：`Using skill: kbm-download-paper-pdf`。

根据用户给出的论文信息查找合法公开 PDF，并在找到时下载到
`/tmp/kbm-downloads/<paper-title>.pdf`。

## Boundaries

- 只使用无需邮箱、API key、登录、cookie、VPN、library proxy、订阅权限或人工请求的公开合法来源。
- 不使用 Sci-Hub、LibGen、盗版镜像、paywall bypass、破解代理、登录会话、学校 VPN、EZproxy、Shibboleth、ResearchGate full-text request 或联系作者邮件。
- 跳过 Unpaywall 和 CORE，因为当前 workflow 明确排除需要邮箱或 API key 的方法。
- 不把下载到 `/tmp/kbm-downloads` 的 PDF 自动登记为 KBManager source；只有用户另行要求导入 KBManager 时，才切换到 `kbm-source` workflow。
- 如果找不到合法公开 PDF，不要下载 publisher landing page、HTML、abstract page 或非论文附件来冒充 PDF。

## Inputs

用户输入可能是：

- DOI；
- arXiv URL 或 arXiv ID；
- PubMed Central PMCID；
- title；
- title + authors/year；
- publisher URL；
- author/project/lab/GitHub/Papers With Code URL；
- BibTeX、citation 或混合文本。

先提取并记录可用 paper metadata：

- `title`
- `authors`
- `year`
- `doi`
- `arxiv_id`
- `pmcid` 或 `pmid`
- `source_url`

如果 title/DOI/arXiv/PMCID 均无法确定，先向用户说明缺少可检索信息，并请求更完整的 title、DOI 或 URL。

## Legal Search Order

按以下顺序查找合法公开 PDF。每一步只使用公开网页或无需凭证的公开 API。

1. **Direct PDF URL**
   - 如果输入 URL 本身疑似 PDF，先验证它是公开 PDF。
   - URL 后缀 `.pdf` 不足以证明；仍需验证 `Content-Type` 或文件头。

2. **arXiv**
   - 从 `arxiv.org/abs/<id>`、`arxiv.org/pdf/<id>` 或文本中提取 arXiv ID。
   - PDF URL 使用 `https://arxiv.org/pdf/<id>.pdf`。
   - 如果只有 title，可在 arXiv 公开搜索中查询 title 和作者。

3. **PubMed Central**
   - 如果有 PMCID，优先使用 PMC 开放全文 PDF。
   - 如果只有 DOI/PMID/title，可查找是否存在 PMC 页面。
   - 仅下载 PMC 页面明确提供的开放 PDF。

4. **OpenAlex**
   - 用 DOI 或 title 查询 OpenAlex。
   - 使用返回的 OA location、best OA location、repository URL 或 PDF URL。
   - 不依赖需要邮箱或 key 的服务。

5. **Semantic Scholar**
   - 用 DOI/title 查询公开可见结果。
   - 只使用明确公开的 `openAccessPdf` 或页面中公开指向的 PDF。

6. **HAL, OSF, Institutional Repositories**
   - 查找 HAL、OSF、MIT DSpace、Stanford Digital Repository、CMU RI Repository、ETH Research Collection、Berkeley eScholarship 等机构仓库。
   - 只下载仓库页面公开提供的 author manuscript、accepted manuscript 或 published OA PDF。

7. **Author/Lab/Project Pages**
   - 查找作者主页、实验室主页、项目页、课程页或论文列表。
   - 只下载作者或项目页面公开链接的 PDF。

8. **Papers With Code and GitHub**
   - 使用 Papers With Code、GitHub README、release、project page 中公开链接的 PDF。
   - GitHub 附带 PDF 必须是论文 PDF，而不是无关 supplementary、slides 或 report，除非用户明确接受。

## Download Procedure

1. 创建下载目录：

   ```bash
   mkdir -p /tmp/kbm-downloads
   ```

2. 验证候选 PDF：
   - 优先用 `curl -L -I <url>` 检查 HTTP status 和 `Content-Type`。
   - 若服务器不支持 HEAD，用小范围 GET 或临时下载后检查文件头。
   - 有效 PDF 应满足：
     - HTTP 成功状态；
     - `Content-Type` 是 `application/pdf`、`application/octet-stream` 且文件头为 PDF，或文件头以 `%PDF` 开始；
     - 文件大小不是明显的错误页或空文件。

3. 生成文件名：
   - 优先使用提取到的 title。
   - 去掉 `/`, `\`, `:`, `*`, `?`, `"`, `<`, `>`, `|` 等路径危险字符。
   - 压缩连续空白为单个空格。
   - 去掉首尾空白和点。
   - 文件名过长时截断到约 180 个字符。
   - 如果 title 不可用，使用 DOI、arXiv ID 或 `paper`。
   - 保存为 `/tmp/kbm-downloads/<sanitized-title>.pdf`。
   - 若目标文件已存在且内容不同，追加短后缀，例如 `-2` 或 DOI/arXiv 片段。

4. 下载：

   ```bash
   curl -L --fail --retry 2 --connect-timeout 20 --max-time 120 -o "/tmp/kbm-downloads/<sanitized-title>.pdf" "<pdf-url>"
   ```

5. 下载后再次验证：
   - 检查文件存在且非空。
   - 检查文件头包含 `%PDF`。
   - 如果验证失败，删除该失败文件，并继续尝试下一个合法候选。

## Reporting

成功时报告：

- saved path；
- paper title；
- authors/year，如已知；
- DOI/arXiv/PMCID，如已知；
- PDF 来源 URL；
- 合法来源类型，例如 arXiv、PMC、OpenAlex OA repository、author page。

失败时报告：

- 已提取的 paper metadata；
- 已尝试的合法来源；
- 为什么不能下载，例如：
  - 未找到无需凭证的公开 PDF；
  - publisher 页面只有摘要或订阅下载；
  - 候选 URL 不是 PDF；
  - 来源需要 API key、邮箱、登录、VPN、library proxy 或人工请求；
  - 网络请求失败或服务器返回错误。

不要建议用户使用非法下载站点。可以建议用户使用学校图书馆/VPN、ResearchGate 请求全文或邮件联系作者，但必须说明这些需要用户自行操作，不能由此 workflow 自动下载。
