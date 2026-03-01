import pdfplumber
import os
import re
import json
from collections import defaultdict, Counter

# ==========================================
# 1. 配置与初始化
# ==========================================
PDF_FOLDER = "patent_pdfs"  # PDF文件所在目录
FILES = ["A.pdf", "B.pdf", "C.pdf", "D.pdf", "E.pdf", "F.pdf", "G.pdf", "H.pdf"]


class IPCKnowledgeEngine:
    def __init__(self):
        # 存储正向数据: { "H04N": "图像通信..." }
        self.ipc_definitions = {}
        # 存储层级关系: { "H": "电学", "H04": "电通信技术", ... }
        self.hierarchy = {}
        # 存储反向索引 (强硬映射库): { "图像": ["H04N", "G06T"], "酿酒": ["C12G"] }
        self.inverted_index = defaultdict(list)

    # ==========================================
    # 2. PDF 挖掘核心 (构建映射库)
    # ==========================================
    def build_knowledge_base(self):
        print("🏗️ 正在初始化 IPC 强硬映射库，这可能需要几十秒...")

        for filename in FILES:
            filepath = os.path.join(PDF_FOLDER, filename)
            if not os.path.exists(filepath):
                print(f"⚠️ 跳过缺失文件: {filename}")
                continue

            section_char = filename[0]  # 'A', 'B'...
            print(f"📖 正在深度解析 {filename} (建立 {section_char} 部索引)...")

            try:
                with pdfplumber.open(filepath) as pdf:
                    # 遍历每一页
                    for page in pdf.pages:
                        text = page.extract_text()
                        if not text: continue
                        self._parse_page_text(text, section_char)
            except Exception as e:
                print(f"❌ 解析错误 {filename}: {e}")

        print(f"✅ 知识库构建完成！包含 {len(self.ipc_definitions)} 个分类节点，{len(self.inverted_index)} 个关键词索引。")

    def _parse_page_text(self, text, section):
        """
        解析逻辑：使用正则提取 IPC 编号和描述
        这里针对常见的 IPC PDF 格式进行正则匹配
        """
        lines = text.split('\n')

        # 正则表达式匹配不同层级
        # 匹配小类 (Subclass) 如 H04N
        re_subclass = re.compile(r'^([A-H]\d{2}[A-Z])\s+(.+)$')
        # 匹配大类 (Class) 如 H04
        re_class = re.compile(r'^([A-H]\d{2})\s+(.+)$')
        # 匹配部 (Section) 这里的PDF通常第一页有部名，简化处理

        for line in lines:
            line = line.strip()

            # 1. 尝试匹配小类 (最核心的检索层级)
            match_sub = re_subclass.match(line)
            if match_sub:
                code, desc = match_sub.groups()
                # 存入正向库
                self.ipc_definitions[code] = desc
                self.hierarchy[code] = desc
                # 建立倒排索引 (分词)
                self._index_keywords(code, desc)
                continue

            # 2. 尝试匹配大类
            match_class = re_class.match(line)
            if match_class:
                code, desc = match_class.groups()
                self.hierarchy[code] = desc
                continue

    def _index_keywords(self, code, text):
        """
        将描述文本拆解为关键词，存入倒排索引
        """
        # 简单分词逻辑：保留中文、英文单词，过滤标点
        # 如果需要更强分词，可引入 jieba
        # 这里使用正则提取所有连续的汉字或英文单词
        tokens = re.findall(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z0-9]{3,}', text)

        # 过滤无意义词 (停用词表可扩展)
        stop_words = {"及其", "用于", "使用", "方法", "装置", "系统", "制造", "处理", "details", "systems", "methods"}

        for token in tokens:
            token = token.lower()
            if token not in stop_words:
                self.inverted_index[token].append(code)

    # ==========================================
    # 3. 强硬检索逻辑 (关键词匹配)
    # ==========================================
    def search(self, user_query):
        """
        根据用户输入，在映射库中打分匹配
        """
        # 1. 对用户输入分词
        query_tokens = re.findall(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z0-9]{3,}', user_query)

        # 2. 计分板 {IPC_CODE: Score}
        scores = Counter()

        found_keywords = []

        for token in query_tokens:
            token = token.lower()
            # 在倒排索引里查
            if token in self.inverted_index:
                found_keywords.append(token)
                matched_codes = self.inverted_index[token]
                for code in matched_codes:
                    scores[code] += 1

        if not scores:
            return None, []

        # 3. 获取最高分的 Code
        best_code, score = scores.most_common(1)[0]
        return best_code, found_keywords

    # ==========================================
    # 4. 输出格式化 (复刻层级表)
    # ==========================================
    def generate_report(self, user_query, best_code, keywords):
        if not best_code:
            print("❌ 强硬规则库中未找到匹配项。请尝试使用更标准的关键词。")
            return

        section = best_code[0]  # H
        main_class = best_code[:3]  # H04
        sub_class = best_code  # H04N

        # 获取名称 (如果在PDF里提取到了就用，没提取到就用占位符)
        section_title = self.hierarchy.get(section, f"{section}部")
        class_title = self.hierarchy.get(main_class, "相关大类")
        sub_class_title = self.ipc_definitions.get(sub_class, "未知定义")

        print("\n" + "=" * 60)
        print(f"🚀 IPC 强硬匹配报告 | 关键词命中: {keywords}")
        print("=" * 60)
        print(f"| 层级 (Level) | 编号 (Symbol) | 名称 (Definition) | 备注 |")
        print(f"| :--- | :--- | :--- | :--- |")
        print(f"| **部** | {section} | {section_title} | - |")
        print(f"| **大类** | {main_class} | {class_title} | - |")
        print(f"| **👉 核心小类** | **{sub_class}** | **{sub_class_title}** | **匹配度最高** |")
        print(f"| └─ 匹配理由 | - | - | 基于关键词 '{' '.join(keywords)}' 在官方文档中的命中 |")
        print("=" * 60 + "\n")


# ==========================================
# 主程序入口
# ==========================================
if __name__ == "__main__":
    # 1. 实例化并构建库 (一次性加载)
    engine = IPCKnowledgeEngine()
    engine.build_knowledge_base()

    print("\n🔍 IPC 本地强硬检索系统 (Ready)")
    print("💡 匹配逻辑完全基于 A.pdf - H.pdf 的内容")

    while True:
        try:
            q = input("\n👉 请输入技术关键词 (q退出): ").strip()
            if q.lower() in ['q', 'exit']: break
            if not q: continue

            # 2. 检索
            code, kw = engine.search(q)

            # 3. 输出
            engine.generate_report(q, code, kw)

        except KeyboardInterrupt:
            break