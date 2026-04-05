# GCC智库研究动态抓取与摘要工具

基于 Python 的自动化研究流水线，用于采集、提取和生成 MENA 地区智库政策研究的中文纪要，重点聚焦海湾合作委员会（GCC）议题。

由 **shanqizhang** 于 2026 年开发，用于内部研究与技术实验目的。

---

## 功能概述

本工具自动化执行三个阶段的工作流：

1. **抓取**：从目标智库网站（AJCS、Rasanah 等）采集文章标题、日期和链接
2. **提取**：访问各文章页面获取正文，对报告类出版物自动识别并提取 PDF 内容
3. **摘要**：调用 Gemini API 生成结构化中文纪要，输出为适合政策受众阅读的 Word 文档

---

## 项目结构

```
├── scrapers_v2.py       # 第一步：文章列表抓取
├── fetch_fulltext.py    # 第二步：正文与PDF提取
├── summarize.py         # 第三步：AI摘要 → Word输出
└── requirements.txt
```

---

## 环境准备

运行本项目前，请确认以下条件已满足：

**1. Python 版本**
需要 Python 3.10 或以上版本。在终端输入以下命令检查：
```bash
python --version
```

**2. Gemini API Key**
本项目使用 Google Gemini API 生成中文摘要。请前往 [Google AI Studio](https://aistudio.google.com/apikey) 免费申请 API Key，申请后妥善保存，运行时需要用到。

**3. 网络环境**
脚本需要访问境外智库网站（如 studies.aljazeera.net、rasanah-iiis.org），请确保网络可以正常访问这些域名。

---

## 快速上手

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置密钥

**请勿将 API Key 硬编码在代码中。** 建议在运行时传入：

```bash
python summarize.py --input output/gcc_fulltext_YYYYMMDD_HHMM.csv --key 你的API密钥
```

或将密钥存入 `.env` 文件（切勿将此文件提交至版本控制系统）：

```
GEMINI_API_KEY=your_key_here
```

### 3. 运行流水线

```bash
# 第一步：抓取文章列表
python scrapers_v2.py --all

# 第二步：提取正文
python fetch_fulltext.py --input output/gcc_all_sources_YYYYMMDD_HHMM.csv

# 第三步：生成中文摘要 → Word文档
python summarize.py --input output/gcc_fulltext_YYYYMMDD_HHMM.csv --key 你的API密钥
```

每个脚本均支持 `--test` 参数，仅处理前3条数据，适合快速验证。

---

## ⚖️ 许可证与权利声明

本项目采用 **GNU Affero General Public License v3.0（AGPL-3.0）** 进行授权。

**著作权所有：Copyright (c) 2026 shanqizhang。保留所有权利。**

- 任何人（包括公司同事）均可依据 AGPLv3 协议下载、修改及运行本代码。
- 若将本程序或其衍生作品用于网络服务或对外发布，必须公开完整源代码并保留原作者版权声明。
- 公司拥有本版本的内部使用权，但未经作者书面同意，不得将本程序的核心逻辑转售或作为独立产品进行商业化。

---

## ⚠️ 重要免责声明

**使用前请务必阅读：**

- **法律合规**：使用者（个人及所在机构）应自行确保抓取行为符合目标网站的 `robots.txt` 协议及服务条款（ToS），作者不对因违规抓取产生的任何法律后果负责。
- **责任归属**：本程序仅为技术工具，按"现状"提供。作者不对使用者因不当操作导致的 IP 封锁、法律纠纷或数据隐私争议承担任何法律责任。
- **API 费用**：本程序涉及第三方 AI API 调用（Gemini），请使用者自行申请并使用本人或公司的 API Key。因测试或运行产生的任何费用由使用者自行承担，作者概不负责。
- **内容准确性**：摘要由 AI 自动生成，正式发布前请人工核实内容准确性。

---

## 技术支持

如对代码逻辑有疑问，请通过公司内部通讯工具联系作者。
