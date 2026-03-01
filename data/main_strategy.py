import json
import os
import re
import jieba
import webbrowser
import time
from collections import defaultdict, Counter
from pyvis.network import Network

# --- 1. 引入 OpenAI SDK ---
try:
    from openai import OpenAI
except ImportError:
    print("❌ 请先安装依赖: pip install openai pyvis")
    exit()

# ==============================================================================
# ⚙️ 配置区域
# ==============================================================================
# ⚠️⚠️⚠️ 请在此处填入您的阿里云 API Key ⚠️⚠️⚠️
DASHSCOPE_API_KEY = "sk-569d9c8b329c48038af583b0ce6bc5f2"

BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = "qwen-plus"

# ==============================================================================
# 📚 资源加载
# ==============================================================================
DB_FILE = "cpc_database.json"

try:
    from cpc_dict import FULL_SYNONYM_DICT

    CANDIDATE_KEYS = list(FULL_SYNONYM_DICT.keys())
except ImportError:
    CANDIDATE_KEYS = []
    FULL_SYNONYM_DICT = {}


# ==============================================================================
# 🧠 AI 核心类 (负责思考)
# ==============================================================================
class QwenBrain:
    def __init__(self):
        if "sk-xxx" in DASHSCOPE_API_KEY:
            self.client = None
        else:
            self.client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=BASE_URL)
        self.trans_cache = {}

    def route(self, user_query):
        """ 意图路由 """
        if not self.client: return []
        print(f"🧠 [AI] 正在分析核心领域...")
        prompt = f"""
        用户输入: "{user_query}"
        请选出 1-3 个最相关的技术领域标签。
        列表: {json.dumps(CANDIDATE_KEYS, ensure_ascii=False)}
        只输出JSON列表。
        """
        try:
            resp = self.client.chat.completions.create(
                model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.1
            )
            content = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
            tags = json.loads(content)
            if isinstance(tags, list):
                return [t for t in tags if t in CANDIDATE_KEYS]
            return []
        except:
            return []

    def expand_keywords(self, user_query):
        """ 关键词裂变 """
        if not self.client: return [user_query]
        print(f"🧠 [AI] 正在扩展关键词...")
        prompt = f"""
        扩展查询词 "{user_query}" 的同义词、下位词。
        返回包含 5-8 个词的 JSON 字符串列表。
        """
        try:
            resp = self.client.chat.completions.create(
                model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.3
            )
            content = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
            keywords = json.loads(content)
            if isinstance(keywords, list):
                if user_query not in keywords: keywords.insert(0, user_query)
                return keywords
            return [user_query]
        except:
            return [user_query]

    def translate(self, text, code):
        """ 翻译 """
        if not text: return "无描述"
        if text in self.trans_cache: return self.trans_cache[text]
        if not self.client: return text
        prompt = f"""Translate CPC title to concise Chinese. Original: "{text}". Code: "{code}". Output only Chinese."""
        try:
            resp = self.client.chat.completions.create(
                model="qwen-turbo", messages=[{"role": "user", "content": prompt}], temperature=0.1
            )
            zh = resp.choices[0].message.content.strip()
            self.trans_cache[text] = zh
            return zh
        except:
            return text


