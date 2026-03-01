import pdfplumber
import os
import re
import json
import jieba
import time
from collections import defaultdict

# ==============================================================================
# 🏗️ 工业级索引构建器 (V15 Massive Edition)
# 目标：从 PDF 中自动挖掘百万级关键词索引
# ==============================================================================
PDF_FOLDER = "patent_pdfs"
OUTPUT_FILE = "ipc_massive.json"

# 停用词表：过滤掉无意义的虚词，保证索引质量
STOP_WORDS = {
    "的", "了", "和", "或", "在", "与", "及", "对于", "关于", "一种", "所述",
    "及其", "装置", "方法", "系统", "设备", "用于", "特征", "在于", "包括",
    "进行", "使用", "制造", "处理", "应用", "组合", "至少", "一个", "部分"
}


def extract_tokens(text):
    """
    NLP 核心：使用结巴分词将长句拆解为关键词
    例如："车辆公路行驶的联合控制" -> ["车辆", "公路", "行驶", "联合", "控制"]
    """
    # 1. 清洗非中文字符
    clean_text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', text)

    # 2. 精确模式分词
    words = jieba.cut(clean_text, cut_all=False)

    # 3. 过滤停用词和短词
    tokens = [w for w in words if len(w) >= 2 and w not in STOP_WORDS]
    return tokens


def build_massive_index():
    print("🚀 启动工业级挖掘机，正在对 A-H 所有 PDF 进行 NLP 分词...")
    start_time = time.time()

    # 1. 倒排索引 (Inverted Index)
    # 结构: { "石墨烯": ["C01B", "H01B"], "自动驾驶": ["B60W"] }
    keyword_index = defaultdict(list)

    # 2. 详情库 (用于展示)
    code_details = {}

    # 3. 层级库
    hierarchy = {}

    files = [f for f in os.listdir(PDF_FOLDER) if f.endswith('.pdf') and len(f) == 5]
    files.sort()

    if not files:
        print("❌ 未找到 PDF 文件！")
        return

    # 正则：匹配所有 IPC 条目 (小类 + 组)
    re_entry = re.compile(r'^([A-H]\d{2}[A-Z]\s?\d{0,3}/?\d{0,})\s+(.+)$')

    total_lines = 0
    total_keywords = 0

    for filename in files:
        section = filename[0]
        print(f"📖 正在深度挖掘 {filename} (这可能需要一点时间)...")

        try:
            with pdfplumber.open(os.path.join(PDF_FOLDER, filename)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if not text: continue

                    lines = text.split('\n')
                    for line in lines:
                        line = line.strip()
                        match = re_entry.match(line)

                        if match:
                            raw_code, desc = match.groups()

                            # 标准化代码
                            code = raw_code.replace(" ", "")
                            if '/' in code:
                                code = code[:4] + " " + code[4:]  # A41D 1/00

                            # 存入详情
                            code_details[code] = desc
                            total_lines += 1

                            # === 核心：NLP 分词建索引 ===
                            tokens = extract_tokens(desc)
                            for token in tokens:
                                # 只有当该代码还没在这个词的列表里时才添加 (去重)
                                if code not in keyword_index[token]:
                                    keyword_index[token].append(code)
                                    total_keywords += 1

                            # 建立层级
                            if len(code) == 4:
                                hierarchy[code] = code[:3]
                                hierarchy[code[:3]] = section

        except Exception as e:
            print(f"⚠️ 解析错误 {filename}: {e}")

    # 统计信息
    unique_words = len(keyword_index)
    duration = time.time() - start_time

    print("\n" + "=" * 60)
    print(f"✅ 构建完成！耗时: {duration:.2f} 秒")
    print(f"📚 收录 IPC 条目数: {total_lines}")
    print(f"🧠 提取关键词总量: {unique_words} 个 (这就是您的自动词典)")
    print(f"🔗 索引连接关系数: {total_keywords} 条")
    print("=" * 60)

    # 保存
    print("💾 正在写入巨大的 JSON 文件...")
    data = {
        "index": keyword_index,
        "details": code_details,
        "hierarchy": hierarchy
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)  # 不缩进以减小体积

    print(f"🎉 数据库已生成: {OUTPUT_FILE}")


if __name__ == "__main__":
    build_massive_index()