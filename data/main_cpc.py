import json
import os
import re
import jieba
import webbrowser
import time
from collections import defaultdict, Counter
from pyvis.network import Network

# --- 1. Import OpenAI SDK ---
try:
    from openai import OpenAI
except ImportError:
    print("❌ Please install dependencies: pip install openai pyvis")
    exit()

# ==============================================================================
# ⚙️ Configuration Area
# ==============================================================================
# ⚠️⚠️⚠️ Enter your Aliyun API Key here ⚠️⚠️⚠️
DASHSCOPE_API_KEY = "sk-569d9c8b329c48038af583b0ce6bc5f2"

BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = "qwen-plus"

# ==============================================================================
# 📚 Resource Loading
# ==============================================================================
DB_FILE = "cpc_database.json"

try:
    from cpc_dict import FULL_SYNONYM_DICT

    CANDIDATE_KEYS = list(FULL_SYNONYM_DICT.keys())
except ImportError:
    CANDIDATE_KEYS = []
    FULL_SYNONYM_DICT = {}


# ==============================================================================
# 🧠 AI Core Class
# ==============================================================================
class QwenBrain:
    def __init__(self):
        if "sk-xxx" in DASHSCOPE_API_KEY:
            self.client = None
        else:
            self.client = OpenAI(api_key=DASHSCOPE_API_KEY, base_url=BASE_URL)
        self.trans_cache = {}

    def route(self, user_query):
        """ Intent Routing """
        if not self.client: return []
        print(f"🧠 [AI] Analyzing core domain...")
        prompt = f"""
        User Input: "{user_query}"
        Select 1-3 most relevant technical domain tags from the list below.
        List: {json.dumps(CANDIDATE_KEYS, ensure_ascii=False)}
        Output only a JSON list.
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
        """ Keyword Expansion """
        if not self.client: return [user_query]
        print(f"🧠 [AI] Expanding keywords...")
        prompt = f"""
        Expand the query "{user_query}" with synonyms and hyponyms.
        Return a JSON string list containing 5-8 words.
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
        """ Translation """
        if not text: return "No Description"
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
# 🔍 Core Search Engine (Execution)
# ==============================================================================
class CPCSearchEngine:
    def __init__(self):
        self.brain = QwenBrain()
        self.details = {}
        self.index = {}
        self.family_tree = defaultdict(list)

        # 🌟 State Storage
        self.current_query = ""
        self.current_strategy = {}  # Stores codes and keywords
        self.current_results = []  # Stores search results

    def load_db(self):
        if not os.path.exists(DB_FILE):
            print(f"❌ Cannot find {DB_FILE}")
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
        print(f"✅ Engine Ready (Loaded {len(self.details)} nodes)")
        return True

    def _get_node_info(self, code):
        raw = self.details.get(code, {})
        if isinstance(raw, dict):
            return raw.get('title', 'Unknown'), raw.get('def', '')
        elif isinstance(raw, str):
            return raw, ""
        return "Unknown", ""

    # ==========================================================================
    # 🌟 Module 1: Strategy Formulation (AI + NLP)
    # ==========================================================================
    def step1_analyze(self, query):
        self.current_query = query
        print(f"\n⚙️ [Step 1] Formulating search strategy: {query} ...")

        # A. Determine core classification codes
        ai_keys = self.brain.route(query)
        matched_codes = []
        if ai_keys:
            for key in ai_keys:
                codes = FULL_SYNONYM_DICT.get(key, [])
                matched_codes.extend(codes)

        # B. Determine search keywords
        expanded_kws = self.brain.expand_keywords(query)
        jieba_kws = [w for w in jieba.cut(query) if len(w) >= 2]
        final_kws = list(set(expanded_kws + jieba_kws))

        # Store strategy
        self.current_strategy = {
            "codes": matched_codes,
            "keywords": final_kws
        }

        print("\n" + "-" * 40)
        print("✅ Strategy formulated")
        print(f"   🎯 Locked Codes: {matched_codes}")
        print(f"   🔑 Locked Keywords: {final_kws}")
        print("-" * 40 + "\n")

    # ==========================================================================
    # 🌟 Module 2: Execute Search (Python)
    # ==========================================================================
    def step2_search(self):
        if not self.current_strategy:
            print("⚠️ Please execute Step 1 to formulate a strategy first!")
            return

        print(f"⚙️ [Step 2] Scanning database...")
        scores = Counter()

        target_codes = self.current_strategy["codes"]
        target_kws = self.current_strategy["keywords"]

        # A. Core weighting
        if target_codes:
            for anchor in target_codes:
                family = self.family_tree.get(anchor, [])
                if not family:
                    for db in self.details.keys():
                        if db.startswith(anchor): family.append(db)
                for code in family: scores[code] += 5000

        # B. Keyword search
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
        print(f"✅ Search complete: Found {len(self.current_results)} relevant nodes (Top 100 captured)")

    # ==========================================================================
    # 🌟 Module 3: Generate Graph (Visual)
    # ==========================================================================
    def step3_visualize(self):
        if not self.current_results:
            print("⚠️ Please execute Step 2 to get results first!")
            return

        print(f"⚙️ [Step 3] Drawing graph...")
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
        net.add_node(root_code, label=f"[Core]\n{root_code}\n{root_zh[:6]}", title=f"{root_zh}", color='#004085',
                     size=50, shape='box', font={'color': 'white'})

        total = len(final_nodes)
        for i, item in enumerate(final_nodes):
            code = item['code']
            en, df = self._get_node_info(code)
            if i % 10 == 0: print(f"   visualizing... {i}/{total}")  # Progress hint
            zh = self.brain.translate(en, code)

            if item['type'] == 'core':
                color, shape, dashes, prefix = '#dc3545', 'box', False, "[Subclass]"
            else:
                color, shape, dashes, prefix = '#fd7e14', 'diamond', True, "[Related]"

            net.add_node(code, label=f"{prefix}\n{code}\n{zh[:8]}", title=f"{zh}\n{en}", color=color, shape=shape,
                         size=30, font={'color': 'white'})
            net.add_edge(root_code, code, color=color, dashes=dashes)

        net.set_options(
            """{"layout": {"hierarchical": {"enabled": true, "direction": "UD", "sortMethod": "directed"}}, "physics": {"enabled": false}}""")
        net.save_graph("cpc_step3_graph.html")
        print(f"✅ Graph generated: cpc_step3_graph.html")
        try:
            webbrowser.open("cpc_step3_graph.html")
        except:
            pass

    # ==========================================================================
    # 🌟 Module 4: AI Architect Report (Restructured V14.0)
    # ==========================================================================
    def step4_report(self):
        if not self.current_results:
            print("⚠️ Please execute Step 2 to get results first!")
            return

        print(f"\n⚙️ [Step 4] AI is reconstructing search results as an architect...")

        # 1. Select data (Top 40)
        results = self.current_results[:40]
        top_code = results[0][0]
        root_code = top_code[:4]

        # 2. Build Context-Rich Data
        structured_data = []
        print("   Preprocessing data and translating...")
        for code, score in results:
            en, _ = self._get_node_info(code)
            zh = self.brain.translate(en, code)

            item = {
                "code": code,
                "title_cn": zh,
                "title_en": en,
                "relationship": "Core Family" if code.startswith(root_code) else "Cross Domain",
                "relevance_score": score
            }
            structured_data.append(item)

        # 3. Write Architect Prompt
        prompt = f"""
        You are a "Technical Architect" proficient in the CPC patent classification system.
        User Query: "{self.current_query}"

        The system retrieved the following discrete classification codes (JSON format):
        {json.dumps(structured_data, ensure_ascii=False, indent=2)}

        【Task: Reconstruct Hierarchy Tree】
        Analyze the hierarchical relationship of CPC codes (e.g., B60W 30/00 is the parent of B60W 30/08) and the user's intent.
        Output a standard **Vertical Structure Tree**.

        **Strict Output Format Requirement**:
        Do not output any conversational filler, introductions, or summary conclusions. 
        Only output the tree structure exactly as shown below:

        [Core] Root Code | Chinese Name (English Name)
          - [Subclass] Code Range | Description
            - [Detail] Code | Description
            - [Detail] Code | Description
          - [Subclass] Code Range | Description
            - [Detail] Code | Description

        [Cross-Domain] (Missing! Should exist but not detected) -> Code | Description
        [Cross-Domain] (Missing! Should exist but not detected) -> Code | Description

        **Crucial Logic**:
        1. Group the provided JSON codes into the tree under [Core] or [Subclass].
        2. Identify "Missing" codes based on the user query. For example, if the query is "WiFi Positioning" but results lack H04W or G01S, list them under [Cross-Domain] (Missing!).
        3. Do not add any other text. Just the tree.
        """

        try:
            print("⏳ AI is building hierarchy and analyzing blind spots (approx 20s)...")
            resp = self.brain.client.chat.completions.create(
                model=MODEL_NAME, messages=[{"role": "user", "content": prompt}], temperature=0.2
            )
            report = resp.choices[0].message.content

            print("\n" + "=" * 60)
            print(report)  # Print directly to console for user
            print("=" * 60 + "\n")

            filename = "cpc_architect_report.md"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"📄 Architect report saved to: {filename}")

            # Auto open report
            try:
                os.startfile(filename)
            except:
                pass

        except Exception as e:
            print(f"❌ Report generation failed: {e}")


# ==============================================================================
# 🎮 Main Program (Interactive Menu)
# ==============================================================================
if __name__ == "__main__":
    engine = CPCSearchEngine()
    if engine.load_db():
        print("\n🤖 CPC Modular Search System (V14.0 Architect)")

        while True:
            print("\n" + "-" * 30)
            print(f"Current Query: [{engine.current_query if engine.current_query else 'Not Set'}]")
            print("[1] 🧠 Input Query & Formulate Strategy")
            print("[2] 🔍 Execute Database Search")
            print("[3] 📊 Generate Visual Graph")
            print("[4] 📝 Generate Architect Analysis Report (Gap Analysis)")
            print("[0] Exit")
            choice = input("👉 Select Option: ").strip()

            if choice == '1':
                q = input("Enter technical description: ").strip()
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
                print("❌ Invalid Input")