# ==============================================================================
# 🔍 核心检索引擎 (负责执行)
# ==============================================================================
class CPCSearchEngine:
    def __init__(self):
        self.brain = QwenBrain()
        self.details = {}
        self.index = {}
        self.family_tree = defaultdict(list)

        # 🌟 状态存储 (用于分步执行)
        self.current_query = ""
        self.current_strategy = {}  # 存储分类号和关键词
        self.current_results = []  # 存储检索结果

    def load_db(self):
        if not os.path.exists(DB_FILE):
            print(f"❌ 找不到 {DB_FILE}")
            return False
        with open(DB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.details = data["details"]
            self.index = data["index"]
            if "family_tree" in data:
                self.family_tree = data["family_tree"]
            else:
                for code in self.details.keys():
                    if len(code) >= 4: self.family_tree[code[:4]].append(code)
        print(f"✅ 引擎就绪 (加载 {len(self.details)} 节点)")
        return True

    def _get_node_info(self, code):
        raw = self.details.get(code, {})
        if isinstance(raw, dict):
            return raw.get('title', 'Unknown'), raw.get('def', '')
        elif isinstance(raw, str):
            return raw, ""
        return "Unknown", ""

    # ==========================================================================
    # 🌟 模块 1: 策略制定 (AI + NLP)
    # ==========================================================================
    def step1_analyze(self, query):
        self.current_query = query
        print(f"\n⚙️ [Step 1] 正在制定检索策略: {query} ...")

        # A. 确定核心分类号
        ai_keys = self.brain.route(query)
        matched_codes = []
        if ai_keys:
            for key in ai_keys:
                codes = FULL_SYNONYM_DICT.get(key, [])
                matched_codes.extend(codes)

        # B. 确定检索关键词
        expanded_kws = self.brain.expand_keywords(query)
        jieba_kws = [w for w in jieba.cut(query) if len(w) >= 2]
        final_kws = list(set(expanded_kws + jieba_kws))

        # 存储策略
        self.current_strategy = {
            "codes": matched_codes,
            "keywords": final_kws
        }

        print("\n" + "-" * 40)
        print("✅ 策略制定完成")
        print(f"   🎯 锁定分类: {matched_codes}")
        print(f"   🔑 锁定词表: {final_kws}")
        print("-" * 40 + "\n")

    # ==========================================================================
    # 🌟 模块 2: 执行检索 (Python)
    # ==========================================================================
    def step2_search(self):
        if not self.current_strategy:
            print("⚠️ 请先执行 Step 1 制定策略！")
            return

        print(f"⚙️ [Step 2] 正在扫描数据库...")
        scores = Counter()

        target_codes = self.current_strategy["codes"]
        target_kws = self.current_strategy["keywords"]

        # A. 核心加权
        if target_codes:
            for anchor in target_codes:
                family = self.family_tree.get(anchor, [])
                if not family:
                    for db in self.details.keys():
                        if db.startswith(anchor): family.append(db)
                for code in family: scores[code] += 5000

        # B. 关键词检索
        candidates = set()
        for kw in target_kws:
            if kw in self.index: candidates.update(self.index[kw])

        for code in candidates:
            title, _ = self._get_node_info(code)
            score = 0
            for kw in target_kws:
                if kw in title: score += 50
            if score > 0: scores[code] += score

        self.current_results = scores.most_common(100)
        print(f"✅ 检索完成: 找到 {len(self.current_results)} 个相关节点 (Top 100 已截取)")

    # ==========================================================================
    # 🌟 模块 3: 生成图谱 (Visual)
    # ==========================================================================
    def step3_visualize(self):
        if not self.current_results:
            print("⚠️ 请先执行 Step 2 获取结果！")
            return

        print(f"⚙️ [Step 3] 正在绘制图谱...")
        results = self.current_results
        top_code = results[0][0]
        root_code = top_code[:4]
        root_en, _ = self._get_node_info(root_code)
        root_zh = self.brain.translate(root_en, root_code)

        nodes_list = []
        for code, score in results:
            if code == root_code: continue
            if code.startswith(root_code):
                nodes_list.append({"code": code, "type": "core", "score": score})
            else:
                nodes_list.append({"code": code, "type": "cross", "score": score})

        nodes_list.sort(key=lambda x: x['score'], reverse=True)
        final_nodes = nodes_list[:40]

        net = Network(height="95vh", width="100%", bgcolor="#f8f9fa", font_color="#333333", select_menu=True)
        net.add_node(root_code, label=f"[核心]\n{root_code}\n{root_zh[:6]}", title=f"{root_zh}", color='#004085',
                     size=50, shape='box', font={'color': 'white'})

        total = len(final_nodes)
        for i, item in enumerate(final_nodes):
            code = item['code']
            en, df = self._get_node_info(code)
            if i % 10 == 0: print(f"   translating... {i}/{total}")  # 进度提示
            zh = self.brain.translate(en, code)

            if item['type'] == 'core':
                color, shape, dashes, prefix = '#dc3545', 'box', False, "[子类]"
            else:
                color, shape, dashes, prefix = '#fd7e14', 'diamond', True, "[旁系]"

            net.add_node(code, label=f"{prefix}\n{code}\n{zh[:8]}", title=f"{zh}\n{en}", color=color, shape=shape,
                         size=30, font={'color': 'white'})
            net.add_edge(root_code, code, color=color, dashes=dashes)

        net.set_options(
            """{"layout": {"hierarchical": {"enabled": true, "direction": "UD", "sortMethod": "directed"}}, "physics": {"enabled": false}}""")
        net.save_graph("cpc_step3_graph.html")
        print(f"✅ 图谱已生成: cpc_step3_graph.html")
        try:
            webbrowser.open("cpc_step3_graph.html")
        except:
            pass

    # ==========================================================================
    # 🌟 模块 4: AI 深度报告 (LLM Refinement)
    # ==========================================================================
    def step4_report(self):
        if not self.current_results:
            print("⚠️ 请先执行 Step 2 获取结果！")
            return

        print(f"\n⚙️ [Step 4] AI 正在阅读 Top 30 结果，准备优化与撰写...")

        results = self.current_results[:40]  # 只给AI看前40个，省Token
        top_code = results[0][0]
        root_code = top_code[:4]

        # 1. 数据结构化
        structured_data = []
        for code, score in results:
            if code == root_code: continue
            rtype = "核心子类" if code.startswith(root_code) else "跨界旁系"
            en, _ = self._get_node_info(code)
            zh = self.brain.translate(en, code)
            structured_data.append({"code": code, "type": rtype, "title": zh})

        # 2. 编写优化 Prompt
        prompt = f"""
        你是一位高级专利情报专家。用户查询词："{self.current_query}"。
        检索系统返回了以下原始技术分类数据（JSON）：
        {json.dumps(structured_data, ensure_ascii=False, indent=2)}

        【你的任务】
        请根据上述原始数据，输出一份经过**优化、去重、补漏**的 Markdown 分析报告。

        1. **技术归纳（优化）**：不要简单罗列。请将这些技术点归纳为 3-4 个逻辑清晰的技术簇（例如：核心算法、硬件载体、应用场景）。
        2. **去重清洗**：如果列表里有含义重复的节点（例如多个关于“定位”的相似分类），请在报告中将它们合并叙述。
        3. **盲点侦测（补漏）**：这是关键！基于用户查询，指出上述列表中明显缺失的关键技术环节（例如搜“电动车”如果有电池，是否缺了充电桩？）。
        4. **下一步建议**：给出更精准的组合搜索词。
        """

        try:
            print("⏳ AI 正在思考 (约15秒)...")
            resp = self.brain.client.chat.completions.create(
                model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.4
            )
            report = resp.choices[0].message.content
            print("\n" + "=" * 60)
            print(report)
            print("=" * 60 + "\n")
            with open("cpc_step4_report.md", "w", encoding="utf-8") as f:
                f.write(report)
            print("📄 报告已保存至: cpc_step4_report.md")
        except Exception as e:
            print(f"❌ 报告生成失败: {e}")


# ==============================================================================
# 🎮 主程序 (交互菜单)
# ==============================================================================
if __name__ == "__main__":
    engine = CPCSearchEngine()
    if engine.load_db():
        print("\n🤖 CPC 模块化检索系统 (V13.0 Modular)")

        while True:
            print("\n" + "-" * 30)
            print(f"当前查询: [{engine.current_query if engine.current_query else '未设置'}]")
            print("[1] 🧠 输入查询 & 制定策略")
            print("[2] 🔍 执行数据库检索")
            print("[3] 📊 生成可视化图谱")
            print("[4] 📝 生成深度分析报告")
            print("[0] 退出")
            choice = input("👉 请选择操作: ").strip()

            if choice == '1':
                q = input("请输入技术描述: ").strip()
                if q: engine.step1_analyze(q)
            elif choice == '2':
                engine.step2_search()
            elif choice == '3':
                engine.step3_visualize()
            elif choice == '4':
                engine.step4_report()
            elif choice == '0':
                break
            else:
                print("❌ 无效输入")